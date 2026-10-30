"""Модель исхода жалобы по тексту: approved / need_evidence / reject.

Нужна, чтобы выбрать вид черновика: предложить наказание (подтверждает
админ), запросить доказательства или отклонить по правилам подачи жалоб.
Цель берётся из поля verdict, извлечённого из ответа админа.
"""
import gzip, json, pickle, sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scipy.sparse import hstack, csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, classification_report
from copilot.features import model_text
from copilot.rules import load
from copilot.signals import extract
from copilot.ticket import from_dict

MAP = {"approved": "approve", "already_punished": "approve", "need_evidence": "need_evidence",
       "rejected": "reject", "invalid_format": "reject", "closed": None, "duplicate": None, "other": None,
       "appeal_rejected": None, "appeal_approved": None}

def meta(t, s):
    return [min(t.images, 6) / 6, float(s.has_url), float(s.words <= 2), float(s.words > 15), float(bool(s.rule_refs))]

def collect(rows, rb):
    X, M, y = [], [], []
    for d in rows:
        if d.get("kind") != "complaint":
            continue
        lab = MAP.get(d.get("verdict"))
        if not lab:
            continue
        t = from_dict(d); s = extract(t.player_text, rb, t.rule_refs_raw, t.images, t.reported_nick)
        if "appeal" in s.topics:
            continue
        X.append(model_text(t, s)); M.append(meta(t, s)); y.append(lab)
    return X, M, y

rb = load(ROOT / "data/rules.json")
train = [json.loads(l) for l in gzip.open(ROOT / "data/tickets_train.jsonl.gz", "rt", encoding="utf-8")]
valid = [json.loads(l) for l in open(ROOT / "data/tickets_valid.jsonl", encoding="utf-8")]
X, M, y = collect(train, rb)
print(len(y), Counter(y))
vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=3, max_features=100000, sublinear_tf=True)
Xt = hstack([vec.fit_transform(X), csr_matrix(M)]).tocsr()
clf = LogisticRegression(max_iter=2000, C=2.0, class_weight="balanced").fit(Xt, y)
Xv, Mv, yv = collect(valid, rb)
P = clf.predict(hstack([vec.transform(Xv), csr_matrix(Mv)]).tocsr())
print("valid n=", len(yv), "acc", round(accuracy_score(yv, P), 3), "macroF1", round(f1_score(yv, P, average="macro"), 3))
print(classification_report(yv, P, zero_division=0))
maj = Counter(y).most_common(1)[0][0]
print("majority baseline acc", round(sum(1 for v in yv if v == maj) / len(yv), 3))
pickle.dump({"vec": vec, "clf": clf}, open(ROOT / "models/verdict.pkl", "wb"))
