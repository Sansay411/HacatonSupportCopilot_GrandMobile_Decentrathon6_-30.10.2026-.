"""Детерминированные сигналы из текста: темы, извлечение фактов, флаги риска.

Словари собраны по 118 тыс. обращений из train: сленг (оск, дм, дб, тк, ск,
софт, скам, опру), транслит (osk, soft), узбекские и казахские формы.
Эти же сигналы служат признаками классификатора и жёсткими правилами
для needs_human.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textnorm import for_matching


def _rx(*parts: str) -> re.Pattern:
    return re.compile("|".join(parts), re.IGNORECASE)


TOPICS: dict[str, re.Pattern] = {
    # оскорбления и токсичность
    "insult": _rx(
        r"\bоск", r"\bosk", r"\boсk", r"оскорб", r"обзыва", r"обозвал", r"\bмат(ом|ерит|ерился|еришь|ы)?\b",
        r"матер", r"упом", r"родн", r"\bрод\b", r"\brod\b", r"мамк", r"\bмать\b", r"\bмам[уы]\b",
        r"токси", r"унижа", r"расизм", r"нацик", r"рофл.*родн", r"\b2\.[146]\b", r"haqorat", r"xaqorat", r"haqr", r"xaqr",
        r"so'?k(di|indi|yapti|ish)", r"sokdi", r"sokin", r"sukin", r"so[ʻ']kin", r"onadan", r"onamni", r"onamdan",
        r"балағат", r"сөкт", r"анамды", r"туыс", r"insult", r"\bxingou", r"\bhaqorat",
    ),
    "threat_irl": _rx(
        r"найду теб", r"вычисл", r"\bдеанон", r"\bдокс", r"\bсват", r"адрес.*(знаю|скин)", r"\bip\b.*(знаю|вычисл)",
        r"убью (тебя )?(в )?(реал|ирл|жизн)", r"в реальн(ой|ую) жизн", r"\birl\b", r"\b2\.6\b", r"угрож(ает|ал).*(реал|жизн|семь)",
    ),
    "cheat": _rx(
        r"\bсофт", r"\bsoft", r"\bчит", r"\bchit", r"\bcheat", r"аим", r"\baim", r"\bвх\b", r"\bwh\b", r"летает", r"fly",
        r"спидхак", r"speed ?hack", r"\bбот\b", r"автоклик", r"макрос", r"\bмакро", r"скрипт", r"сборк", r"багоюз",
        r"\bбаг(ом|и)? (юз|использ)", r"телепорт(ируется|ит)", r"\b5\.2\b", r"\bхак", r"hack", r"стороннее по", r"\bтп(шится|ается)",
    ),
    "dm": _rx(
        r"\bдм\b", r"\bdm\b", r"дмит", r"дмят", r"\bдб\b", r"\bdb\b", r"\bтк\b", r"\btk\b", r"\bск\b", r"\bsk\b",
        r"\bрк\b", r"\brk\b", r"\bnon ?rp\b", r"нон ?рп", r"\bнрп\b", r"\bnrp\b", r"\bпг\b", r"\bpg\b", r"\bмг\b", r"\bmg\b",
        r"убил", r"убива", r"убьет", r"застрелил", r"стреля", r"без причин", r"без рп", r"бес причин", r"sababsiz",
        r"be ?sabab", r"o'?ldir", r"uldir", r"oldirdi", r"otdi", r"otyap", r"зелен(ой|ая) зон", r"\bзз\b", r"\bgz\b", r"\bгз\b",
        r"\b5\.[345]\b", r"\b1\.[12] ?(gz|гз|зз)", r"\bfw\b", r"\bфв\b", r"таран", r"сбил", r"задавил", r"наручник",
        r"посадил", r"\bkishan", r"qamad", r"qamoq", r"арестовал", r"посадили", r"мент", r"\bкоп", r"\bkop\b", r"розыск",
        r"өлтір", r"ұрды", r"себепсіз",
    ),
    "scam": _rx(
        r"\bскам", r"\bscam", r"\bskam", r"обман", r"кинул", r"развел", r"развёл", r"мошен", r"не вернул", r"не отдал",
        r"не перевел", r"не перевёл", r"\bдолг", r"вымога", r"\b4\.[12]\b", r"aldab", r"aldadi", r"алдап", r"\bукрал",
        r"не скинул", r"забрал (деньги|машину|авто)", r"кража",
    ),
    "rmt_ads": _rx(
        r"реклам", r"за реал", r"реальн(ые|ых) (деньг|руб)", r"\bрмт\b", r"\brmt\b", r"продает (акк|аккаунт|вирт)",
        r"продаёт (акк|аккаунт|вирт)", r"\bтг\b", r"телег", r"telegram", r"\btg\b", r"\bfunpay", r"фанпей", r"другой сервер",
        r"\b2\.3\b", r"\b4\.4\b", r"вирты за", r"\bдискорд сервер",
    ),
    "appeal": _rx(
        r"не ?согл", r"\bопру\b", r"оспар", r"снимите", r"сняти[ея] наказ", r"разбан", r"разблок", r"амнист", r"пересмотр",
        r"выдал (мне|бан|мут|варн|деморган|джайл)", r"(мне|меня) (выдали|забанили|замутили|посадили в деморган)",
        r"забанил[и]? (меня|ни за)", r"за что (бан|мут|варн|наказ)", r"наказали (просто|ни за|без)", r"\bнаказан(ие|ия) (не ?верн|ошиб)",
        r"админ(истратор)? (ошиб|не прав|выдал|наказал|забанил|замутил)", r"ошибочн", r"рофл.*бан", r"\bunban",
        r"disagree", r"unfair (ban|mute)", r"\bi did(n'?t| not)\b", r"no estoy de acuerdo", r"n[ãa]o concordo", r"desban",
        r"rozi emasman", r"\bne ?sogl", r"norozi", r"noroziman", r"не үшін бан", r"nega (ban|mute|warn)", r"nma sababdan ban",
        r"самооборон", r"ты о ч[её]м", r"в каком месте", r"как я оказался", r"\bперевыдал", r"разбант", r"разбан",
        r"(амнист|прошу прощени|признаю|раска(иваюсь|юсь))", r"yechila", r"yechib", r"ban yech", r"нохақ", r"nohaq", r"келіспеймін", r"ban berdi", r"mute beradi", r"warn bery", r"menga .*ban",
        # оправдания наказанного: «я никого не убивал», «где я текашил», «за что?»
        r"\bя (никого|не кого|ни кого|никово|ни в кого|не в кого|даже не в кого|даже не) ", r"я (даже )?(не|ни) (стрелял|убивал|оскорблял|оскал|играл|багоюзал|дмил|нарушал)",
        r"\bгде (я|тут|здесь|вы видите|вы увидели)\b", r"^\W*(эээ?,? )?за (что|шо|чт)\b", r"за что (мне|меня|бан|мут|варн|ванн|дали|наказ)",
        r"(нет|нету) (у меня )?(софт|чит)", r"у меня (нет|нету) (софт|чит)", r"кого (же )?я (убил|оскорбил)", r"\bсняли? (бан|мут|варн|наказ)",
        r"(снимите|снять|сними)\b", r"не ?верно (выдан|выдал)", r"не ?правильно выдал", r"(меня|мне) (посадили|дали|выдали|забанили)",
        r"(чекните|проверьте) (по )?лог", r"обжал", r"\bорпу\b", r"дмг (не|ни) за что", r"деморган (не|ни) за что",
        r"почему (данный |этот )?админ", r"админ(истратор)? (да[её]т|дала|сажает|забанил)", r"(наказание|бан|мут) (не поступил|не выдан)",
        r"за ?что (бан|мут)", r"\bmenga (warn|ban|mute)", r"мені (бан|жаза)", r"ничего не (нарушал|делал)", r"ештеңе жасама",
    ),
    "admin": _rx(r"\bадмин", r"\badm", r"администратор", r"\badmin", r"әкімші", r"куратор", r"хелпер", r"модератор"),
    "account": _rx(
        r"взлом", r"взломал", r"взломали", r"\bвзл", r"(пропал|пропала|пропали|исчез|исчезла|исчезли|слетел|слетела|слетели)",
        r"украли (акк|аккаунт|машин|дом|деньг|бизнес)", r"не могу (зайти|войти|вой)", r"(доступ|пароль|почт[уа]|привязк)",
        r"аккаунт.*(угнал|увели|украли|чуж)", r"\bакк(аунт)? (взл|угн)", r"hack(ed)?", r"\bbuzib", r"o'g'irla",
        r"обнул(или|ился|ение)",
    ),
    "payment": _rx(
        r"\bдонат", r"задонат", r"оплатил\w*\W+(\w+\W+)?(гк|донат|вип|vip|пропуск|кейс|карт|рубл|тенге|сум\b)",
        r"(деньги|средства) (списал|сняли|ушли)", r"платеж", r"платёж", r"\bгк\b.*(не приш|не зачисл|не дошл)",
        r"(не приш|не зачисл|не дошл).*(гк|донат|деньг|коин|coin|вип|vip)", r"списал", r"списали", r"\bчек\b", r"возврат (денег|средств)",
        r"grand ?coin", r"гранд ?коин", r"\bpaid\b", r"\bpayment", r"\bpul (to'?la|tushmadi)", r"төлеп", r"\bкупил\b.*(не приш|не дал)",
    ),
    "stuck": _rx(
        r"застрял", r"застряла", r"застряли", r"зостр", r"текстур", r"провалил", r"проволил", r"\bвытащ", r"\bбаг\b", r"\bбаги\b",
        r"\bзабаг", r"не могу (выйти|выбраться|двигаться|ходить|сесть)", r"\bтп\b", r"\btp\b", r"телепорт", r"тепни", r"телепортир",
        r"верните", r"вылетел", r"вылетает", r"\bкраш", r"stuck", r"qolib ketdim", r"qotib", r"тұрып қалдым",
        r"переверн", r"перевернi", r"перевернит", r"перевернiт", r"(до|да)ста(нь|н)те", r"\bспавн", r"\bресп", r"рестп",
        r"наручник", r"\bмешок", r"почин", r"измерени", r"потерял", r"потiрявся", r"не могу (встать|перевернуть|сесть)",
        r"страховк", r"atrapad", r"\bpreso\b", r"travad", r"\bstuck\b", r"упал в (воду|речку|реку)", r"в воде", r"улетел", r"зав'язали", r"связали",
    ),
    "question": _rx(
        r"\?", r"^\s*(как|где|когда|почему|зачем|что|какой|какая|сколько|можно ли|можно|подскажите|скажите)\b",
        r"\b(как|где) (мне|можно|купить|получить|устроиться|сделать|найти|взять)", r"подскаж", r"\bвопрос",
        r"\bqanday\b", r"\bqayerda\b", r"\bnima\b", r"\bқалай\b", r"\bқайда\b", r"\bhow\b", r"\bwhere\b", r"\bcomo\b",
    ),
    "help_word": _rx(r"помог", r"помаг", r"помоите", r"помощ", r"хелп", r"\bhelp", r"\bsos\b", r"спаси", r"\bпмг\b",
                     r"yordam", r"көмек", r"ajuda", r"ayuda", r"помоги"),
    "greeting_offtopic": _rx(r"^\s*(привет|здравствуйте|здрасте|ку|хай|hi|hello|salom|сәлем|ау|алло|\+|\.+|\?+)\s*[!.)]*\s*$",
                             r"как (у вас )?дела", r"лучший админ", r"скучно", r"\bлол\b", r"дай(те)? работу", r"\bгоск",
                             r"собеседовани", r"заправ", r"дайте (денег|деньги|машину|вирт)", r"столица", r"хорошего настроения",
                             r"добрый (вечер|день)\W*$", r"наилучш", r"на руках носить"),
    "evidence_word": _rx(r"скрин", r"видео", r"видос", r"фрапс", r"\bfraps", r"запись", r"доказ", r"\bдок[иа]\b", r"\bvideo",
                         r"dalil", r"isbot", r"ютуб", r"youtube", r"\bшортс"),
    "no_evidence_word": _rx(r"доказательств(а)? нет", r"нет (скрин|видео|доказ)", r"без доказ", r"не успел (заснять|записать|скрин)",
                            r"нету (скрин|видео|доказ)", r"не записал"),
    "big_property": _rx(r"\bдом", r"бизнес", r"машин", r"\bавто\b", r"\bкв(артир)", r"\d{2,}\s*(млн|kk|кк|лям)", r"миллион", r"\bгк\b"),
    "mass_issue": _rx(r"у всех (не|вылет|завис|пропал)", r"сервер (упал|лежит|не работает)", r"массов(ый|ые) баг",
                      r"всех (кикнуло|выкинуло)", r"не заходит никто"),
}


@dataclass
class Signals:
    topics: set[str] = field(default_factory=set)
    rule_refs: list[str] = field(default_factory=list)
    has_url: bool = False
    images: int = 0
    nickname: str | None = None
    player_id: str | None = None
    server: str | None = None
    words: int = 0
    content_free: bool = False

    @property
    def has_evidence(self) -> bool:
        return self.has_url or self.images > 0 or "evidence_word" in self.topics and "no_evidence_word" not in self.topics


_NICK = re.compile(r"\b([A-Z][a-z]{1,15}_[A-Z][a-zA-Z]{1,20}\d{0,4})\b")
_ID_REPORT = re.compile(r"(?:^|\s)(?:id|ид|айди|айд|\#)?\s*(\d{1,4})\s*(?:id|ид)?\s+(?=[а-яa-z])|(?:id|ид|айди)\s*(\d{1,4})", re.I)
_SERVER = re.compile(r"\b(?:сервер|server|серв)\s*[#№]?\s*(\d{1,2})\b|\|\s*(\d{1,2})\b", re.I)


def extract(text: str, rule_base, rule_refs_raw: str | None = None, images: int | None = None,
            reported_nick: str | None = None) -> Signals:
    m = for_matching(text)
    s = Signals()
    for name, rx in TOPICS.items():
        if rx.search(m):
            s.topics.add(name)
    refs = rule_base.parse_refs(text)
    if rule_refs_raw:
        for r in rule_base.parse_refs(rule_refs_raw):
            if r not in refs:
                refs.append(r)
        mr = for_matching(rule_refs_raw)
        for name in ("insult", "dm", "cheat", "scam", "appeal", "rmt_ads"):
            if TOPICS[name].search(mr):
                s.topics.add(name)
    s.rule_refs = refs
    s.has_url = "<url>" in text or "http" in m
    s.images = int(images or 0)
    nick = _NICK.search(text)
    s.nickname = reported_nick or (nick.group(1) if nick else None)
    idm = _ID_REPORT.search(m)
    if idm:
        s.player_id = idm.group(1) or idm.group(2)
    sm = _SERVER.search(m)
    if sm:
        s.server = sm.group(1) or sm.group(2)
    words = re.findall(r"[a-zа-яёәғқңөұүһіўҳ']{2,}", m)
    s.words = len(words)
    meaningful = [w for w in words if w not in {"url", "digits", "handle", "email", "nick"}]
    s.content_free = len(meaningful) == 0 and not refs
    return s
