"""Обучение классификатора категорий на слабой разметке train.

Слабая разметка = правила copilot.taxonomy.label_rules + исход из ответа
админа (verdict, violation). Исход в рантайме недоступен, поэтому модель
учится восстанавливать его по тексту игрока: так она обобщает сленг,
опечатки и узбекские формулировки, которых нет в словарях.

Выход: models/category.pkl (две модели: complaint и report).
"""
from __future__ import annotations

import argparse
import gzip
import json
import pickle
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from copilot.features import model_text  # noqa: E402
from copilot.rules import load  # noqa: E402
from copilot.signals import extract  # noqa: E402
from copilot.taxonomy import label_rules  # noqa: E402
from copilot.ticket import from_dict  # noqa: E402


def iter_train(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def build(rows, rb):
    data = {"complaint": ([], []), "report": ([], [])}
    for d in rows:
        t = from_dict(d)
        sig = extract(t.player_text, rb, t.rule_refs_raw, t.images, t.reported_nick)
        y = label_rules(t.kind, sig, t.player_text, verdict=d.get("verdict"), violation=d.get("violation"), rule_base=rb)
        data[t.kind][0].append(model_text(t, sig))
        data[t.kind][1].append(y)
    return data


def fit(texts, labels, seed=0):
    word = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=2, max_features=60000, sublinear_tf=True,
                           token_pattern=r"(?u)[\w.']+")
    char = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=3, max_features=120000, sublinear_tf=True)
    Xw = word.fit_transform(texts)
    Xc = char.fit_transform(texts)
    X = hstack([Xw, Xc]).tocsr()
    clf = LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced", random_state=seed)
    clf.fit(X, labels)
    return {"word": word, "char": char, "clf": clf}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default=str(ROOT / "data/tickets_train.jsonl.gz"))
    ap.add_argument("--rules", default=str(ROOT / "data/rules.json"))
    ap.add_argument("--out", default=str(ROOT / "models/category.pkl"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rb = load(args.rules)
    t0 = time.time()
    rows = list(iter_train(Path(args.train)))
    if args.limit:
        rows = rows[: args.limit]
    data = build(rows, rb)
    print(f"weak labels built in {time.time() - t0:.0f}s")
    models = {}
    for kind, (X, y) in data.items():
        print(kind, len(y), Counter(y).most_common())
        t1 = time.time()
        models[kind] = fit(X, y)
        print(f"  fit {time.time() - t1:.0f}s")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "wb") as f:
        pickle.dump(models, f)
    print("saved", args.out)


if __name__ == "__main__":
    main()
