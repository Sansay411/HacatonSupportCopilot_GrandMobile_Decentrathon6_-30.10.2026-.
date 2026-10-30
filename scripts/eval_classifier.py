"""Сравнение правил, модели и гибрида на dev-разметке valid."""
import json, sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from sklearn.metrics import accuracy_score, f1_score, classification_report
from copilot.classifier import CategoryModel
from copilot.rules import load
from copilot.signals import extract
from copilot.taxonomy import priority_rules
from copilot.ticket import from_dict

rb = load(ROOT / "data/rules.json")
gold = json.load(open(ROOT / "data/labels/valid_gold.json"))
rows = [json.loads(l) for l in open(ROOT / "data/tickets_valid.jsonl")]
cm = CategoryModel(ROOT / "models/category.pkl")
Y, R, M, H, PY, PH = [], [], [], [], [], []
for d in rows:
    t = from_dict(d); s = extract(t.player_text, rb, t.rule_refs_raw, t.images, t.reported_nick)
    res = cm.predict(t, s)
    g = gold[d["ticket_id"]]
    Y.append(g["category"]); R.append(res.rules_category); H.append(res.category)
    M.append(cm._proba(t.kind, __import__("copilot.features", fromlist=["x"]).model_text(t, s))[0][0])
    PY.append(g["priority"]); PH.append(priority_rules(res.category, s))
for name, P in [("rules", R), ("model", M), ("hybrid", H)]:
    print(f"{name:7s} acc={accuracy_score(Y, P):.3f}  macroF1={f1_score(Y, P, average='macro'):.3f}")
print("priority macro-F1 (hybrid cat):", round(f1_score(PY, PH, average="macro"), 3), "acc", round(accuracy_score(PY, PH), 3))
if "-v" in sys.argv:
    print(classification_report(Y, H, zero_division=0))
    errs = Counter((y, h) for y, h in zip(Y, H) if y != h)
    print(errs.most_common(15))
