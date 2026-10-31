"""Показать 60 слепых пар: текст игрока и шаблонный ответ A (ключ раскрывается только для чтения шаблона).

Для аудита ошибок системы (не для оценки Qwen): смотрим, что именно отвечают шаблоны Sentra на 60 реальных обращениях.
    python experiments/draft_audit/show_pairs.py [--from 0 --to 20] [--side A|B]
"""
from __future__ import annotations

import argparse
import csv
import json

import common as C

ap = argparse.ArgumentParser()
ap.add_argument("--from", dest="lo", type=int, default=0)
ap.add_argument("--to", dest="hi", type=int, default=60)
ap.add_argument("--side", default="A")
ap.add_argument("--maxp", type=int, default=260)
a = ap.parse_args()

base = C.ROOT / "reports" / "private" / "final_quality"
key = json.loads((base / "blind_pairs_real.KEY.json").read_text(encoding="utf-8"))
with open(base / "human_review_pairs.csv", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))
for i, r in enumerate(rows[a.lo:a.hi], start=a.lo):
    k = key[r["pair_id"]]
    side_xy = "X" if k["X"] == a.side else "Y"
    txt = r["reply_" + side_xy]
    pt = " ".join(r["player_text"].split())
    print(f"[{i}] {r['pair_id']} {r['language']} | ИГРОК: {pt[:a.maxp]}")
    print(f"     {a.side}: {txt}")
