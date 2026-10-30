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
            if line:
                rows.append((i, json.loads(line)))
    order = sorted(rows, key=lambda x: (x[1].get("created_at") or "", x[0]))
    results = {}
    t0 = time.time()
    for i, d in order:
        payload = dict(d)
        payload["messages"] = [m for m in d.get("messages", []) if m.get("role") != "admin"]
        try:
            r = cp.triage(payload)
        except Exception as e:  # один битый тикет не должен ронять прогон
            r = {"lang": "und", "category": None, "priority": "p2", "is_spam_or_duplicate": False,
                 "extracted": {"nickname": None, "rule_refs": [], "has_evidence": False, "server": None},
                 "draft_reply": {"lang": "ru", "text": "", "cited": []}, "needs_human": True, "confidence": 0.0,
                 "reasons": [f"ошибка обработки: {type(e).__name__}"]}
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
