"""Правильность ответов базы знаний внутри конвейера: для репортов train со сценарием question_kb смотрим, назвал ли админ тот же маршрут.

Gold: в ответе админа есть последний элемент маршрута записи («Правительство», «Автошкола»…) как отдельное слово.
Это нижняя оценка правильности: админ мог ответить иначе, но верно. Тексты не сохраняются, печатаются счётчики.

    python experiments/final_polish/kb_pipeline_precision.py [--split dev|test|all]
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "draft_audit"))
import common as C  # noqa: E402
from copilot import kb  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="all")
    a = ap.parse_args()
    from copilot.pipeline import Copilot

    cp = Copilot()
    paths = {e.key: re.compile(r"(?<!\w)" + re.escape(e.path.split(">")[-1].strip()) + r"(?!\w)", re.I) for e in kb.KB if e.path}
    with gzip.open(ROOT / "data" / "tickets_train.jsonl.gz", "rt", encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    rows = [r for r in rows if r["kind"] == "report"
            and (a.split == "all" or ("dev" if int(hashlib.md5(str(r["ticket_id"]).encode()).hexdigest(), 16) % 2 == 0 else "test") == a.split)]
    stat = collections.defaultdict(collections.Counter)
    total_q = 0
    for r in rows:
        x = cp.triage(C.player_payload(r), use_dedup=False)
        if x["category"] == "report.question":
            total_q += 1
        if x["_meta"]["intent"] != "question_kb":
            continue
        key = re.search(r"«([^»]+)»", " ".join(x["reasons"]))
        key = key.group(1) if key else "?"
        admin = " ".join((m.get("text") or "") for m in r["messages"] if m.get("role") == "admin")
        rx = paths.get(key)
        stat[key]["n"] += 1
        stat[key]["admin_has_route"] += bool(rx and rx.search(admin))
        stat[key]["auto"] += not x["needs_human"]
    n = sum(s["n"] for s in stat.values())
    ok = sum(s["admin_has_route"] for s in stat.values())
    print(f"репортов {len(rows)}, из них вопросов {total_q}, ответов question_kb {n}, админ назвал тот же маршрут {ok} ({ok / max(1, n):.2f}), "
          f"без человека {sum(s['auto'] for s in stat.values())}")
    for k, s in sorted(stat.items(), key=lambda kv: -kv[1]["n"]):
        print(f"  {k:<16} ответов {s['n']:>3}  маршрут совпал {s['admin_has_route']:>3}  без человека {s['auto']:>3}")


if __name__ == "__main__":
    main()
