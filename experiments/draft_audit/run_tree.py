"""Прогон выборки тикетов через pipeline из указанного дерева исходников (HEAD в отдельной папке или рабочая копия).

Нужен для сравнения «до» и «после» на данных, которые не использовались при поиске проблем (train). Данные и модели берутся
из рабочей копии через COPILOT_DATA и COPILOT_MODELS, код из --tree. Тексты игроков пишутся только в reports/private/.

    python run_tree.py --tree <папка с copilot/> --in data/tickets_train.jsonl.gz --n 6000 --seed 7 --out reports/private/draft_audit/train_before.jsonl
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

ap = argparse.ArgumentParser()
ap.add_argument("--tree", required=True)
ap.add_argument("--in", dest="inp", required=True)
ap.add_argument("--n", type=int, default=0)
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--out", required=True)
a = ap.parse_args()

os.environ["COPILOT_DATA"] = str(ROOT / "data")
os.environ["COPILOT_MODELS"] = str(ROOT / "models")
sys.path.insert(0, str(Path(a.tree).resolve()))

from copilot.pipeline import Copilot  # noqa: E402

import copilot  # noqa: E402
assert Path(copilot.__file__).resolve().is_relative_to(Path(a.tree).resolve()), copilot.__file__

p = Path(a.inp)
op = gzip.open if p.suffix == ".gz" else open
with op(p, "rt", encoding="utf-8") as f:
    rows = [json.loads(x) for x in f if x.strip()]
if a.n and a.n < len(rows):
    rows = random.Random(a.seed).sample(rows, a.n)
rows.sort(key=lambda r: (r.get("created_at") or "", r.get("ticket_id") or ""))

cp = Copilot()
out = []
t0 = time.perf_counter()
for r in rows:
    payload = dict(r)
    payload["messages"] = [m for m in (r.get("messages") or []) if isinstance(m, dict) and m.get("role") != "admin"]
    x = cp.triage(payload)
    out.append({
        "ticket_id": r.get("ticket_id"), "kind": r.get("kind"), "verdict": r.get("verdict"),
        "player_text": "\n".join(m.get("text") or "" for m in payload["messages"] if m.get("role", "player") == "player"),
        "category": x["category"], "priority": x["priority"], "needs_human": x["needs_human"],
        "intent": x["_meta"]["intent"], "reply_lang": x["draft_reply"]["lang"], "text": x["draft_reply"]["text"],
        "cited": x["draft_reply"]["cited"], "latency_ms": x["_meta"]["latency_ms"],
    })
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
with open(a.out, "w", encoding="utf-8") as f:
    for o in out:
        f.write(json.dumps(o, ensure_ascii=False) + "\n")
print(f"{len(out)} тикетов за {time.perf_counter() - t0:.1f} с -> {a.out}")
