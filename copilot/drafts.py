"""Сборка черновика ответа: выбор сценария, пунктов правил и текста.

Все цитаты выбираются кодом из rules.json (RAG по правилам: явные ссылки
игрока, сверенные с категорией, затем пункты категории из taxonomy.json,
затем BM25-поиск по тексту правил с порогом). Модель, даже если подключена,
получает этот список и не может добавить свой пункт: валидатор отрежет.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import i18n, kb, sanctions
from .rules import RuleBase, SECTIONS
from .signals import TOPICS, Signals
from .taxonomy import ref_category
from .textnorm import for_matching

PROFANITY = re.compile(
    r"\b(х[уy]й|х[уy]е|х[уy]я|пизд|еба|ёба|ебл|ебу|бля|сука|суки|пидор|пидр|чмо|уеб|гандон|гондон|шлюх|мудак|долбо[её]б|"
    r"нахуй|нахер|хуесос|далбо|ебан)\w*", re.I)
# признаки узких тем оскорбления: пропаганда (2.2) и расизм, ксенофобия, религия (2.4)
_INSULT_TOPIC_CUES = {
    "2.2": re.compile(r"пропаганд|18\+|порн|секс|наркот|лгбт|политик|суицид|нацизм|sex|porn"),
    "2.4": re.compile(r"расиз|нац(?:ия|ии|ист|ионал)|религ|негр|нег#|xenoph|ислам|мусульман|христиан|еврей|хохл|чурк"),
}
_GZ_HINT = re.compile(r"\bзз\b|\bgz\b|\bгз\b|зел[её]н\w* зон|green|yashil zona|\bzz\b|больниц|bolnits|банк|автосалон|"
                      r"вокзал|стоянк|авторынк|автошкол|мэри|правительств|\bсми\b|bolnitsa", re.I)
_GZ_CRIME = re.compile(r"вер[её]вк|мешок|похищ|связ(ал|ка|али)|arqon|qop", re.I)
_VEHICLE = re.compile(r"машин|тачк|\bавто\b|транспорт|перевер|эвакуат|вытащ|в вод[уе]|речк|мото|байк|mashin|moshin|көлі", re.I)
_SERVICE = re.compile(r"\bтп\b|телепорт|тепни|спавн дайте|дайте (денег|деньги|машин|вирт|лвл|уровень)|заправ|\bmp\b|\bмп\b|"
                      r"мероприяти|подкиньте|teleport", re.I)
_RP_DISPUTE = re.compile(r"наручник|посадил|арест|\bкоп\b|мент|связал|заломал|задерж|kishan|qamad|не по рп|нон ?рп", re.I)
_TECH = re.compile(r"\bвип\b|\bvip\b|донат|не приш|не появ|купил|купив|\bбаг\b|не работает|вылет|лагает|фризит|почт", re.I)
# «как подать жалобу»: нужно слово-вопрос рядом; просто упоминание жалобы («проверьте мою жалобу») не повод объяснять, как её подавать
_HOWTO_COMPLAINT = re.compile(
    r"(?:как|где|куда|каким образом|что делать|можно ли|подскажите|помогите)\W+(?:\w+\W+){0,5}?(?:жалоб|\bжб\b|shikoyat|шағым)"
    r"|(?:жалоб\w*|\bжб\b)\W+(?:\w+\W+){0,4}?(?:как|где|куда)\b"
    r"|(?:qanday|qayerda|қалай|қайда)\W+(?:\w+\W+){0,4}?(?:shikoyat|шағым)", re.I)
# вопрос о судьбе уже поданной жалобы: ответа в базе нет, отвечает человек
_COMPLAINT_STATUS = re.compile(
    r"(?:проверьте|рассмотрите|посмотрите|ответьте|ждать|жду|обещает\w*)\W+(?:\w+\W+){0,4}?(?:жалоб|\bжб\b|репорт)"
    r"|(?:жалоб\w*|\bжб\b|репорт\w*)\W+(?:\w+\W+){0,4}?(?:одобрил\w*|рассмотр\w*|проверил\w*|до сих пор)", re.I)

# Правила уровня черновика. Классификатор их не видит (признаки модели не менялись), они только выбирают сценарий ответа.
_HELP_EXTRA = re.compile(r"помож|помоч|помог|yordam|көмек", re.I)               # «поможіть», «помочь»
_STUCK_VEHICLE = re.compile(r"(?:упал\w*|провалил\w*|утонул\w*|застрял\w*|перевернул\w*|слетел\w*)\W+(?:\w+\W+){0,3}?(?:в вод|в реч|в рек|в озер)|в вод[еу]\b|на крыше")
# слово «машина» обязательно рядом: застрявший в текстурах персонаж эвакуатором не вытаскивается
_DEFINITION_Q = re.compile(r"^\W*(?:(?:привет\w*|здравствуйте|админ\w*|подскажите)\W+){0,2}(?:что\s+(?:такое|значит|означает)|кто\s+такой)\b")
# слова про наказание игрока и вопрос о нём: «почему бан?», «когда снимете мут», «за что варн»
_PENALTY = r"(?:бан\w*|мут\w*|варн\w*|warn\w*|наказани\w*|деморган\w*|блокировк\w*)"
_PENALTY_Q = re.compile(
    rf"(?:почему|за ?что|когда|причин\w*|поясни\w*|объясни\w*|разъясни\w*)\W+(?:\w+\W+){{0,4}}?{_PENALTY}"
    rf"|{_PENALTY}\W+(?:\w+\W+){{0,3}}?(?:почему|за ?что|когда|снимут|снимете|снят\w*|поясни\w*|объясни\w*)")
_THIRD_PARTY = re.compile(r"\b(?:игрок\w*|нарушител\w*|ему|этому|его|ей|им)\b")
# просьба снять наказание и «я невиновен» на казахском, узбекском и английском (русские формы есть в signals.TOPICS['appeal'])
_APPEAL_EXTRA = re.compile("|".join([
    r"(?:бан|жаза|мут)\w*\s+(?:\w+\s+)?(?:алып\s*тас|шеш|кері\s*қайтар)", r"кінәлі\s+емес", r"қате\s+жаза",
    r"(?:ban|jazo|mute|warn)\w*\s+(?:\w+\s+)?(?:yech|olib\s*tashla|bekor|qaytar)", r"aybdor\s+emas", r"noto['ʻ’‘]?g['ʻ’‘]?ri\s+(?:ban|jazo)",
    r"\bunban\b", r"(?:lift|remove)\s+(?:the|my)\s+(?:ban|mute|penalty)", r"(?:ban|mute)\s+(?:was|is)\s+(?:unfair|wrong)",
]))
# администратор как объект обвинения в коррупции: это жалоба на администратора, а не обжалование наказания
_ADMIN_MISCONDUCT = re.compile(
    r"(?:админ\w*|администратор\w*|хелпер\w*|модератор\w*|куратор\w*)\W+(?:[\w.]+\W+){0,2}?(?:берет|берут|брал\w*|взятк\w*|вымогает|вымогал\w*|торгует|продает)"
    r"|взятк\w*|за деньги\W+(?:\w+\W+)?(?:разбан|снима|снять|сним)")
# в репорте администратор назван нарушителем: «админ Ivan_Petrov12 телепортировал меня и ограбил»
_ADMIN_ACTED = re.compile(
    r"(?:админ\w*|администратор\w*|хелпер\w*|модератор\w*)\W+(?:[\w]+_[\w]+\W+)?(?:телепортировал\w*|ограбил\w*|кикнул\w*|"
    r"оскорбил\w*|нахамил\w*|убил\w*|обманул\w*|кинул\w*|вымогает|берет|использует|читит)")
_VIOLATION_TOPICS = ("insult", "cheat", "dm", "scam", "rmt_ads")
# отрицание перед упоминанием нарушения: «не читер», «я его даже не убил», «без читов», «не использую читы»
_NEGATOR = re.compile(
    r"(?:^|\W)(?:не|ни|нет|нету|без|никто|никого|никогда)\W+(?:(?:даже|просто|совсем|вообще|специально|сам|его|ее|их|ему|им|я|мы|"
    r"использую|использовал\w*|применяю|применял\w*|юзаю|юзал\w*|покупал\w*|пользовал\w*|имею|имел\w*|ставил\w*)\W+){0,2}$")
_CLAUSE = re.compile(r"[^.,;:!?()\n]+")
_CLAUSE_SPLIT = re.compile(r"\s(?:а|но|зато|однако|хотя)\s")
_FIRST_PERSON = re.compile(r"\bя\b|\bмы\b")
_SIMPLE_SUBJECT = {"это", "он", "она", "они", "тут", "там", "да", "вообще", "просто", "же", "но", "и", "ну", "так", "ведь"}


@dataclass
class Draft:
    lang: str
    text: str
    cited: list[str] = field(default_factory=list)
    intent: str = ""
    auto_ok: bool = False          # можно отправить без человека
    reasons: list[str] = field(default_factory=list)
    proposes_penalty: bool = False
    alternatives: list = field(default_factory=list)   # [{"intent", "text", "cited"}] для интерфейса админа


def _fmt(tpl: str, **kw) -> str:
    out = tpl
    for k, v in kw.items():
        out = out.replace("{" + k + "}", str(v))
    return out


# вместо номера пункта, которого нет в rules.json: ссылку выдумывать нельзя
_NO_CITE = {"ru": "правил сервера", "kk": "сервер ережелерінің", "uz": "server qoidalarining", "en": "the server rules",
            "es": "las reglas del servidor", "pt": "as regras do servidor"}


def cite_text(rb: RuleBase, cite: str, lang: str, genitive: bool = False) -> str:
    p = rb.get(cite)
    if p is None:
        return _NO_CITE.get(lang, _NO_CITE["ru"])
    tpl = i18n.T[lang]["cite"]
    section = i18n.SECTION_GEN[lang][p.section_id]
    txt = _fmt(tpl, ref=p.ref, section=section)
    if genitive and lang == "kk":
        txt = txt.replace("-тармағы", "-тармағының")
    return txt


_MAX_TITLE = 90
_NAME_CONF = 0.7      # ниже этой уверенности категории нарушение в запросе доказательств не называем
# служебное слово в конце обрезанного названия: «…шумы, а также»
_DANGLING = re.compile(r"[\s,;:(/-]+(?:а также|а|и|или|либо|в|во|на|с|со|по|из|за|для|от|до|при|к|о|об|не|без|включая|то есть)$", re.I)


def _tidy_title(s: str) -> str:
    """Название нарушения из текста пункта: без точки в конце, обрезка по запятой или границе слова, скобки в паре,
    без висящего служебного слова."""
    s = s.strip(" ,;:.")
    if len(s) > _MAX_TITLE:
        cut = s[:_MAX_TITLE]
        comma = cut.rfind(", ")
        s = cut[:comma] if comma >= 40 else cut.rsplit(" ", 1)[0]
    while s.count("(") > s.count(")"):
        s = s[:s.rfind("(")]
    prev = None
    while prev != s:
        prev = s
        s = _DANGLING.sub("", s).rstrip(" ,;:(/-")
    return s


def rule_title(rb: RuleBase, cite: str, lang: str) -> str | None:
    if cite in i18n.RULE_TITLES:
        return i18n.RULE_TITLES[cite][lang]
    p = rb.get(cite)
    if p is None:
        return None
    if lang == "ru":
        body = p.body
        body = re.sub(r"^Запрещен[оаы]?\s+", "", body)
        first = re.split(r"[.:;]\s", body)[0]
        return _tidy_title(first) or None
    return None


def term_title(term: str, lang: str) -> str | None:
    """Короткое название RP-термина: «убийство без RP-причины» из «DeathMatch (убийство без RP-причины)»."""
    full = i18n.RP_TERM_TITLES.get(term, {}).get(lang)
    if not full:
        return None
    m = re.fullmatch(r".*?\((.+)\)", full)
    return m.group(1) if m else full


def violation_denial(t: str) -> str | None:
    """Отрицает ли игрок нарушение, о котором пишет: «first» (от первого лица: «я не оскорблял»), «other» («это не читер»)
    или None, если хотя бы одно упоминание нарушения не отрицается («он не отстаёт, матерится»).

    Область отрицания клауза: после запятой, точки и союзов «а», «но» отрицание не действует. Разбор только русского текста;
    для остальных языков остаются обычные сигналы обжалования.
    """
    cues = sorted(m.start() for name in _VIOLATION_TOPICS for m in TOPICS[name].finditer(t))
    if not cues:
        return None
    negated_clauses, first_person = 0, False
    for seg in _CLAUSE.finditer(t):
        pos = seg.start()
        for part in _CLAUSE_SPLIT.split(seg.group(0)):
            start = t.find(part, pos)
            end = pos = start + len(part)
            inside = [c for c in cues if start <= c < end]
            if not inside:
                continue
            neg = _NEGATOR.search(t[start:inside[0]])
            if not neg:
                return None
            mine = bool(_FIRST_PERSON.search(part))
            # не от первого лица отрицание принимаем только в простой форме («это не читер»); пересказ чужих слов
            # («он сказал не скам, я отдал машину») отрицанием не считается
            if not mine and not set(re.findall(r"\w+", part[:neg.start()])) <= _SIMPLE_SUBJECT:
                return None
            negated_clauses += 1
            first_person = first_person or mine
    if not negated_clauses:
        return None
    return "first" if first_person else "other"


# ---------- выбор пунктов ----------
def pick_violation(cat: str, sig: Signals, text: str, rb: RuleBase) -> tuple[str | None, str | None]:
    """Возвращает (пункт правил | None, RP-термин | None) для черновика с нарушением."""
    t = for_matching(text)
    for r in sig.rule_refs:
        rc = ref_category(r)
        if rc == cat and rb.exists(r):
            if r == "GZ 1.1" and _GZ_CRIME.search(t):
                return "GZ 1.2", None
            # в форме часто выбирают 2.2 или 2.4 вместо 2.1; без признаков этой темы в тексте админы чаще всего ставили 2.1
            # (train, одобренные жалобы: 2.2 без признаков темы 40 из 59 — 2.1, 10 — 2.2; 2.4: 6 из 9 — 2.1)
            if cat == "complaint.insult" and r in _INSULT_TOPIC_CUES and not _INSULT_TOPIC_CUES[r].search(t) and rb.exists("2.1"):
                return "2.1", None
            return r, None
    if cat == "complaint.insult":
        if re.search(r"расиз|нац(ия|ии|ист|ионал)|религ|негр|нег#|xenoph", t):
            return "2.4", None
        if "threat_irl" in sig.topics or re.search(r"угроз|ugroz|tahdid", t):
            return "2.6", None
        if re.search(r"пропаганд|18\+|порн|секс|наркот", t):
            return "2.2", None
        if re.search(r"(оск|хам|обзыва|матер)\w*\W+(\w+\W+)?(админ|администрац|хелпер)", t):
            return "3.2", None
        return "2.1", None
    if cat == "complaint.cheat":
        return "5.2", None
    if cat == "complaint.scam":
        return ("4.2" if re.search(r"вымога|pora|undur|шантаж", t) else "4.1"), None
    if cat == "complaint.rmt_ads":
        return ("2.3" if re.search(r"реклам|reklam", t) else "4.4"), None
    if cat == "complaint.dm":
        if _GZ_HINT.search(t):
            return ("GZ 1.2" if _GZ_CRIME.search(t) else "GZ 1.1"), None
        if re.search(r"уход\w* от рп|ушел от рп|вышел из игры|\bafk\b|афк", t) and not re.search(r"стоял\w* (в )?афк|был (в )?афк", t):
            return "5.3", None
        if re.search(r"у (моего |своего )?дома|территори\w+ дома|в квартир|uy(im)? oldi", t):
            return "5.4", None
        for code, rx in (("SK", r"\bск\b|\bsk\b|спавн ?кил|spawn"), ("TK", r"\bтк\b|\btk\b"), ("RK", r"\bрк\b|\brk\b"),
                         ("DB", r"\bдб\b|\bdb\b|задавил|сбил|таран|машин\w* (сбил|задавил)|ezib"),
                         ("NONRP", r"non ?rp|нон ?рп|\bнрп\b|\bnrp\b|без рп|bez rp|наручник|kishan|посадил|арест"),
                         ("DM", r".")):
            if re.search(rx, t):
                return None, code
    if cat == "complaint.other":
        for code, rx in (("5.6", r"секс|домога|изнасил|альтушк|\bsex|отыгровк\w* (насил|интим)|18\+"),
                         ("1.2", r"(представля|выдает себя|выдаёт себя|говорит что)\w*\W+(\w+\W+)?(админ|разработчик)"),
                         ("5.8", r"(фам|семь|семей)\w*.*(копир|назван|плагиат)|(копир|плагиат)\w*.*(фам|семь)"),
                         ("1.6", r"\bник\w*|никнейм|nick"),
                         ("5.7", r"номер\w* (знак|машин|авто)|\bномера\b"),
                         ("5.9", r"ивент|мероприяти|\bмп\b|event"),
                         ("2.5", r"музык|микрофон|в войс|орет|орёт|кричит|гс\b"),
                         ("3.2", r"(оск|хам|клевет|обман)\w*\W+(\w+\W+)?(админ|администрац)")):
            if re.search(rx, t):
                return code, None
        if re.search(r"[а-яё]", t):
            hits = rb.search(text, k=1, sections={30})
            if hits and hits[0][1] >= 12.0:
                return hits[0][0].cite, None
    return None, None


def term_sanction(rb: RuleBase, code: str) -> list:
    term = rb.terms.get(code)
    if not term:
        return []
    parts = term.text.split("|")
    if len(parts) < 2:
        return []
    return sanctions.parse(parts[1].strip())


# ---------- сценарии ----------
def decide_outcome(cat: str, verdict: str | None, conf: float, sig: Signals) -> str | None:
    """Сценарий для жалобы с нарушением.

    Оскорбления админы обычно решают по скриншоту чата, а DM, читы и скам
    требуют видео (ЖБ 1.3.1). Поэтому один и тот же прогноз модели исхода
    по-разному переводится в сценарий для разных категорий.
    """
    if cat == "complaint.insult":
        if verdict == "need_evidence" and conf >= 0.6:
            return "need_evidence"
        return "approve"
    if cat in ("complaint.dm", "complaint.cheat", "complaint.scam", "complaint.rmt_ads"):
        if sig.has_url and not (verdict == "need_evidence" and conf >= 0.7):
            return "approve"   # ссылка на видео (фрапс) есть
        if verdict == "approve" and conf >= 0.6:
            return "approve"
        return "need_evidence" if verdict != "reject" else "reject"
    return verdict


def build(kind: str, cat: str, sig: Signals, text: str, lang: str, rb: RuleBase,
          verdict: str | None, nick: str | None, duplicate: bool, verdict_conf: float = 0.5,
          cat_conf: float = 1.0) -> Draft:
    L = i18n.T[lang]
    t = for_matching(text)

    def done(intent: str, body: str, cited: list[str], auto: bool, reasons: list[str] | None = None,
             penalty: bool = False) -> Draft:
        hello = L["hello"]
        full = f"{hello} {body}".strip()
        reasons = list(reasons or [])
        missing = [c for c in cited if not rb.exists(c)]
        if missing:
            # пункт, зашитый в сценарий, отсутствует в этой версии rules.json: номер в текст не попал
            reasons.append("пункты не найдены в rules.json, ссылка в тексте обезличена: " + ", ".join(missing))
            auto = False
        return Draft(lang=lang, text=full, cited=[c for c in cited if rb.exists(c)], intent=intent, auto_ok=auto,
                     reasons=reasons, proposes_penalty=penalty)

    def ct(c, gen=False):
        return cite_text(rb, c, lang, genitive=gen)

    common = dict(support=i18n.SUPPORT_URL, discord=i18n.DISCORD_URL)

    if duplicate:
        c = "ЖБ 1.2.9" if kind == "complaint" else "3.1"
        if kind == "complaint":
            return done("duplicate", _fmt(L["duplicate"], cite=ct(c)), [c], True, ["повтор обращения за последний час"])
        return done("duplicate", _fmt(L["offtopic_flood"], cite=ct(c)), [c], True, ["повтор репорта за последний час"])

    # ---------------- жалобы ----------------
    if kind == "complaint":
        req, tm = "ЖБ 1.3.1", "ЖБ 1.2.6"

        def appeal_draft(extra_reason: str | None = None) -> Draft:
            """Обжалование: итог (наказание выдано верно или снято) сервис не знает, поэтому черновик его не утверждает.
            Отклонение остаётся вариантом для администратора, который проверил наказание."""
            reasons = ["обжалование наказания: решает старшая администрация",
                       "черновик не утверждает итог: наказание сервис не проверял; если оно выдано верно, "
                       "выберите вариант «Отклонить обжалование»"]
            d = done("appeal", _fmt(L["appeal"], cite_req=ct(req), cite_time=ct(tm)), [req, tm], False,
                     reasons + ([extra_reason] if extra_reason else []))
            alt = done("appeal_reject", _fmt(L["appeal_reject"], cite_req=ct(req)), [req], False)
            d.alternatives.append({"intent": alt.intent, "text": alt.text, "cited": alt.cited})
            return d

        misconduct = bool(_ADMIN_MISCONDUCT.search(t))
        if cat == "complaint.admin":
            if "appeal" in sig.topics and not misconduct:
                return appeal_draft()
            if _PENALTY_Q.search(t) and not misconduct and not _THIRD_PARTY.search(t):
                return appeal_draft("игрок спрашивает о своём наказании")
            return done("admin_complaint", _fmt(L["admin_complaint"], cite_req=ct(req)), [req], False,
                        ["жалоба на администратора: решает старшая администрация"])

        # игрок спрашивает о своём наказании или просит его снять (в том числе на kk/uz/en): это обжалование
        if cat in ("complaint.invalid", "complaint.other") and not misconduct and (
                _APPEAL_EXTRA.search(t) or (_PENALTY_Q.search(t) and not _THIRD_PARTY.search(t))):
            return appeal_draft("в тексте просьба снять наказание или вопрос о нём")

        # игрок отрицает нарушение: «я не оскорблял», «это не читер»; подтверждать или запрашивать доказательства нельзя
        if cat not in ("complaint.invalid", "complaint.admin"):
            denial = violation_denial(t)
            if denial == "first":
                return appeal_draft("игрок пишет, что не совершал нарушения")
            if denial == "other" and sig.words <= 12:
                return done("clarify", L["clarify"], [], False,
                            ["в тексте нарушение отрицается («не читер», «не оскорблял»): нужно уточнение или решение человека"])

        if cat == "complaint.invalid":
            if PROFANITY.search(t) and sig.words >= 2:
                c = "ЖБ 1.2.7"
                return done("toxic", _fmt(L["toxic"], cite=ct(c)), [c], True, ["в тексте жалобы оскорбления (ЖБ 1.2.7)"])
            if sig.topics & {"question", "greeting_offtopic"} or sig.words >= 4:
                c = "ЖБ 1.1.2"
                body = _fmt(L["not_complaint"], cite=ct(c), **common)
                reasons = ["обращение не является жалобой"]
                hit = kb.lookup(text, lang) if "question" in sig.topics else None
                if hit:
                    body += " " + hit[0]
                    reasons.append(f"добавлен ответ из базы знаний «{hit[1].key}»")
                return done("not_complaint", body, [c], True, reasons)
            c = "ЖБ 1.2.3"
            if sig.has_url:
                return done("no_description", _fmt(L["no_description"], cite=ct(c)), [c], False,
                            ["нет описания, но есть ссылка: администратор должен открыть видео"])
            return done("no_description", _fmt(L["no_description"], cite=ct(c)), [c], True, ["нет описания ситуации"])

        prof_hits = len(PROFANITY.findall(t))
        if cat != "complaint.insult" and prof_hits >= 2:
            c = "ЖБ 1.2.7"
            return done("toxic", _fmt(L["toxic"], cite=ct(c)), [c], False, ["в тексте жалобы оскорбления (ЖБ 1.2.7)"])
        rule, term = pick_violation(cat, sig, text, rb)
        nick_part = _fmt(L["nick_part"], nick=nick) if nick else ""
        no_desc = sig.words <= 1 and not sig.has_url
        if verdict == "reject" and no_desc:
            c = "ЖБ 1.2.3"
            return done("no_description", _fmt(L["no_description"], cite=ct(c)), [c], False,
                        ["нет описания, только код пункта: проверьте приложенные скриншоты"])
        verdict = decide_outcome(cat, verdict, verdict_conf, sig)
        approve_d = _approve(L, rule, term, text, lang, rb, ct, done, nick_part) if (rule or term) else None
        # нарушение называем в запросе доказательств, только если категория надёжна или пункт указал сам игрок:
        # иначе ошибка модели становилась бы утверждением в тексте (по собственной разметке верно 93 % при уверенности от 0,7)
        name_it = cat_conf >= _NAME_CONF or (rule is not None and rule in sig.rule_refs)
        if verdict == "approve" and approve_d:
            ne = _need_evidence(L, rule if name_it else None, term if name_it else None, lang, rb, ct, done)
            approve_d.alternatives.append({"intent": ne.intent, "text": ne.text, "cited": ne.cited})
            return approve_d
        ne = _need_evidence(L, rule if name_it else None, term if name_it else None, lang, rb, ct, done)
        if approve_d:
            ne.alternatives.append({"intent": approve_d.intent, "text": approve_d.text, "cited": approve_d.cited})
        return ne

    # ---------------- репорты ----------------
    if cat == "report.account":
        c = "1.4"
        return done("account", _fmt(L["account"], cite=ct(c), **common), [c], False,
                    ["аккаунт или имущество: всегда человек"])
    if cat == "report.payment":
        return done("payment", _fmt(L["payment"], **common), [], False, ["платёж: всегда человек"])
    if "threat_irl" in sig.topics:
        c = "2.6"
        return done("threat", _fmt(L["threat"], cite=ct(c)), [c], False, ["угроза вне игры: p0, человек"])
    def watch_draft(who: str | None) -> Draft:
        pid_part = _fmt(L["pid_part"], pid=who) if who else ""
        return done("report_watch", _fmt(L["report_watch"], pid_part=pid_part), [], False, ["нужно проследить за игроком в игре"])

    def question_flow() -> Draft:
        if "appeal" in sig.topics:
            c = "ЖБ 1.2.6"
            return done("report_appeal", _fmt(L["report_appeal"], cite_time=ct(c)), [c], True, ["несогласие с наказанием"])
        if _TECH.search(t):
            return done("question_tech", _fmt(L["question_tech"], **common), [], True, ["технический вопрос"])
        if _HOWTO_COMPLAINT.search(t):
            return done("question_howto", L["question_complaint_howto"], [], True, ["как подать жалобу"])
        if _COMPLAINT_STATUS.search(t):
            return done("help_ack", L["help_ack"], [], False,
                        ["вопрос о судьбе поданной жалобы: статус проверяет администратор"])
        if _VEHICLE.search(t) and _STUCK_VEHICLE.search(t):
            return done("help_vehicle", L["help_vehicle"], [], True, ["транспорт: есть кнопка эвакуатора"])
        hit = kb.lookup(text, lang)
        if hit:
            ans, entry = hit
            return done("question_kb", ans, [], True,
                        [f"ответ из базы знаний «{entry.key}»: так отвечали админы {entry.support} раз"])
        # не вопрос по механике (категория модели ошиблась): игрок зовёт на помощь или называет нарушителя
        who = sig.report_id or nick
        if who and "question" not in sig.topics:
            return watch_draft(who)
        if _RP_DISPUTE.search(t) and "question" not in sig.topics:
            return done("report_rp", L["report_rp"], [], False,
                        ["RP-ситуация без явного нарушения; категория модели была «вопрос», проверьте, не нужна ли помощь"])
        if "help_word" in sig.topics or _HELP_EXTRA.search(t):
            return done("help_ack", L["help_ack"], [], False,
                        ["просьба о помощи без деталей: админы обычно сразу подключаются и следят за игроком"])
        return done("question_unknown", _fmt(L["question_unknown"], **common), [], False,
                    ["вопрос по механике вне базы знаний: ответ проверяет человек"])

    if cat == "report.complaint":
        if "appeal" in sig.topics:
            c = "ЖБ 1.2.6"
            return done("report_appeal", _fmt(L["report_appeal"], cite_time=ct(c)), [c], True, ["несогласие с наказанием"])
        if (_DEFINITION_Q.match(t) or _COMPLAINT_STATUS.search(t)) and not sig.report_id and not nick:
            return question_flow()                  # «что значит ДМ», «проверьте мою жалобу»: это вопрос, а не жалоба
        if sig.report_id:
            return watch_draft(sig.report_id)
        if _RP_DISPUTE.search(t):
            return done("report_rp", L["report_rp"], [], True, ["RP-ситуация без явного нарушения"])
        if nick:
            return watch_draft(nick)
        return done("report_need_id", L["report_need_id"], [], False, ["нужно проследить за игроком в игре"])
    if cat == "report.help":
        if _ADMIN_ACTED.search(t):
            req = "ЖБ 1.3.1"
            return done("admin_complaint", _fmt(L["admin_complaint"], cite_req=ct(req)), [req], False,
                        ["в репорте администратор назван нарушителем: решает старшая администрация"])
        if _SERVICE.search(t) and not _VEHICLE.search(t):
            c = "3.1"
            return done("help_service", _fmt(L["help_service"], cite=ct(c)), [c], True, ["просьба о телепорте или имуществе"])
        if _VEHICLE.search(t):
            return done("help_vehicle", L["help_vehicle"], [], True, ["транспорт: есть кнопка эвакуатора"])
        return done("help_generic", L["help_generic"], [], False, ["нужна помощь администратора в игре"])
    if cat == "report.question":
        return question_flow()
    # «+» в репорт: игроки так просят телепорт на мероприятие (админы отвечают «телепорт на МП закрыт»)
    if re.fullmatch(r"\s*\++\s*", text or ""):
        return done("event_tp", L["event_tp"], [], False,
                    ["«+» в репорте означает запрос телепорта на мероприятие (кластер из 2869 таких репортов в train)",
                     "открыт ли сейчас телепорт, знает только администратор"])
    # оффтоп
    if PROFANITY.search(t) or sig.topics & {"greeting_offtopic"} and not sig.topics & {"help_word"}:
        c = "3.1"
        return done("offtopic_flood", _fmt(L["offtopic_flood"], cite=ct(c)), [c], True, ["оффтоп"])
    if _VEHICLE.search(t) and _STUCK_VEHICLE.search(t):
        return done("help_vehicle", L["help_vehicle"], [], True, ["транспорт: есть кнопка эвакуатора"])
    if "help_word" in sig.topics or _HELP_EXTRA.search(t):
        return done("help_ack", L["help_ack"], [], False,
                    ["просьба о помощи без деталей: админы обычно сразу подключаются и следят за игроком"])
    return done("clarify", L["clarify"], [], True, ["нет содержания, нужно уточнение"])


def _need_evidence(L, rule, term, lang, rb, ct, done) -> Draft:
    req, plat = "ЖБ 1.3.1", "ЖБ 1.2.1"
    # какое именно нарушение проверяется: название пункта или RP-термина на языке игрока, если оно известно
    title = rule_title(rb, rule, lang) if rule else term_title(term, lang) if term else None
    what = _fmt(L["what"], title=title) if title else ""
    body = _fmt(L["need_evidence"], what=what, cite_req=ct(req), cite_platform=ct(plat))
    return done("need_evidence", body, [req, plat], False,
                ["запрос доказательств: администратор проверяет приложенные скриншоты"])


def _approve(L, rule, term, text, lang, rb, ct, done, nick_part) -> Draft:
    if rule:
        sanc = sanctions.render(sanctions.choose(rb.get(rule), text), lang)
        title = rule_title(rb, rule, lang)
        body_tpl = L["approve"] if sanc else L["approve_nosanction"]
        body = _fmt(body_tpl, cite=ct(rule), cite_gen=ct(rule, gen=True), title=title or "",
                    nick_part=nick_part, sanction=sanc)
        if not title:
            body = body.replace(" ()", "")
        return done("approve", body, [rule], False,
                    ["черновик предлагает наказание: решение подтверждает администратор"], penalty=True)
    sanc = sanctions.render(term_sanction(rb, term), lang)
    title = i18n.RP_TERM_TITLES.get(term, {}).get(lang, term)
    body = _fmt(L["approve_term"], term=title, nick_part=nick_part, sanction=sanc or "—")
    return done("approve", body, [], False,
                ["черновик предлагает наказание: решение подтверждает администратор",
                 "нарушение из раздела «RP термины», у раздела нет номеров пунктов"], penalty=True)


def section_of(cite: str) -> int | None:
    for sid, (prefix, _, _) in SECTIONS.items():
        if prefix and cite.startswith(prefix + " "):
            return sid
    return 30 if re.fullmatch(r"\d+(\.\d+)+", cite) else None
