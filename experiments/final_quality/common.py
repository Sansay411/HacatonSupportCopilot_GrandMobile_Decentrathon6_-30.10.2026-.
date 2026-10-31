"""Общие функции экспериментов final_quality: данные, группы повторов, утечка train -> valid.

Ничего из production-кода не меняется. Все кэши лежат в var/final_quality (игнорируется git), потому что содержат
тексты игроков из выдачи кейса. В reports/final_quality пишутся только агрегаты без текстов.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import pickle
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from copilot import lang as lang_mod  # noqa: E402
from copilot.features import model_text  # noqa: E402
from copilot.rules import load as load_rules  # noqa: E402
from copilot.signals import extract  # noqa: E402
from copilot.taxonomy import label_rules, priority_rules  # noqa: E402
from copilot.textnorm import for_matching  # noqa: E402
from copilot.ticket import from_dict  # noqa: E402

SEED = 20261031
CACHE = ROOT / "var" / "final_quality"
OUT = ROOT / "reports" / "final_quality"
PRIVATE = ROOT / "reports" / "private" / "final_quality"
for _d in (CACHE, OUT, PRIVATE):
    _d.mkdir(parents=True, exist_ok=True)

_NONWORD = re.compile(r"[\W_]+", re.UNICODE)


def norm_text(text: str) -> str:
    """Форма для поиска повторов: без регистра, пунктуации и растяжек."""
    return _NONWORD.sub(" ", for_matching(text or "")).strip()


def text_hash(text: str) -> str:
    return hashlib.blake2b(norm_text(text).encode("utf-8"), digest_size=8).hexdigest()


def iter_jsonl(path: Path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def load_rb():
    return load_rules(str(ROOT / "data/rules.json"))


def prep(row: dict, rb, keep_objects: bool = False) -> dict:
    """Признаки тикета ровно так, как их строит production (copilot.features, copilot.signals)."""
    t = from_dict(row)
    sig = extract(t.player_text, rb, t.rule_refs_raw, t.images, t.reported_nick)
    out = {
        "ticket_id": row["ticket_id"], "kind": t.kind, "server_lang": row.get("server_lang"),
        "lang": lang_mod.detect(t.player_text, t.server_lang),
        "mtext": model_text(t, sig), "norm": norm_text(t.player_text), "hash": text_hash(t.player_text),
        "words": sig.words, "verdict": row.get("verdict"),
        "reporter": t.reporter_hash, "reported": t.reported_hash or t.reported_nick,
        "y_weak": label_rules(t.kind, sig, t.player_text, verdict=row.get("verdict"),
                              violation=row.get("violation"), rule_base=rb),
        "y_rules": label_rules(t.kind, sig, t.player_text),
    }
    if keep_objects:
        out["t"], out["sig"] = t, sig
    return out


def load_train(rb, limit: int = 0) -> list[dict]:
    cache = CACHE / "train_prep.pkl"
    if cache.exists() and not limit:
        return pickle.loads(cache.read_bytes())
    t0 = time.time()
    rows = []
    for i, d in enumerate(iter_jsonl(ROOT / "data/tickets_train.jsonl.gz")):
        if limit and i >= limit:
            break
        rows.append(prep(d, rb))
    print(f"train prepared: {len(rows)} rows in {time.time() - t0:.0f}s", flush=True)
    if not limit:
        cache.write_bytes(pickle.dumps(rows))
    return rows


def load_valid(rb) -> list[dict]:
    """valid в исходном порядке файла: индексы совпадают с make_gold.py и data/labels/valid_gold.json."""
    gold = json.loads((ROOT / "data/labels/valid_gold.json").read_text(encoding="utf-8"))
    rows = []
    for d in iter_jsonl(ROOT / "data/tickets_valid.jsonl"):
        p = prep(d, rb, keep_objects=True)
        p["gold_cat"] = gold[d["ticket_id"]]["category"]
        p["gold_pri"] = gold[d["ticket_id"]]["priority"]
        rows.append(p)
    return rows


# ---------- группы повторов ----------
class _DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb_ = self.find(a), self.find(b)
        if ra != rb_:
            self.p[rb_] = ra


def group_ids(rows: list[dict]) -> np.ndarray:
    """Повторные обращения в одну группу: одинаковый нормализованный текст или одна пара «заявитель + нарушитель».

    Так один и тот же случай не попадёт одновременно в обучающую и проверочную часть."""
    dsu = _DSU(len(rows))
    first_text: dict[str, int] = {}
    first_pair: dict[tuple, int] = {}
    for i, r in enumerate(rows):
        h = (r["kind"], r["hash"])
        if h in first_text:
            dsu.union(first_text[h], i)
        else:
            first_text[h] = i
        if r["reporter"] and r["reported"]:
            pair = (r["reporter"], r["reported"])
            if pair in first_pair:
                dsu.union(first_pair[pair], i)
            else:
                first_pair[pair] = i
    return np.array([dsu.find(i) for i in range(len(rows))])


def group_holdout(rows: list[dict], frac: float = 0.15, seed: int = SEED):
    """Разбиение train на обучение и отложенную часть по группам повторов."""
    g = group_ids(rows)
    uniq = np.unique(g)
    rng = np.random.default_rng(seed)
    rng.shuffle(uniq)
    # крупные группы (например «+», 2869 повторов) целиком уходят в одну часть, поэтому доля считается по строкам
    sizes = {u: 0 for u in uniq}
    for x in g:
        sizes[x] += 1
    hold, count, target = set(), 0, frac * len(rows)
    for u in uniq:
        if count >= target:
            break
        hold.add(u)
        count += sizes[u]
    mask = np.array([x in hold for x in g])
    return np.where(~mask)[0], np.where(mask)[0], g


# ---------- утечка train -> valid ----------
def leak_flags(valid: list[dict], train: list[dict], near_thr: float = 0.9) -> list[str]:
    """exact: тот же нормализованный текст есть в train; near: косинус TF-IDF >= порога; clean: остальное.

    Короткие тексты (до 3 слов) сравниваются только точно: у них косинус почти всегда 1.0 из-за общих слов."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    train_hash = {(r["kind"], r["hash"]) for r in train}
    vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=2, sublinear_tf=True, dtype=np.float32)
    Xt = vec.fit_transform([r["norm"] for r in train])
    Xv = vec.transform([r["norm"] for r in valid])
    kinds_t = np.array([r["kind"] for r in train])
    flags = []
    for i, r in enumerate(valid):
        if (r["kind"], r["hash"]) in train_hash:
            flags.append("exact")
            continue
        if r["words"] <= 3:
            flags.append("clean")
            continue
        flags.append("pending")
    # векторизованный проход для оставшихся: блоками, чтобы не раздувать память
    idx = [i for i, f in enumerate(flags) if f == "pending"]
    train_by_kind = {k: np.where(kinds_t == k)[0] for k in ("complaint", "report")}
    for start in range(0, len(idx), 100):
        chunk = idx[start:start + 100]
        for kind in ("complaint", "report"):
            sub = [i for i in chunk if valid[i]["kind"] == kind]
            if not sub:
                continue
            sims = (Xv[sub] @ Xt[train_by_kind[kind]].T).max(axis=1).toarray().ravel()
            for i, s in zip(sub, sims):
                flags[i] = "near" if s >= near_thr else "clean"
    return flags


