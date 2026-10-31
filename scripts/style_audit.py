"""Аудит стиля ответов: сколько черновиков нарушают запреты (тире, слеши, эмодзи, разметка, штампы) до и после фильтра.

    python scripts/style_audit.py --in data/tickets_valid.jsonl       шаблоны, без LLM
    python scripts/style_audit.py --in data/tickets_valid.jsonl --llm  с LLM из COPILOT_LLM_* (тексты уходят во внешний API)

Наружу идут только агрегаты (reports/style_audit.json): ни текстов игроков, ни текстов черновиков в отчёте нет.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from copilot import llm as llm_mod, style  # noqa: E402
from copilot.pipeline import Copilot  # noqa: E402


def load_rows(path: Path) -> list[dict]:
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt", encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def payload_of(row: dict) -> dict:
    if "messages" in row:
        p = dict(row)
    else:
        p = {"kind": row["kind"], "messages": [{"role": "player", "text": row.get("text", ""), "attachments": row.get("att", 0)}]}
        for k in ("server_lang", "region"):
            if row.get(k):
                p[k] = row[k]
    p["messages"] = [m for m in p["messages"] if m.get("role") != "admin"]
    return p


def run(rows, data_dir, models_dir, llm, filter_on: bool) -> list[dict]:
    original = style.apply_draft
    if not filter_on:
        style.apply_draft = lambda d: d
    try:
        cp = Copilot(data_dir, models_dir, llm=llm)
        return [cp.triage(payload_of(r), use_dedup=True) for r in rows]
    finally:
        style.apply_draft = original


def summarize(resps: list[dict]) -> dict:
    codes, per_lang = collections.Counter(), collections.defaultdict(collections.Counter)
    bad = 0
    for r in resps:
        dr = r["draft_reply"]
        found = style.issues(dr["text"], dr["lang"])
        bad += bool(found)
        for f in found:
            code = f.split(":")[0]
            codes[code] += 1
            per_lang[dr["lang"]][code] += 1
    n = len(resps)
    return {"tickets": n, "tickets_with_violation": bad, "share": round(bad / max(1, n), 4), "by_code": dict(codes),
            "by_lang": {k: dict(v) for k, v in sorted(per_lang.items())}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(ROOT / "data/tickets_valid.jsonl"))
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--models-dir", default=str(ROOT / "models"))
    ap.add_argument("--llm", action="store_true", help="включить LLM из COPILOT_LLM_*")
    ap.add_argument("--out", default=str(ROOT / "reports/style_audit.json"))
    ap.add_argument("--pairs", help="куда записать пары «шаблон и ответ LLM» для ручной проверки: только reports/private, там тексты игроков")
    args = ap.parse_args()

    rows = load_rows(Path(args.inp))
    rows.sort(key=lambda r: (r.get("created_at") or ""))
    llm = llm_mod.from_env() if args.llm else None
    if args.llm and llm is None:
        sys.exit("COPILOT_LLM_BASE_URL, COPILOT_LLM_API_KEY и COPILOT_LLM_MODEL не заданы")

    after_resps = run(rows, args.data_dir, args.models_dir, llm, filter_on=True)
    report = {"llm": bool(llm), "filter_on": summarize(after_resps),
              "needs_human_share_filter_on": round(sum(r["needs_human"] for r in after_resps) / max(1, len(after_resps)), 3)}
    if llm:
        # живая модель отвечает по-разному от запуска к запуску и каждый запуск стоит денег: прогон «без фильтра» не делаем
        report["llm_stats"] = llm.report()
        report["tickets_llm_consulted"] = sum(r["_meta"]["llm"] for r in after_resps)
        if args.pairs:
            plain = run(rows, args.data_dir, args.models_dir, None, filter_on=True)
            Path(args.pairs).parent.mkdir(parents=True, exist_ok=True)
            with open(args.pairs, "w", encoding="utf-8") as f:
                for row, a, b in zip(rows, after_resps, plain):
                    if a["_meta"]["llm"]:
                        text = " ".join(m.get("text") or "" for m in payload_of(row)["messages"] if m.get("role", "player") == "player")
                        f.write(json.dumps({"ticket_id": row.get("ticket_id"), "player_text": text, "template": b["draft_reply"]["text"],
                                            "llm": a["draft_reply"]["text"], "reasons": a["reasons"]}, ensure_ascii=False) + "\n")
    else:
        before_resps = run(rows, args.data_dir, args.models_dir, llm, filter_on=False)
        report["filter_off"] = summarize(before_resps)
        report["texts_changed_by_filter"] = sum(a["draft_reply"]["text"] != b["draft_reply"]["text"]
                                                for a, b in zip(before_resps, after_resps))
    after = report["filter_on"]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if after["tickets_with_violation"] else 0


if __name__ == "__main__":
    sys.exit(main())
