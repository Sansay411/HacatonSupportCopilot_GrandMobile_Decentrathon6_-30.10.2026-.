"""Кандидаты в новые шаблоны ответов по кластерам похожих обращений.

Идея: внутри каждой категории тексты игроков кластеризуются (TF-IDF по символьным
n-граммам, SVD, MiniBatchKMeans), для кластера считаются самые частые ответы админов
после замены ников и чисел на плейсхолдеры. Если ответ повторяется и содержательный,
а текущие сценарии drafts.py кластер покрывают плохо, кластер помечается как
кандидат в шаблон.

Модуль ничего не придумывает: формулировка кандидата это дословный (после замены
ников и чисел) повторяющийся ответ админов. Ссылки на пункты в нём проверяются по
rules.json, шаблон с несуществующей ссылкой в рекомендации не попадает.
Чистые функции без обращения к файлам данных: их можно тестировать на синтетике.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from .guard import check as guard_check
from .rules import RuleBase
from .textnorm import for_matching

# сценарии drafts.py, которые не говорят игроку ничего конкретного
GENERIC_INTENTS = frozenset({"help_generic", "question_unknown", "clarify", "report_need_id"})

NICK = re.compile(r"\b[A-Za-zА-Яа-яЁё]{2,}_[A-Za-zА-Яа-яЁё]{2,}\d*\b")
_ID = re.compile(r"#+\s*<digits>|#+\s*\d+|<digits>")
_URL = re.compile(r"<url>|https?://\S+")
# ссылка на пункт правил: 2.1, 1.2.3 (с необязательным буквенным разделом)
REF = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{1,2}){1,2})(?!\d)\s*[.,]?\s*([A-Za-zА-Яа-яЁё]{1,10})?")
_NUM = re.compile(r"(?<![\d.{])\d+(?![\d.]*\d)")
_WS = re.compile(r"\s+")
_GREET = re.compile(
    r"^(?:здравствуйте|приветств?у(?:ю|ем)(?: вас)?|добрый (?:день|вечер)|уважаемый(?: игрок)?|уважаемая|"
    r"salom|assalomu alaykum|hello|hi|сәлем|сәлеметсіз бе)[\s,!.{}a-z_]*", re.I)
_SIGN = re.compile(r"(?:с уважением|желаем удачи|хорошей игры|приятной игры|удачной игры|администрация|"
                   r"hurmat bilan|best regards)[^.!?]*[.!?]?\s*$", re.I)


# ---------------------------------------------------------------- нормализация
def normalize_reply(text: str) -> str:
    """Ответ админа в виде шаблона: ники -> {nick}, номера жалоб -> {id}, числа -> {n}.

    Номера пунктов правил (2.1, 1.2.3) не трогаем: по ним идёт проверка в rules.json.
    """
    t = text or ""
    t = _URL.sub("{url}", t)
    t = _ID.sub("{id}", t)
    t = NICK.sub("{nick}", t)
    # числа вне ссылок на пункты: защищаем ссылки временным маркером
    refs: list[str] = []

    def keep(m: re.Match) -> str:
        refs.append(m.group(0))
        return "\x00R\x00"

    t = REF.sub(keep, t)
    t = _NUM.sub("{n}", t)
    it = iter(refs)
    t = re.sub(r"\x00R\x00", lambda m: next(it), t)
    return _WS.sub(" ", t).strip()


def reply_key(norm: str) -> str:
    """Ключ для подсчёта одинаковых ответов: регистр, приветствие, подпись и пунктуация не важны."""
    core = reply_core(norm) or norm
    return _WS.sub(" ", re.sub(r"[^\w{}]+", " ", core.lower().replace("ё", "е"))).strip()


def reply_core(norm: str) -> str:
    """Ответ без приветствия и подписи: что осталось по существу."""
    t = norm.strip()
    for _ in range(2):
        t = _GREET.sub("", t, count=1).strip(" ,.!")
    t = _SIGN.sub("", t).strip(" ,.!")
    t = re.sub(r"\{(?:nick|id|n|url)\}", " ", t)
    return _WS.sub(" ", t).strip(" ,.!|")


def player_text_for_clustering(text: str) -> str:
    t = _URL.sub(" ", text or "")
    t = NICK.sub(" ", t)
    t = _ID.sub(" ", t)
    return _WS.sub(" ", for_matching(t)).strip()


# ---------------------------------------------------------------- ссылки на пункты
def verify_refs(norm: str, rb: RuleBase) -> tuple[list[str], list[str]]:
    """(подтверждённые пункты, ссылки, которых нет в rules.json).

    Ссылкой считаем «число.число» с необязательным разделом («2.1 ОП», «1.2.3 ЖБ»).
    Подтверждает только rb.parse_refs, то есть пункт реально есть в rules.json.
    """
    ok: list[str] = []
    bad: list[str] = []
    for m in REF.finditer(norm):
        snippet = m.group(0).strip(" .,")
        parsed = rb.parse_refs(snippet)
        if parsed:
            for c in parsed:
                if rb.exists(c) and c not in ok:
                    ok.append(c)
        else:
            bad.append(snippet)
    return ok, bad


# ---------------------------------------------------------------- кластеризация
def choose_k(n: int, max_k: int = 24, per_cluster: int = 400) -> int:
    return int(min(max_k, max(2, round(n / per_cluster))))


def cluster_texts(texts: list[str], k: int, seed: int = 7, svd_dim: int = 80) -> tuple[np.ndarray, np.ndarray]:
    """(метки, расстояние до центроида). Без внешних моделей: только scikit-learn."""
    n = len(texts)
    if n < 2 or k < 2:
        return np.zeros(n, dtype=int), np.zeros(n)
    k = min(k, n)
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=2 if n > 50 else 1,
                          max_features=60000, sublinear_tf=True, dtype=np.float32)
    X = vec.fit_transform(texts)
    if X.shape[1] == 0:
        return np.zeros(n, dtype=int), np.zeros(n)
    dim = max(2, min(svd_dim, X.shape[1] - 1, n - 1))
    Z = normalize(TruncatedSVD(n_components=dim, random_state=seed).fit_transform(X))
    km = MiniBatchKMeans(n_clusters=k, random_state=seed, n_init=3, batch_size=2048, max_iter=60)
    labels = km.fit_predict(Z)
    dist = np.linalg.norm(Z - km.cluster_centers_[labels], axis=1)
    return labels, dist


def cluster_terms(cluster_texts_: list[str], all_texts: list[str], top: int = 6, min_df: int = 8) -> list[str]:
    """Слова, которые в кластере встречаются заметно чаще, чем в категории (агрегат, не текст игрока)."""
    tok = re.compile(r"[a-zа-яёқғңөұүһәі]{4,}", re.I)
    df_c: Counter = Counter()
    for t in cluster_texts_:
        df_c.update(set(tok.findall(t)))
    df_a: Counter = Counter()
    for t in all_texts:
        df_a.update(set(tok.findall(t)))
    n_c, n_a = max(1, len(cluster_texts_)), max(1, len(all_texts))
    scored = []
    floor = max(min_df, int(0.04 * n_c))
    for w, c in df_c.items():
        if c < floor:
            continue
        lift = (c / n_c) / ((df_a[w] + 1) / n_a)
        scored.append((lift * np.log1p(c), w))
    return [w for _, w in sorted(scored, reverse=True)[:top]]


# ---------------------------------------------------------------- сводка по кластеру
@dataclass
class Params:
    min_cluster: int = 30          # меньше тикетов: кластер не рассматриваем
    min_reply_count: int = 20      # шаблон должен повторяться не реже (заодно k-анонимность: это не индивидуальный ответ)
    min_reply_share: float = 0.05  # доля тикетов кластера с этим ответом
    min_core_words: int = 3        # «Приветствую, одобрено» шаблоном не считается
    merge_sim: float = 0.6         # формулировки с таким косинусом (символьные n-граммы) считаются одним ответом
    min_lift: float = 5.0          # доля ответа в кластере / доля среди всех тикетов того же вида (жалоба, репорт)
    stock_share: float = 0.03      # ответ, на который приходится столько тикетов вида и не меньше stock_min_count,
    stock_min_count: int = 300     # считается стандартной отпиской и кандидатом не бывает
    intent_share_ok: float = 0.6   # доля основного сценария, при которой кластер считается покрытым
    draft_sim_ok: float = 0.15     # косинус «наш черновик ~ ответ админов»: ниже значит, что черновик говорит о другом
    max_k: int = 24
    per_cluster: int = 400
    top_replies: int = 5
    examples: int = 5
    seed: int = 7


def reply_stats(records: list[dict]) -> tuple[Counter, Counter]:
    """Сколько раз каждый нормализованный ответ встречается среди тикетов вида (жалоба, репорт) и сколько тикетов вида."""
    cnt: Counter = Counter()
    kinds: Counter = Counter()
    for r in records:
        if (r.get("reply") or "").strip():
            k = r.get("kind") or ""
            cnt[(k, reply_key(normalize_reply(r["reply"])))] += 1
            kinds[k] += 1
    return cnt, kinds


def stock_replies(records: list[dict], P: Params | None = None, top: int = 8) -> list[dict]:
    """Стандартные отписки админов: формулировка и доля тикетов вида. Для сводки, это не кандидаты."""
    P = P or Params()
    cnt, kinds = reply_stats(records)
    display: dict = {}
    for r in records:
        if (r.get("reply") or "").strip():
            display.setdefault((r.get("kind") or "", reply_key(normalize_reply(r["reply"]))), normalize_reply(r["reply"]))
    out = [{"kind": k, "template": display[(k, key)], "count": c, "share": round(c / kinds[k], 4)}
           for (k, key), c in cnt.most_common()
           if c >= P.stock_min_count and c / kinds[k] >= P.stock_share]
    return out[:top]


def build_suggestions(records: list[dict], rb: RuleBase, params: Params | None = None,
                      categories: list[str] | None = None) -> list[dict]:
    """records: category, kind, player_text, reply, intent, draft (текст нашего черновика), ticket_id, lang.

    Возвращает список кластеров (полная версия, с примерами из данных).
    Публичная версия получается через public_view().
    """
    P = params or Params()
    glob, kinds = reply_stats(records)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if (r.get("reply") or "").strip():
            by_cat[r["category"]].append(r)
    out: list[dict] = []
    for cat in sorted(by_cat):
        if categories and cat not in categories:
            continue
        rows = by_cat[cat]
        if len(rows) < P.min_cluster:
            continue
        texts = [player_text_for_clustering(r["player_text"]) for r in rows]
        k = choose_k(len(rows), P.max_k, P.per_cluster)
        labels, dist = cluster_texts(texts, k, P.seed)
        norms = [normalize_reply(r["reply"]) for r in rows]
        keys = [reply_key(n) for n in norms]
        cores = [reply_core(n) for n in norms]
        drafts_core = [reply_core(normalize_reply(r.get("draft") or "")) for r in rows]
        sim_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)
        sim_vec.fit(cores + drafts_core)
        D = sim_vec.transform(drafts_core)
        for cid in sorted(set(labels.tolist())):
            idx = [i for i in range(len(rows)) if labels[i] == cid]
            if len(idx) < P.min_cluster:
                continue
            out.append(_summarize(cat, cid, idx, rows, texts, norms, keys, dist, rb, P, sim_vec, D, glob, kinds))
    return score_gaps(out, P)


def _group_variants(ranked: list[tuple[str, int]], sim_vec, thr: float) -> list[list[tuple[str, int]]]:
    """Склеивает формулировки одного ответа («нажмите кнопку эвакуатора» / «воспользуйтесь кнопкой эвакуатора»).

    ranked идёт по убыванию частоты, лидером группы становится самая частая формулировка.
    """
    from scipy.sparse import vstack
    if not ranked:
        return []
    V = sim_vec.transform([k for k, _ in ranked])
    leaders: list[int] = []
    groups: list[list[tuple[str, int]]] = []
    for i, item in enumerate(ranked):
        if leaders:
            sims = (V[i] @ vstack([V[j] for j in leaders]).T).toarray().ravel()
            j = int(sims.argmax())
            if sims[j] >= thr:
                groups[j].append(item)
                continue
        leaders.append(i)
        groups.append([item])
    return sorted(groups, key=lambda g: -sum(c for _, c in g))


def _summarize(cat, cid, idx, rows, texts, norms, keys, dist, rb: RuleBase, P: Params, sim_vec, D, glob: Counter,
               kinds: Counter) -> dict:
    size = len(idx)
    cnt = Counter(keys[i] for i in idx)
    forms: dict[str, Counter] = defaultdict(Counter)
    for i in idx:
        forms[keys[i]][norms[i]] += 1
    display = {k: f.most_common(1)[0][0] for k, f in forms.items()}   # в шаблон идёт самая частая полная форма
    intents = Counter(rows[i].get("intent") or "?" for i in idx)
    top_intent, top_intent_n = intents.most_common(1)[0]
    langs = Counter(rows[i].get("lang") or "?" for i in idx)
    kind = Counter(rows[i].get("kind") or "" for i in idx).most_common(1)[0][0]

    ranked = cnt.most_common(80)
    groups = _group_variants(ranked, sim_vec, P.merge_sim)

    def describe(members: list[tuple[str, int]]) -> dict:
        key, lead = members[0]
        tpl = display[key]
        count = sum(c for _, c in members)
        ok, bad = verify_refs(tpl, rb)
        _, flags = guard_check(tpl, ok, rb)
        g = sum(glob[(kind, k)] for k, _ in members)
        gshare = g / kinds[kind]
        return {"template": tpl, "count": count, "share": round(count / size, 4), "exact_share": round(lead / size, 4),
                "variants": len(members), "lift": round((count / size) / gshare, 2),
                "stock": g >= P.stock_min_count and gshare >= P.stock_share,
                "core_words": len(reply_core(tpl).split()), "refs": ok, "unverified_refs": bad, "guard": flags}

    described = [describe(m) for m in groups]
    replies = described[:P.top_replies]
    # шаблон-кандидат: самый частый ответ, который повторяется, содержателен и характерен именно для кластера
    best = next((r for r in described
                 if r["count"] >= P.min_reply_count and r["share"] >= P.min_reply_share
                 and r["core_words"] >= P.min_core_words and r["lift"] >= P.min_lift and not r["stock"]), None)
    repeated = best is not None
    ref_reply = best or replies[0]

    sim = None
    if ref_reply["core_words"]:
        T = sim_vec.transform([reply_core(ref_reply["template"])])
        sim = round(float((D[idx] @ T.T).mean()), 3)
    order = sorted(idx, key=lambda i: dist[i])
    examples = [{"ticket_id": rows[i].get("ticket_id"), "player_text": rows[i]["player_text"][:400],
                 "admin_reply": norms[i][:400], "intent": rows[i].get("intent"),
                 "draft": (rows[i].get("draft") or "")[:400]} for i in order[:P.examples]]
    cl_texts = [texts[i] for i in idx]
    all_texts = [texts[j] for j in range(len(texts))] if len(texts) <= 4000 else [texts[j] for j in range(0, len(texts), max(1, len(texts) // 4000))]
    return {
        "category": cat, "cluster": int(cid), "size": size,
        "terms": cluster_terms(cl_texts, all_texts),
        "langs": dict(langs.most_common(3)),
        "intent": top_intent, "intent_share": round(top_intent_n / size, 3),
        "intents": dict(intents.most_common(3)),
        "distinct_replies": len(cnt), "top_reply_share": replies[0]["share"],
        "draft_sim": sim,
        "top_replies": replies, "best": best, "repeated": repeated, "examples": examples,
    }


def score_gaps(clusters: list[dict], P: Params | None = None) -> list[dict]:
    P = P or Params()
    for c in clusters:
        reasons = []
        generic = c["intent"] in GENERIC_INTENTS
        weak_intent = c["intent_share"] < P.intent_share_ok
        far = c.get("draft_sim") is not None and c["draft_sim"] < P.draft_sim_ok
        best = c["best"] or c["top_replies"][0]
        if generic:
            reasons.append(f"основной сценарий «{c['intent']}» общий и ничего конкретного не говорит")
        if weak_intent:
            reasons.append(f"основной сценарий покрывает только {c['intent_share']:.0%} кластера")
        if far:
            reasons.append(f"черновик мало похож на ответ админов (косинус {c['draft_sim']:.2f})")
        c["gap_reasons"] = reasons
        gap = bool(reasons) and c["repeated"]
        c["gap"] = gap
        if not c["repeated"]:
            c["status"] = "ответы не повторяются"
        elif best["unverified_refs"]:
            c["status"] = "отклонён: ссылка на пункт, которого нет в rules.json"
            c["gap"] = False
        elif best["guard"]:
            c["status"] = "отклонён: формулировка содержит обещание (guard)"
            c["gap"] = False
        elif not reasons:
            c["status"] = "покрыт текущими сценариями"
        else:
            c["status"] = "кандидат в шаблон"
    return clusters


# ---------------------------------------------------------------- публичная сводка
def public_view(clusters: list[dict], params: Params | None = None, meta: dict | None = None,
                stock: list[dict] | None = None) -> dict:
    """Агрегаты и формулировки шаблонов: без текстов игроков, примеров и id тикетов.

    Формулировка попадает в сводку только у кандидатов и покрытых кластеров; повторяемость
    не меньше min_reply_count гарантирует, что это шаблон, а не индивидуальный ответ.
    Кандидаты с одинаковой формулировкой из разных кластеров объединяются в одну запись.
    """
    P = params or Params()
    rest, merged = [], {}
    for c in clusters:
        best = c["best"] or c["top_replies"][0]
        item = {
            "category": c["category"], "cluster": c["cluster"], "size": c["size"], "terms": c["terms"],
            "langs": c["langs"], "intent": c["intent"], "intent_share": c["intent_share"],
            "draft_sim": c["draft_sim"], "distinct_replies": c["distinct_replies"],
            "top_reply_share": best["share"], "exact_share": best["exact_share"], "variants": best["variants"],
            "lift": best["lift"], "status": c["status"], "gap": c["gap"],
            "gap_reasons": c["gap_reasons"], "merged_clusters": 1, "categories": [c["category"]],
        }
        if c["status"] in ("кандидат в шаблон", "покрыт текущими сценариями"):
            item.update(template=best["template"], template_count=best["count"], refs=best["refs"], guard=best["guard"])
        if not c["gap"]:
            rest.append(item)
            continue
        key = reply_key(best["template"])
        if key not in merged:
            merged[key] = item
            continue
        m = merged[key]
        if item["size"] * item["top_reply_share"] > m["size"] * m["top_reply_share"]:
            item["size"] += m["size"]
            item["merged_clusters"] += m["merged_clusters"]
            item["categories"] = sorted(set(item["categories"]) | set(m["categories"]))
            merged[key] = m = item
        else:
            m["size"] += item["size"]
            m["merged_clusters"] += 1
            m["categories"] = sorted(set(m["categories"]) | set(item["categories"]))
    cands = sorted(merged.values(), key=lambda x: -x["size"] * x["top_reply_share"])
    items = cands + sorted(rest, key=lambda x: -x["size"])
    return {
        "meta": dict(meta or {}, params={k: getattr(P, k) for k in P.__dataclass_fields__}),
        "totals": {"clusters": len(clusters), "candidates": len(cands),
                   "candidate_clusters": sum(x["merged_clusters"] for x in cands),
                   "tickets_in_candidates": sum(x["size"] for x in cands),
                   "tickets_in_clusters": sum(c["size"] for c in clusters)},
        "stock_replies": stock or [],
        "clusters": items,
    }


def render_markdown(summary: dict, limit: int = 40) -> str:
    m, t = summary["meta"], summary["totals"]
    p = m.get("params", {})
    lines = [
        "# Кандидаты в новые шаблоны ответов",
        "",
        "Сводка собрана скриптом `scripts/suggest_templates.py` по обучающей выгрузке. Здесь только агрегаты и "
        "формулировки, которые админы повторяют дословно (ники и числа заменены на плейсхолдеры). "
        "Тексты игроков и примеры лежат в `reports/private/` и в репозиторий не попадают.",
        "",
        f"- Тикетов с ответом админа: {m.get('tickets', '?')}, кластеров с размером не меньше {p.get('min_cluster')}: {t['clusters']}.",
        f"- Кандидатов в шаблон: **{t['candidates']}** (из {t['candidate_clusters']} кластеров, покрывают {t['tickets_in_candidates']} тикетов).",
        f"- Категория для каждого тикета взята из `Copilot.triage`; модель обучена на тех же данных, "
        "поэтому на train категории оптимистичны.",
        "",
        "## Как помечается кандидат",
        "",
        f"1. Главный ответ админов в кластере повторяется: не меньше {p.get('min_reply_count')} раз и не меньше "
        f"{p.get('min_reply_share', 0):.0%} кластера (близкие формулировки с косинусом не ниже {p.get('merge_sim')} считаются одним ответом), в нём не меньше {p.get('min_core_words')} слов по существу, "
        f"и он характерен именно для кластера: доля в кластере не меньше чем в {p.get('min_lift')} раза выше, чем среди "
        "всех тикетов того же вида. Стандартные отписки вроде «слежу за вами», которые админы шлют на всё, "
        "кандидатами не считаются (раздел ниже).",
        f"2. Текущий сценарий покрывает кластер плохо: основной `_meta.intent` общий ({', '.join(sorted(GENERIC_INTENTS))}), "
        f"или он даёт меньше {p.get('intent_share_ok', 0):.0%} кластера, или косинус между нашим черновиком и "
        f"ответом админов ниже {p.get('draft_sim_ok')}.",
        "3. Все номера пунктов в формулировке подтверждены `rules.json`; иначе кластер отклоняется.",
        "",
        "Шаблон это предложение для проверки человеком, а не готовый текст для автоответа. "
        "Формулировки с обещанием (снятие наказания, возврат) и со ссылкой на несуществующий пункт отклоняются.",
        "",
        "## Кандидаты",
        "",
    ]
    cands = [c for c in summary["clusters"] if c["gap"]]
    if not cands:
        lines.append("Кандидатов нет при текущих порогах.")
    for i, c in enumerate(cands[:limit], 1):
        lines += [
            f"### {i}. {c['category']}, кластер {c['cluster']}",
            "",
            f"- Размер: {c['size']}, доля этого ответа в кластере: {c['top_reply_share']:.0%} ({c['variants']} близких формулировок, дословно самая частая {c['exact_share']:.0%}), "
            f"в {c['lift']} раз выше, чем среди тикетов того же вида. Различных ответов в кластере: {c['distinct_replies']}."
            + (f" Объединено кластеров с этой формулировкой: {c['merged_clusters']}, категории: {', '.join(c['categories'])}." if c["merged_clusters"] > 1 else ""),
            *([f"- Ключевые слова кластера: {', '.join(c['terms'])}."] if c["terms"] else []),
            f"- Текущий сценарий: `{c['intent']}` ({c['intent_share']:.0%}), близость черновика к ответу админов: {c['draft_sim']}.",
            f"- Почему кандидат: {'; '.join(c['gap_reasons'])}.",
            f"- Пункты правил в формулировке: {', '.join(c['refs']) or 'нет'}.",
            "",
            "> " + c["template"].replace("\n", "\n> ").replace("—", "-").replace("–", "-"),
            "",
        ]
    if len(cands) > limit:
        lines.append(f"Показаны первые {limit} из {len(cands)}, полный список в `reports/template_suggestions_summary.json`.")
    if summary.get("stock_replies"):
        lines += ["", "## Стандартные отписки", "",
                  "Эти ответы админы шлют на всё подряд, к теме кластера они не привязаны, кандидатами не считаются:", ""]
        lines += [f"- {r['kind']}, {r['share']:.1%} тикетов вида: {r['template']}" for r in summary["stock_replies"]]
    rest = [c for c in summary["clusters"] if not c["gap"]]
    if rest:
        st = Counter(c["status"] for c in rest)
        lines += ["", "## Остальные кластеры", ""] + [f"- {k}: {v}" for k, v in st.most_common()]
    return "\n".join(lines).rstrip() + "\n"
