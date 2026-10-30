"""Оценка качества черновиков: проверки-инварианты, которые не требуют разметки категорий.

Два режима:
  python scripts/eval_drafts.py                       синтетика из tests/fixtures + правила из tests/fixtures (без data/ и models/)
  python scripts/eval_drafts.py --in data/tickets_valid.jsonl   реальные тикеты, правила и модели из data/ и models/

Проверяется по каждому ответу: схема, язык черновика (ожидаемый и по детектору), существование каждого номера пункта в
тексте (а не только в cited), отсутствие обещаний разбана и возврата, обязательные эскалации, ожидаемый needs_human.
Наружу идут только агрегаты (reports/draft_quality_*.json). Для реальных данных дополнительно пишется выборка для ручной
проверки в reports/private/ (там тексты игроков, она в .gitignore и не публикуется).
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import random
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from copilot import lang as lang_mod  # noqa: E402
from copilot.pipeline import NEEDS_HUMAN_ALWAYS, Copilot  # noqa: E402
from copilot.taxonomy import ALL_CATS  # noqa: E402

# любой номер вида 2.1 или 1.2.3 вне ссылок: «п. 2.1», «2.1-тармағы», а также голое «нарушение 2.4»
_REF_IN_TEXT = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{1,2}){1,2})(?![\d.]*\d)")
# собственный список обещаний оценщика: не зависит от copilot.guard, чтобы сравнивать версии кода одной линейкой
_PROMISE_EVAL = re.compile("|".join([
    r"(будет|будут|будете) (снят|снято|сняты|разбанен|разблокирован|возвращен|возвращ[её]н|восстановлен)",
    r"\bвернем\b|\bвернём\b|\bвозместим\b|компенсируем|\bразбаним\b|\bснимем\b|\bвосстановим\b",
    r"\b(бан|мут|варн|warn|наказани\w*|блокировк\w*|деморган)\s+(уже\s+|был\s+|будет\s+)?(снят\w*|отмен[её]н\w*|аннулирован\w*)",
    r"\b(деньги|денег|средства|донат\w*|имущество|аккаунт\w*|машин\w*)\s+(уже\s+|были\s+|будут\s+)?"
    r"(возвращ[её]н\w*|вернут\w*|вернуты|восстановлен\w*)",
    r"гарантиру\w+|гарантия\b",
    r"қайтарамыз|алып тастаймыз|қалпына келтіреміз", r"qaytaramiz|olib tashlaymiz|tiklaymiz|bandan chiqaramiz",
    r"\bwe will (unban|refund|restore|return|lift)\b|\bwill be (unbanned|refunded|restored|lifted)\b",
]), re.I)
REQUIRED = ("lang", "category", "priority", "is_spam_or_duplicate", "extracted", "draft_reply", "needs_human",
            "confidence", "reasons")


def check(resp: dict, known_refs: set[str], expect: dict | None = None) -> list[str]:
    expect = expect or {}
    bad = []
    if any(k not in resp for k in REQUIRED) or resp.get("category") not in ALL_CATS:
        bad.append("schema")
        return bad
    dr = resp["draft_reply"]
    text = dr.get("text") or ""
    if not text.strip():
        bad.append("empty_text")
    want = expect.get("lang")
    if want and dr.get("lang") != want:
        bad.append("lang_expected")
    letters = sum(ch.isalpha() for ch in text)
    if letters >= 25:
        got = lang_mod.detect(re.sub(r"https?://\S+", " ", text))
        if got != dr.get("lang") and not (dr.get("lang") == "ru" and got == "uk"):
            bad.append("lang_detected")
    for m in _REF_IN_TEXT.finditer(text):
        if m.group(1) not in known_refs:
            bad.append("ref_not_in_rules")
            break
    if _PROMISE_EVAL.search(text):
        bad.append("promise")
    if resp["category"] in NEEDS_HUMAN_ALWAYS and not resp["needs_human"]:
        bad.append("always_human_missed")
    if resp["priority"] == "p0" and not resp["needs_human"]:
        bad.append("p0_not_human")
    if expect.get("human") and not resp["needs_human"]:
        bad.append("human_expected")
    return bad


def _payload(row: dict) -> dict:
    if "messages" in row:
        return row
    p = {"kind": row["kind"], "messages": [{"role": "player", "text": row.get("text", ""), "attachments": row.get("att", 0)}]}
    for k in ("server_lang", "region"):
        if row.get(k):
            p[k] = row[k]
    return p


def load_rows(path: Path) -> list[dict]:
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt", encoding="utf-8") as f:
        if path.suffix == ".json":
            return json.load(f)
        return [json.loads(x) for x in f if x.strip()]


def group_of(resp: dict, payload: dict) -> list[str]:
    g = [f"lang:{resp['draft_reply'].get('lang')}", f"cat:{resp['category']}"]
    sl = payload.get("server_lang")
    if sl in ("kk", "uz"):
        g.append(f"server:{sl}")
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", help="jsonl/jsonl.gz с тикетами; без флага берётся синтетика")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--models-dir", default=str(ROOT / "models"))
    ap.add_argument("--sample", type=int, default=60, help="размер выборки для ручной проверки (только реальные данные)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out")
    args = ap.parse_args()

    tmp = None
    if args.inp:
        rows, mode = load_rows(Path(args.inp)), "real"
        cp = Copilot(args.data_dir, args.models_dir)
        rows.sort(key=lambda r: (r.get("created_at") or ""))
    else:
        mode = "synthetic"
        rows = load_rows(ROOT / "tests/fixtures/synthetic_tickets.json")
        tmp = tempfile.mkdtemp()
        shutil.copy(ROOT / "tests/fixtures/rules_mini.json", Path(tmp) / "rules.json")
        cp = Copilot(tmp, Path(tmp) / "no_models")
    known = {p.ref for p in cp.rules.points.values()}

    fails, by_group, n_group = collections.Counter(), collections.defaultdict(collections.Counter), collections.Counter()
    failed_ids, scored = [], []
    for row in rows:
        payload = _payload(row)
        payload["messages"] = [m for m in payload["messages"] if m.get("role") != "admin"]
        resp = cp.triage(payload, use_dedup=(mode == "real"))
        bad = check(resp, known, row if mode == "synthetic" else None)
        for g in group_of(resp, payload):
            n_group[g] += 1
            for b in bad:
                by_group[g][b] += 1
        for b in bad:
            fails[b] += 1
        if bad:
            failed_ids.append({"id": row.get("id") or row.get("ticket_id"), "problems": bad})
        scored.append((row, payload, resp, bad))

    n = len(rows)
    report = {"mode": mode, "tickets": n, "tickets_with_any_problem": len(failed_ids),
              "problems": dict(fails), "problem_rate": round(len(failed_ids) / max(1, n), 4),
              "needs_human_share": round(sum(r["needs_human"] for _, _, r, _ in scored) / max(1, n), 3),
              "by_group": {g: {"n": n_group[g], "problems": dict(c)} for g, c in sorted(by_group.items())},
              "groups_total": dict(sorted(n_group.items()))}
    if mode == "synthetic":
        report["failed"] = failed_ids          # id синтетических кейсов не содержат данных игроков
    out = Path(args.out or ROOT / f"reports/draft_quality_{mode}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("by_group", "groups_total")}, ensure_ascii=False, indent=1))

    if mode == "real":
        rnd = random.Random(args.seed)
        strata = collections.defaultdict(list)
        for i, (row, payload, resp, bad) in enumerate(scored):
            lg = resp["draft_reply"].get("lang")
            key = lg if lg in ("kk", "uz") else (resp["category"] if resp["category"] in
                  ("complaint.other", "complaint.invalid", "report.question") else "rest")
            strata[key].append(i)
        quota = {"kk": 12, "uz": 12, "complaint.other": 12, "complaint.invalid": 8, "report.question": 8, "rest": 8}
        pick = []
        for key, q in quota.items():
            pool = strata.get(key, [])
            pick += rnd.sample(pool, min(q, len(pool)))
        pick = pick[:args.sample]
        priv = ROOT / "reports/private/draft_review_sample.jsonl"
        priv.parent.mkdir(parents=True, exist_ok=True)
        with open(priv, "w", encoding="utf-8") as f:
            for i in pick:
                row, payload, resp, bad = scored[i]
                text = " ".join(m.get("text") or "" for m in payload["messages"] if m.get("role", "player") == "player")
                f.write(json.dumps({"ticket_id": row.get("ticket_id"), "kind": payload.get("kind"), "player_text": text,
                                    "category": resp["category"], "needs_human": resp["needs_human"],
                                    "draft": resp["draft_reply"], "auto_problems": bad,
                                    "review": {"answers_question": None, "rules_correct": None, "language_ok": None,
                                               "no_forbidden_promises": None, "clear_and_useful": None,
                                               "needs_admin_correct": None, "comment": ""}},
                                   ensure_ascii=False) + "\n")
        print(f"выборка для ручной проверки: {priv} ({len(pick)} шт., не коммитится)")
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if fails.get("promise") or fails.get("ref_not_in_rules") or fails.get("always_human_missed") else 0


if __name__ == "__main__":
    sys.exit(main())
