"""make predict IN=tickets.jsonl OUT=pred.jsonl

Обрабатывает тикеты в порядке created_at (так работает дедупликация «за час»),
пишет ответы в исходном порядке. Ответы админов во входе игнорируются.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from copilot.llm import from_env  # noqa: E402
from copilot.pipeline import Copilot  # noqa: E402


def fallback(kind, reason: str) -> dict:
    """Ответ на тикет, который не удалось разобрать: категория валидна, решает человек."""
    cat = "complaint.other" if kind == "complaint" else "report.question"
    return {"lang": "und", "category": cat, "priority": "p2", "is_spam_or_duplicate": False,
            "extracted": {"nickname": None, "rule_refs": [], "has_evidence": False, "server": None},
            "draft_reply": {"lang": "ru", "text": "", "cited": []}, "needs_human": True, "confidence": 0.0,
            "reasons": [reason]}


def _sort_key(item):
    i, d = item
    created = d.get("created_at") if isinstance(d, dict) else None
    return (created if isinstance(created, str) else "", i)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--debug", action="store_true", help="оставить служебное поле _meta")
    args = ap.parse_args()

    cp = Copilot(llm=from_env())
    rows = []
    with open(args.inp, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append((i, json.loads(line)))
            except json.JSONDecodeError:
                rows.append((i, None))     # битая строка: ответ-заглушка на её месте
    order = sorted(rows, key=_sort_key)
    results = {}
    t0 = time.time()
    for i, d in order:
        if not isinstance(d, dict):
            results[i] = fallback(None, "строка не является JSON-объектом: нужен человек")
            continue
        try:
            payload = dict(d)
            payload["messages"] = [m for m in (d.get("messages") or []) if isinstance(m, dict) and m.get("role") != "admin"]
            r = cp.triage(payload)
        except Exception as e:  # один битый тикет не должен ронять прогон
            r = fallback(d.get("kind"), f"ошибка обработки: {type(e).__name__}")
        if not args.debug:
            r = {k: v for k, v in r.items() if not k.startswith("_")}
        if d.get("ticket_id"):
            r = {"ticket_id": d["ticket_id"], **r}
        results[i] = r
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for i, _ in rows:
            f.write(json.dumps(results[i], ensure_ascii=False) + "\n")
    dt = time.time() - t0
    print(f"{len(rows)} tickets -> {args.out} in {dt:.1f}s", file=sys.stderr)
    if cp.llm is not None:
        print("LLM stats:", json.dumps(cp.llm.stats), file=sys.stderr)


if __name__ == "__main__":
    main()