def metrics_cat(y_true, y_pred, labels=None):
    from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support

    labels = labels or sorted(set(y_true) | set(y_pred))
    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)
    return {
        "n": len(y_true),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "macro_f1": round(float(f1_score(y_true, y_pred, average="macro", labels=[l for l, n in zip(labels, s) if n > 0],
                                         zero_division=0)), 4),
        "per_class": {l: {"p": round(float(pp), 3), "r": round(float(rr), 3), "f1": round(float(ff), 3), "n": int(nn)}
                      for l, pp, rr, ff, nn in zip(labels, p, r, f, s)},
    }


def paired_bootstrap(y, pred_a, pred_b, metric, n: int = 1000, seed: int = SEED):
    """Разность метрики B - A на выборке и 95 % интервал по парному бутстрепу."""
    y, pred_a, pred_b = np.asarray(y), np.asarray(pred_a), np.asarray(pred_b)
    rng = np.random.default_rng(seed)
    base = metric(y, pred_b) - metric(y, pred_a)
    diffs = []
    for _ in range(n):
        ix = rng.integers(0, len(y), len(y))
        diffs.append(metric(y[ix], pred_b[ix]) - metric(y[ix], pred_a[ix]))
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"delta": round(float(base), 4), "ci95": [round(float(lo), 4), round(float(hi), 4)]}
