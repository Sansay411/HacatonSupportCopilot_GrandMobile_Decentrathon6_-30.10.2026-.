"""Мультиязычная проверка ответов: ru, kk, uz отдельно. Автоопределение языка здесь только флаг, не доказательство
естественности перевода: естественность проверяет носитель по файлу reports/private/final_quality/native_review_*.jsonl.

Что считается автоматически (все признаки грубые, ложные срабатывания возможны):
  * покрытие шаблонов i18n по языкам (нет ли ключей без перевода);
  * чистота алфавита: kk должен содержать казахские буквы, uz это латиница, ru не содержит латинских слов;
  * утечка русских служебных слов в kk и uz;
  * согласие lang.detect(черновик) с заявленным языком черновика;
  * язык обращения против языка ответа.
Запуск: python experiments/final_quality/multilingual_qa.py [--compare reports/private/final_quality/compare_real.json]
"""
from __future__ import annotations

import argparse
import json
import pickle
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
from common import ROOT  # noqa: E402

from copilot import i18n, lang as lang_mod  # noqa: E402

KK_LETTERS = set("әғқңөұүһі")
UZ_APOS = {"'", "‘", "’", "ʻ", "ʼ", "`"}
RU_FUNC = re.compile(r"(?<![\w])(и|не|что|на|для|или|это|вы|ваш\w*|жалоб\w*|видео\w*|спасибо|пожалуйста)(?![\w])", re.I)
URL = re.compile(r"https?://\S+|discord\.\S+", re.I)


PLATFORMS = re.compile(r"youtube|imgur|rutube|discord|google|yandex|launcher|gb|id", re.I)


def strip_service(text: str, nick: str | None) -> str:
    t = PLATFORMS.sub(" ", URL.sub(" ", text))
    if nick:
        t = t.replace(nick, " ")
    return re.sub(r"\[\d+\]", " ", t)


def purity_flags(text: str, lang: str, nick: str | None) -> list[str]:
    t = strip_service(text, nick)
    letters = [ch for ch in t if ch.isalpha()]
    if len(letters) < 25:
        return []
    cyr = sum(1 for ch in letters if "Ѐ" <= ch <= "ӿ")
    lat = len(letters) - cyr
    flags = []
    if lang == "kk":
        if not any(ch.lower() in KK_LETTERS for ch in t):
            flags.append("kk_no_kazakh_letters")
        if lat / len(letters) > 0.05:
            flags.append("kk_latin_mix")
        if len(RU_FUNC.findall(t)) >= 2:
            flags.append("kk_russian_function_words")
    elif lang == "uz":
        if cyr / len(letters) > 0.03:
            flags.append("uz_cyrillic_mix")
        # o‘ и g‘ пишутся одним знаком (U+2018); тутуқ белгиси (ma’no, U+2019) другой знак и ошибкой не считается
        used = {m.group(1) for m in re.finditer(r"[oOgG]([" + "".join(UZ_APOS) + "])", t)}
        if len(used) > 1:
            flags.append("uz_mixed_apostrophes_in_o_g")
    elif lang == "ru":
        if lat / len(letters) > 0.05:
            flags.append("ru_latin_mix")
    got = lang_mod.detect(t)
    if got != lang and not (lang == "ru" and got == "uk"):
        flags.append(f"detect_{got}")
    return flags


def template_coverage():
    base = set(i18n.T["ru"])
    out = {}
    for lg, table in i18n.T.items():
        out[lg] = {"keys": len(table), "missing_vs_ru": sorted(base - set(table)), "extra_vs_ru": sorted(set(table) - base)}
    return out


def analyse_texts(items, label):
    """items: [{id, lang, text, nick, intent}] -> агрегаты и список флагов."""
    by_lang = defaultdict(lambda: {"n": 0, "flagged": 0, "flags": Counter()})
    flagged = []
    for it in items:
        fl = purity_flags(it["text"], it["lang"], it.get("nick"))
        s = by_lang[it["lang"]]
        s["n"] += 1
        if fl:
            s["flagged"] += 1
            s["flags"].update(fl)
            flagged.append({**it, "flags": fl})
    return {k: {"n": v["n"], "flagged": v["flagged"], "flagged_share": round(v["flagged"] / max(1, v["n"]), 3),
                "flags": dict(v["flags"])} for k, v in sorted(by_lang.items())}, flagged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", default="")
    args = ap.parse_args()

    cache = pickle.loads((C.CACHE / "valid_baseline_triage.pkl").read_bytes())
    rows = {d["ticket_id"]: d for d in C.iter_jsonl(ROOT / "data/tickets_valid.jsonl")}
    triage = cache["triage"]
    items = []
    for tid, r in triage.items():
        items.append({"id": tid, "lang": r["draft_reply"]["lang"], "text": r["draft_reply"]["text"],
                      "nick": r["extracted"]["nickname"], "intent": r["_meta"]["intent"], "text_lang": r["lang"],
                      "server_lang": rows[tid].get("server_lang"), "category": r["category"]})
    agg_a, flagged_a = analyse_texts(items, "A")
    cross = Counter((i["text_lang"], i["lang"]) for i in items)
    by_lang_intent = defaultdict(Counter)
    for i in items:
        by_lang_intent[i["lang"]][i["intent"]] += 1
    out = {
        "note": "автоопределение языка и чистота алфавита это флаги; естественность перевода не доказана и требует носителя",
        "template_coverage": template_coverage(),
        "baseline_templates_valid": {"purity_by_reply_lang": agg_a,
                                      "player_lang_to_reply_lang": {f"{a}->{b}": n for (a, b), n in sorted(cross.items())},
                                      "intents_by_reply_lang": {k: dict(v) for k, v in by_lang_intent.items()}},
    }
    if args.compare:
        comp = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        a_items = [{"id": c["id"], "lang": c["lang"], "text": c["A"], "nick": None, "intent": c["intent"]} for c in comp]
        b_items = [{"id": c["id"], "lang": c["lang"], "text": c["B"], "nick": None, "intent": c["intent"]} for c in comp
                   if c["B_status"] == "ok"]
        raw_items = [{"id": c["id"], "lang": c["lang"], "text": c["B_raw"], "nick": None, "intent": c["intent"]} for c in comp
                     if c.get("B_raw")]
        out["compare_sample"] = {"A": analyse_texts(a_items, "A")[0], "B_final_used": analyse_texts(b_items, "B")[0],
                                 "B_raw_all_generations": analyse_texts(raw_items, "Braw")[0]}

    (C.OUT / "multilingual.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])

    # файл для носителя: все kk, uz по сценариям, и все помеченные флагами; тексты игроков, только локально
    rnd = random.Random(C.SEED + 3)
    pick = [i for i in items if i["lang"] == "kk"]
    uz = [i for i in items if i["lang"] == "uz"]
    by_int = defaultdict(list)
    for i in uz:
        by_int[i["intent"]].append(i)
    for k, v in by_int.items():
        pick += rnd.sample(v, min(6, len(v)))
    seen = {i["id"] for i in pick}
    pick += [f for f in flagged_a if f["lang"] in ("kk", "uz") and f["id"] not in seen]
    path = C.PRIVATE / "native_review_kk_uz.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for i in pick:
            f.write(json.dumps({"ticket_id": i["id"], "reply_lang": i["lang"], "player_text": " ".join(
                m.get("text") or "" for m in rows[i["id"]]["messages"] if m["role"] != "admin"), "scenario": i["intent"],
                "draft_A_templates": i["text"], "auto_flags": purity_flags(i["text"], i["lang"], i.get("nick")),
                "review": {"natural": None, "grammar_ok": None, "terms_ok": None, "tone_ok": None, "comment": ""}},
                ensure_ascii=False) + "\n")
    print(f"для носителя: {path} ({len(pick)} шт., не коммитится)")


if __name__ == "__main__":
    main()
