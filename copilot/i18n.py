"""Тексты черновиков на шести языках клиента.

Стиль взят из реальных ответов администраторов в train (русские и узбекские
шаблоны), но без обещаний, которые сервис не может выполнить: наказание
«предлагается по правилам», решение подтверждает админ (needs_human=true).
Казахские шаблоны в выгрузке отсутствуют (на kz-сервере админы отвечают
по-русски), поэтому они написаны с нуля и требуют проверки носителем.
"""
from __future__ import annotations

SUPPORT_URL = "https://support.grnd.gg/"
DISCORD_URL = "https://discord.gg/grnd"

# названия разделов правил в форме «чего?»: «п. 2.1 Общих правил»
SECTION_GEN = {
    "ru": {30: "Общих правил", 31: "Правил подачи жалоб", 32: "Правил Зелёной Зоны", 33: "Правил для лидеров",
           34: "Правил госорганизаций", 35: "Правил гос. волны", 36: "Правил семейных мероприятий", 40: "Правил для ОПГ",
           41: "Правил войны за бизнес", 42: "Правил битвы за фургон"},
    "kk": {30: "Жалпы ережелердің", 31: "Шағым беру ережелерінің", 32: "Жасыл аймақ ережелерінің", 33: "Көшбасшылар ережелерінің",
           34: "Мемлекеттік ұйымдар ережелерінің", 35: "Мемлекеттік толқын ережелерінің", 36: "Отбасылық іс-шаралар ережелерінің",
           40: "ОПГ ережелерінің", 41: "Бизнес үшін соғыс ережелерінің", 42: "Фургон үшін шайқас ережелерінің"},
    "uz": {30: "Umumiy qoidalarning", 31: "Shikoyat berish qoidalarining", 32: "Yashil zona qoidalarining", 33: "Liderlar qoidalarining",
           34: "Davlat tashkilotlari qoidalarining", 35: "Davlat to‘lqini qoidalarining", 36: "Oilaviy tadbirlar qoidalarining",
           40: "OPG qoidalarining", 41: "Biznes uchun urush qoidalarining", 42: "Furgon uchun jang qoidalarining"},
    "en": {30: "General Rules", 31: "Complaint Rules", 32: "Green Zone Rules", 33: "Leader Rules", 34: "Government Organization Rules",
           35: "Government Radio Rules", 36: "Family Event Rules", 40: "Gang (OPG) Rules", 41: "Business War Rules", 42: "Van Battle Rules"},
    "es": {30: "las Reglas generales", 31: "las Reglas de quejas", 32: "las Reglas de la Zona Verde", 33: "las Reglas para líderes",
           34: "las Reglas de organizaciones estatales", 35: "las Reglas de la onda estatal", 36: "las Reglas de eventos familiares",
           40: "las Reglas para bandas (OPG)", 41: "las Reglas de la guerra por negocios", 42: "las Reglas de la batalla por la furgoneta"},
    "pt": {30: "das Regras gerais", 31: "das Regras de denúncias", 32: "das Regras da Zona Verde", 33: "das Regras para líderes",
           34: "das Regras das organizações estatais", 35: "das Regras da onda estatal", 36: "das Regras de eventos familiares",
           40: "das Regras para gangues (OPG)", 41: "das Regras da guerra por negócios", 42: "das Regras da batalha pela van"},
}

# короткие названия нарушений для частых пунктов
RULE_TITLES = {
    "2.1": {"ru": "оскорбление игрока или его родных", "kk": "ойыншыны немесе оның туыстарын балағаттау",
            "uz": "o‘yinchini yoki uning yaqinlarini haqorat qilish", "en": "insulting a player or their relatives",
            "es": "insultar a un jugador o a sus familiares", "pt": "insultar um jogador ou seus familiares"},
    "2.2": {"ru": "пропаганда запрещённых тем", "kk": "тыйым салынған тақырыптарды насихаттау",
            "uz": "taqiqlangan mavzularni targ‘ib qilish", "en": "promoting prohibited topics",
            "es": "propaganda de temas prohibidos", "pt": "propaganda de temas proibidos"},
    "2.3": {"ru": "реклама", "kk": "жарнама", "uz": "reklama", "en": "advertising", "es": "publicidad", "pt": "publicidade"},
    "2.4": {"ru": "расизм, ксенофобия, оскорбление религии", "kk": "нәсілшілдік, ксенофобия, дінді қорлау",
            "uz": "irqchilik, ksenofobiya, dinni haqorat qilish", "en": "racism, xenophobia, insulting religion",
            "es": "racismo, xenofobia, insultos a la religión", "pt": "racismo, xenofobia, ofensa à religião"},
    "2.6": {"ru": "угрозы и перенос конфликта из игры в реальность", "kk": "қорқыту және ойындағы жанжалды өмірге көшіру",
            "uz": "tahdid va o‘yindagi nizoni real hayotga ko‘chirish", "en": "threats and taking conflicts outside the game",
            "es": "amenazas y llevar conflictos fuera del juego", "pt": "ameaças e levar conflitos para fora do jogo"},
    "3.1": {"ru": "использование репорта не по назначению", "kk": "репортты мақсатсыз пайдалану",
            "uz": "reportdan noto‘g‘ri foydalanish", "en": "misusing the report system",
            "es": "uso indebido de los reportes", "pt": "uso indevido dos reports"},
    "3.2": {"ru": "хамство в адрес администрации", "kk": "әкімшілікке дөрекілік", "uz": "ma’muriyatga qo‘pollik",
            "en": "rudeness towards administrators", "es": "groserías hacia la administración", "pt": "grosseria com a administração"},
    "4.1": {"ru": "мошенничество", "kk": "алаяқтық", "uz": "firibgarlik", "en": "scamming", "es": "estafa", "pt": "golpe"},
    "4.2": {"ru": "вымогательство", "kk": "бопсалау", "uz": "tovlamachilik", "en": "extortion", "es": "extorsión", "pt": "extorsão"},
    "4.4": {"ru": "сделки за реальные деньги", "kk": "нақты ақшаға мәміле жасау", "uz": "real pulga savdo qilish",
            "en": "real-money trading", "es": "comercio con dinero real", "pt": "comércio com dinheiro real"},
    "5.2": {"ru": "стороннее ПО и багоюз", "kk": "бөгде бағдарламалар мен баг пайдалану", "uz": "begona dasturlar va bagdan foydalanish",
            "en": "third-party software or bug abuse", "es": "software de terceros o abuso de bugs",
            "pt": "software de terceiros ou abuso de bugs"},
    "5.3": {"ru": "уход от RP-ситуации", "kk": "RP-жағдайдан қашу", "uz": "RP-vaziyatdan qochish", "en": "leaving an RP situation",
            "es": "abandonar una situación de rol", "pt": "abandonar uma situação de RP"},
    "5.4": {"ru": "убийство или урон у дома", "kk": "үй маңында өлтіру не зақым келтіру", "uz": "uy oldida o‘ldirish yoki zarar yetkazish",
            "en": "killing or damaging players at a house", "es": "matar o dañar en una casa", "pt": "matar ou causar dano em uma casa"},
    "5.6": {"ru": "аморальные отыгровки и домогательства", "kk": "әдепсіз рөлдік әрекеттер мен қудалау",
            "uz": "axloqsiz rol harakatlari va shilqimlik", "en": "immoral roleplay and harassment",
            "es": "rol inmoral y acoso", "pt": "RP imoral e assédio"},
    "1.6": {"ru": "запрещённый никнейм", "kk": "тыйым салынған никнейм", "uz": "taqiqlangan nikneym", "en": "a prohibited nickname",
            "es": "un apodo prohibido", "pt": "um apelido proibido"},
    "GZ 1.1": {"ru": "убийство или урон в Зелёной Зоне", "kk": "Жасыл аймақта өлтіру не зақым келтіру",
               "uz": "Yashil zonada o‘ldirish yoki zarar yetkazish", "en": "killing or damage in the Green Zone",
               "es": "matar o dañar en la Zona Verde", "pt": "matar ou causar dano na Zona Verde"},
    "GZ 1.2": {"ru": "криминальные действия в Зелёной Зоне (верёвки, похищения)", "kk": "Жасыл аймақтағы қылмыстық әрекет (арқан, ұрлау)",
               "uz": "Yashil zonadagi jinoiy harakatlar (arqon, o‘g‘irlash)", "en": "criminal actions in the Green Zone (ropes, kidnapping)",
               "es": "acciones criminales en la Zona Verde", "pt": "ações criminosas na Zona Verde"},
}

# термины RP: в черновике называем нарушение без номера пункта (у раздела нет пунктов)
RP_TERM_TITLES = {
    "DM": {"ru": "DeathMatch (убийство без RP-причины)", "kk": "DeathMatch (RP-себепсіз өлтіру)", "uz": "DeathMatch (RP sababisiz o‘ldirish)",
           "en": "DeathMatch (killing without an RP reason)", "es": "DeathMatch (matar sin motivo de rol)", "pt": "DeathMatch (matar sem motivo de RP)"},
    "DB": {"ru": "DriveBy (убийство из транспорта)", "kk": "DriveBy (көліктен өлтіру)", "uz": "DriveBy (transportdan o‘ldirish)",
           "en": "DriveBy (killing from a vehicle)", "es": "DriveBy (matar desde un vehículo)", "pt": "DriveBy (matar de um veículo)"},
    "SK": {"ru": "SpawnKill (убийство на месте появления)", "kk": "SpawnKill (пайда болған жерде өлтіру)", "uz": "SpawnKill (paydo bo‘lish joyida o‘ldirish)",
           "en": "Spawn Kill", "es": "Spawn Kill", "pt": "Spawn Kill"},
    "TK": {"ru": "TeamKill (убийство своих)", "kk": "TeamKill (өз ұйымындағыларды өлтіру)", "uz": "TeamKill (o‘z tashkilotdoshlarini o‘ldirish)",
           "en": "Team Kill", "es": "Team Kill", "pt": "Team Kill"},
    "RK": {"ru": "RevengeKill (убийство из мести)", "kk": "RevengeKill (кек алу үшін өлтіру)", "uz": "RevengeKill (o‘ch olish uchun o‘ldirish)",
           "en": "Revenge Kill", "es": "Revenge Kill", "pt": "Revenge Kill"},
    "NONRP": {"ru": "NonRP (нарушение RP-режима)", "kk": "NonRP (RP режимін бұзу)", "uz": "NonRP (RP rejimini buzish)",
              "en": "NonRP (breaking roleplay)", "es": "NonRP (romper el rol)", "pt": "NonRP (quebra de RP)"},
}

T = {
    # ---------------- русский ----------------
    "ru": {
        "appeal_reject": "Ваше обжалование рассмотрено: наказание выдано верно, оснований для его снятия нет. Если у вас есть "
                         "видео, которое опровергает нарушение, подайте новую жалобу и приложите его ({cite_req}). Жалоба закрыта.",
        "hello": "Здравствуйте!",
        "cite": "п. {ref} {section}",
        "approve": "По приложенным материалам видно нарушение {cite} ({title}){nick_part}. "
                   "Наказание по правилам: {sanction}. Срок назначит администратор.",
        "approve_nosanction": "По приложенным материалам видно нарушение {cite} ({title}){nick_part}. "
                              "Наказание назначит администратор по правилам проекта.",
        "approve_term": "По приложенным материалам видно нарушение: {term}{nick_part}. "
                        "Наказание по правилам: {sanction}. Срок назначит администратор.",
        "nick_part": ", нарушитель {nick}",
        "need_evidence": "Для проверки нарушения{what} нужна видеозапись, на которой виден момент нарушения и ник игрока ({cite_req}). "
                         "Загрузите видео на YouTube, imgur, Rutube, Яндекс Диск или Google Диск ({cite_platform}) и подайте новую жалобу.",
        "what": " ({title})",
        "no_description": "Жалоба не может быть рассмотрена: в ней нет точного и логичного описания произошедшего ({cite}). "
                          "Опишите, что случилось, где и когда, укажите ник нарушителя и приложите доказательства, затем подайте новую жалобу.",
        "not_complaint": "Раздел жалоб не предназначен для вопросов, общения и технических проблем ({cite}). "
                         "С вопросами обращайтесь в Discord-сервер игры ({discord}) или в техническую поддержку ({support}).",
        "toxic": "Жалоба не может быть рассмотрена: текст содержит оскорбления или ненормативную лексику ({cite}). "
                 "Подайте новую жалобу со спокойным описанием ситуации и доказательствами.",
        "duplicate": "Эта жалоба повторяет ранее поданную, поэтому рассматриваться не будет ({cite}). "
                     "Дождитесь решения по первой жалобе.",
        "appeal": "Ваше обращение по выданному наказанию принято: решение о снятии "
                  "или изменении наказания принимает только старшая администрация. Если ещё не приложили, добавьте скриншот наказания и "
                  "видео, подтверждающее вашу позицию ({cite_req}). Обжаловать наказание можно в течение 48 часов ({cite_time}).",
        "admin_complaint": "Жалоба на действия администратора принята: её проверяет старшая администрация. "
                           "Для рассмотрения нужны доказательства: видео или скриншоты с моментом нарушения ({cite_req}).",
        "report_watch": "Администратор проверит ситуацию и проследит за игроком{pid_part}. Если есть видео нарушения, оформите жалобу в лаунчере.",
        "pid_part": " [{pid}]",
        "report_need_id": "Укажите ID нарушителя и что он нарушает, администратор проследит. Если есть видео, "
                          "оформите жалобу в лаунчере.",
        "report_rp": "Администрация не вмешивается в RP-процесс. Если считаете, что игрок нарушил правила, "
                     "запишите видео и оформите жалобу в лаунчере.",
        "report_appeal": "Если не согласны с наказанием, подайте жалобу в лаунчере в течение 48 часов ({cite_time}) "
                         "и приложите скриншот наказания и видео.",
        "help_vehicle": "Если транспорт застрял или перевернулся, нажмите кнопку эвакуатора на спидометре.",
        "help_generic": "Администратор сейчас постарается вам помочь, оставайтесь на месте.",
        "help_service": "Администрация не выдаёт телепорт, игровую валюту, транспорт и другое имущество ({cite}).",
        "question_unknown": "Ответ на этот вопрос можно узнать у игроков или в Discord-сервере игры ({discord}).",
        "question_tech": "С техническими проблемами и вопросами по покупкам обращайтесь в техническую поддержку: {support}.",
        "question_complaint_howto": "Жалоба подаётся в лаунчере игры: укажите ник нарушителя, опишите ситуацию и приложите видео или скриншоты.",
        "clarify": "Уточните, пожалуйста, ваш вопрос или жалобу: что случилось?",
        "help_ack": "Администратор на связи. Опишите в репорте, что случилось, так помощь придёт быстрее.",
        "event_tp": "Открыт ли телепорт на мероприятие, подтвердит администратор. Следите за объявлениями администрации в чате.",
        "offtopic_flood": "Репорт предназначен для обращений к администрации. За оффтоп и флуд в репорт может последовать мут репорта ({cite}).",
        "account": "Вопросы доступа к аккаунту, взлома и пропажи имущества администрация в игре не решает. Обратитесь в "
                   "техническую поддержку: {support}. Обращение также рассмотрит администратор. Напоминаем: по {cite} "
                   "игрок сам отвечает за сохранность аккаунта и имущества.",
        "payment": "Вопросы оплаты и доната решает техническая поддержка: {support}. Укажите дату, сумму и способ оплаты, "
                   "приложите чек. Обращение также рассмотрит администратор.",
        "threat": "Угрозы и перенос конфликта за пределы игры запрещены ({cite}). Обращение рассмотрит старшая администрация. "
                  "Если угроза касается вашей безопасности в реальной жизни, обратитесь в полицию.",
        "bye": "",
    },
    # ---------------- казахский ----------------
    "kk": {
        "appeal_reject": "Жазаға берген шағымыңыз қаралды: жаза дұрыс берілген, оны алып тастауға негіз жоқ. Бұзушылықты "
                         "жоққа шығаратын бейнежазбаңыз болса, оны тіркеп, жаңа шағым беріңіз ({cite_req}). Шағым жабылды.",
        "hello": "Сәлеметсіз бе!",
        "cite": "{section} {ref}-тармағы",
        "approve": "Тіркелген материалдардан {cite_gen} бұзылғаны көрінеді ({title}){nick_part}. "
                   "Ереже бойынша жаза: {sanction}. Нақты мерзімді әкімші белгілейді.",
        "approve_nosanction": "Тіркелген материалдардан {cite_gen} бұзылғаны көрінеді ({title}){nick_part}. "
                              "Жазаны әкімші жоба ережелеріне сәйкес белгілейді.",
        "approve_term": "Тіркелген материалдардан бұзушылық көрінеді: {term}{nick_part}. "
                        "Ереже бойынша жаза: {sanction}. Нақты мерзімді әкімші белгілейді.",
        "nick_part": ", бұзушы: {nick}",
        "need_evidence": "Бұзушылықты{what} тексеру үшін бейнежазба қажет: онда бұзушылық сәті мен ойыншының никі көрінуі керек ({cite_req}). "
                         "Бейнені YouTube, imgur, Rutube, Яндекс Диск немесе Google Диск арқылы жүктеп ({cite_platform}), жаңа шағым беріңіз.",
        "what": " ({title})",
        "no_description": "Шағым қаралмайды: онда не болғаны нақты әрі түсінікті жазылмаған ({cite}). "
                          "Не болғанын, қай жерде және қашан болғанын жазып, бұзушының никін көрсетіңіз, дәлелдерді тіркеп, жаңа шағым беріңіз.",
        "not_complaint": "Шағым бөлімі сұрақтарға, әңгімеге және техникалық мәселелерге арналмаған ({cite}). "
                         "Сұрақтарыңызды ойынның Discord-серверіне ({discord}) немесе техникалық қолдау қызметіне ({support}) жазыңыз.",
        "toxic": "Шағым қаралмайды: мәтінде балағат не дөрекі сөздер бар ({cite}). "
                 "Жағдайды сабырлы түрде сипаттап, дәлелдерді тіркеп, жаңа шағым беріңіз.",
        "duplicate": "Бұл шағым бұрын берілген шағымды қайталайды, сондықтан қаралмайды ({cite}). "
                     "Алғашқы шағымыңыз бойынша шешімді күтіңіз.",
        "appeal": "Жазаға қатысты өтінішіңіз қабылданды: жазаны алып тастау немесе өзгерту "
                  "туралы шешімді тек аға әкімшілік қабылдайды. Әлі тіркемеген болсаңыз, жаза туралы скриншотты және өз ұстанымыңызды "
                  "растайтын бейнежазбаны қосыңыз ({cite_req}). Жазаға 48 сағат ішінде шағымдануға болады ({cite_time}).",
        "admin_complaint": "Әкімшінің әрекетіне берілген шағым қабылданды: оны аға әкімшілік тексереді. "
                           "Қарау үшін дәлел қажет: бұзушылық сәті көрінетін бейне немесе скриншот ({cite_req}).",
        "report_watch": "Әкімші жағдайды тексеріп, ойыншыны{pid_part} бақылайды. Бұзушылықтың бейнежазбасы болса, лаунчер арқылы шағым беріңіз.",
        "pid_part": " [{pid}]",
        "report_need_id": "Бұзушының ID нөмірін және не бұзып жатқанын жазыңыз, әкімші бақылайды. Бейнежазба болса, "
                          "лаунчер арқылы шағым беріңіз.",
        "report_rp": "Әкімшілік RP-процеске араласпайды. Ойыншы ережені бұзды деп ойласаңыз, бейнеге түсіріп, "
                     "лаунчер арқылы шағым беріңіз.",
        "report_appeal": "Жазамен келіспесеңіз, 48 сағат ішінде лаунчер арқылы шағым беріңіз ({cite_time}) және жаза "
                         "скриншоты мен бейнежазбаны тіркеңіз.",
        "help_vehicle": "Көлігіңіз тұрып қалса немесе аударылып қалса, спидометрдегі эвакуатор түймесін басыңыз.",
        "help_generic": "Әкімші қазір көмектесуге тырысады, орныңыздан кетпеңіз.",
        "help_service": "Әкімшілік телепорт, ойын ақшасын, көлік және басқа мүлік бермейді ({cite}).",
        "question_unknown": "Бұл сұрақтың жауабын ойыншылардан немесе ойынның Discord-серверінен ({discord}) білуге болады.",
        "question_tech": "Техникалық мәселелер мен сатып алу сұрақтары бойынша техникалық қолдау қызметіне жазыңыз: {support}.",
        "question_complaint_howto": "Шағым ойын лаунчері арқылы беріледі: бұзушының никін көрсетіп, жағдайды сипаттаңыз және бейне не скриншот тіркеңіз.",
        "clarify": "Сұрағыңызды немесе шағымыңызды нақтылап жазыңызшы: не болды?",
        "help_ack": "Әкімші байланыста. Не болғанын репортқа жазыңыз, сонда көмек тезірек келеді.",
        "event_tp": "Іс-шараға телепорт ашық па, соны әкімші растайды. Чаттағы әкімшілік хабарландыруларын қадағалаңыз.",
        "offtopic_flood": "Репорт әкімшілікке жүгіну үшін арналған. Оффтоп пен флуд үшін репортқа шектеу қойылуы мүмкін ({cite}).",
        "account": "Аккаунтқа кіру, аккаунтты бұзу және мүліктің жоғалуы мәселелерін ойын ішіндегі әкімшілік шешпейді. "
                   "Техникалық қолдау қызметіне жазыңыз: {support}. Өтінішіңізді әкімші де қарайды. Еске саламыз: {cite} бойынша "
                   "аккаунт пен мүліктің қауіпсіздігіне ойыншының өзі жауап береді.",
        "payment": "Төлем мен донат мәселелерін техникалық қолдау қызметі шешеді: {support}. Төлем күнін, сомасын және "
                   "тәсілін жазып, чекті тіркеңіз. Өтінішіңізді әкімші де қарайды.",
        "threat": "Қорқытуға және жанжалды ойыннан тыс жерге көшіруге тыйым салынған ({cite}). Өтінішті аға әкімшілік қарайды. "
                  "Егер қауіп өміріңізге қатысты болса, полицияға жүгініңіз.",
        "bye": "",
    },
    # ---------------- узбекский (латиница, как у админов uz-сервера) ----------------
    "uz": {
        "appeal_reject": "Jazo ustidan shikoyatingiz ko‘rib chiqildi: jazo to‘g‘ri berilgan, uni olib tashlashga asos yo‘q. "
                         "Agar qoidabuzarlikni rad etuvchi videongiz bo‘lsa, uni ilova qilib, yangi shikoyat yuboring ({cite_req}). Shikoyat yopildi.",
        "hello": "Assalomu alaykum!",
        "cite": "{section} {ref}-bandi",
        "approve": "Ilova qilingan materiallarda {cite} buzilgani ko‘rinadi ({title}){nick_part}. "
                   "Qoidalar bo‘yicha jazo: {sanction}. Aniq muddatni administrator belgilaydi.",
        "approve_nosanction": "Ilova qilingan materiallarda {cite} buzilgani ko‘rinadi ({title}){nick_part}. "
                              "Jazoni administrator loyiha qoidalariga muvofiq belgilaydi.",
        "approve_term": "Ilova qilingan materiallarda qoidabuzarlik ko‘rinadi: {term}{nick_part}. "
                        "Qoidalar bo‘yicha jazo: {sanction}. Aniq muddatni administrator belgilaydi.",
        "nick_part": ", qoidabuzar: {nick}",
        "need_evidence": "Qoidabuzarlikni{what} tekshirish uchun video dalil (videofiksatsiya) zarur: videoda qoidabuzarlik lahzasi va "
                         "o‘yinchining niki ko‘rinishi kerak ({cite_req}). "
                         "Videoni YouTube, imgur, Rutube, Yandex Disk yoki Google Disk orqali yuklang ({cite_platform}) va yangi shikoyat yuboring.",
        "what": " ({title})",
        "no_description": "Shikoyat ko‘rib chiqilmaydi: unda nima sodir bo‘lgani aniq va mantiqiy bayon qilinmagan ({cite}). "
                          "Nima bo‘lganini, qayerda va qachon bo‘lganini yozing, qoidabuzarning nikini ko‘rsating, dalillarni ilova qilib, yangi shikoyat yuboring.",
        "not_complaint": "Shikoyatlar bo‘limi savollar, suhbat va texnik muammolar uchun mo‘ljallanmagan ({cite}). "
                         "Savollaringiz bilan o‘yinning Discord serveriga ({discord}) yoki texnik yordamga ({support}) murojaat qiling.",
        "toxic": "Shikoyat ko‘rib chiqilmaydi: matnda haqorat yoki so‘kinish bor ({cite}). "
                 "Vaziyatni xotirjam tasvirlab, dalillar bilan yangi shikoyat yuboring.",
        "duplicate": "Ushbu shikoyat avval yuborilgan shikoyatning takrori, shu sababli ko‘rib chiqilmaydi ({cite}). "
                     "Birinchi shikoyatingiz bo‘yicha qarorni kuting.",
        "appeal": "Jazo bo‘yicha murojaatingiz qabul qilindi: jazoni olib tashlash yoki o‘zgartirish "
                  "to‘g‘risidagi qarorni faqat katta ma’muriyat qabul qiladi. Agar hali ilova qilmagan bo‘lsangiz, jazo skrinshotini va "
                  "pozitsiyangizni tasdiqlovchi videoni qo‘shing ({cite_req}). Jazo ustidan 48 soat ichida shikoyat qilish mumkin ({cite_time}).",
        "admin_complaint": "Administrator harakatlari ustidan shikoyat qabul qilindi: uni katta ma’muriyat tekshiradi. "
                           "Ko‘rib chiqish uchun dalil kerak: qoidabuzarlik lahzasi ko‘rinadigan video yoki skrinshot ({cite_req}).",
        "report_watch": "Administrator vaziyatni tekshirib, o‘yinchini{pid_part} kuzatadi. Agar qoidabuzarlik videosi bo‘lsa, launcher orqali shikoyat yozing.",
        "pid_part": " [{pid}]",
        "report_need_id": "Qoidabuzarning ID raqamini va nimani buzayotganini yozing, administrator kuzatadi. Video bo‘lsa, "
                          "launcher orqali shikoyat yozing.",
        "report_rp": "Ma’muriyat RP jarayoniga aralashmaydi. Agar o‘yinchi qoidani buzgan deb hisoblasangiz, videoga oling va "
                     "launcher orqali shikoyat yozing.",
        "report_appeal": "Agar jazoga rozi bo‘lmasangiz, 48 soat ichida launcher orqali shikoyat yozing ({cite_time}) va jazo "
                         "skrinshoti hamda videoni ilova qiling.",
        "help_vehicle": "Agar mashinangiz qotib qolgan yoki ag‘darilgan bo‘lsa, spidometrdagi evakuator tugmasini bosing.",
        "help_generic": "Administrator hozir yordam berishga harakat qiladi, iltimos, joyingizdan ketmang.",
        "help_service": "Ma’muriyat teleport, o‘yin puli, transport va boshqa mol-mulk bermaydi ({cite}).",
        "question_unknown": "Bu savolga javobni o‘yinchilardan yoki o‘yinning Discord serveridan ({discord}) bilishingiz mumkin.",
        "question_tech": "Texnik muammolar va xaridlar bo‘yicha texnik yordamga murojaat qiling: {support}.",
        "question_complaint_howto": "Shikoyat o‘yin launcheri orqali yoziladi: qoidabuzarning nikini ko‘rsating, vaziyatni tasvirlang va video yoki skrinshot ilova qiling.",
        "clarify": "Iltimos, savolingiz yoki shikoyatingizni aniqroq yozing: nima bo‘ldi?",
        "help_ack": "Administrator aloqada. Nima bo‘lganini reportga yozing, shunda yordam tezroq keladi.",
        "event_tp": "Tadbirga teleport ochiqligini administrator tasdiqlaydi. Chatdagi ma’muriyat e’lonlarini kuzatib boring.",
        "offtopic_flood": "Report ma’muriyatga murojaat qilish uchun mo‘ljallangan. Reportda offtop va flud uchun reportga cheklov qo‘yilishi mumkin ({cite}).",
        "account": "Akkauntga kirish, akkauntni buzib kirish va mol-mulk yo‘qolishi masalalarini o‘yin ichidagi ma’muriyat hal qilmaydi. "
                   "Texnik yordamga yozing: {support}. Murojaatingizni administrator ham ko‘rib chiqadi. Eslatma: {cite}ga ko‘ra "
                   "akkaunt va mol-mulk xavfsizligi uchun o‘yinchining o‘zi javobgar.",
        "payment": "To‘lov va donat masalalarini texnik yordam xizmati hal qiladi: {support}. To‘lov sanasi, summasi va usulini "
                   "yozing, chekni ilova qiling. Murojaatingizni administrator ham ko‘rib chiqadi.",
        "threat": "Tahdid qilish va nizoni o‘yindan tashqariga olib chiqish taqiqlangan ({cite}). Murojaatni katta ma’muriyat ko‘rib chiqadi. "
                  "Agar tahdid real hayotdagi xavfsizligingizga tegishli bo‘lsa, politsiyaga murojaat qiling.",
        "bye": "",
    },
    # ---------------- английский ----------------
    "en": {
        "appeal_reject": "Your appeal has been reviewed: the penalty was issued correctly and there are no grounds to lift it. "
                         "If you have a video that disproves the violation, submit a new complaint with it ({cite_req}). The complaint is closed.",
        "hello": "Hello!",
        "cite": "rule {ref} of the {section}",
        "approve": "Your complaint has been reviewed. The attached materials show a violation of {cite} ({title}){nick_part}. "
                   "Penalty under the rules: {sanction}. The exact term is set by the administrator. Thank you! The complaint is closed.",
        "approve_nosanction": "Your complaint has been reviewed. The attached materials show a violation of {cite} ({title}){nick_part}. "
                              "The administrator will set the penalty according to the rules. Thank you! The complaint is closed.",
        "approve_term": "Your complaint has been reviewed. The attached materials show a violation: {term}{nick_part}. "
                        "Penalty under the rules: {sanction}. The exact term is set by the administrator. Thank you! The complaint is closed.",
        "nick_part": " by {nick}",
        "need_evidence": "Thank you for the complaint. To check the violation{what} we need a video showing the moment of the violation and "
                         "the player's nickname, since a complaint must contain full evidence ({cite_req}). Upload the video to YouTube, "
                         "imgur, Rutube, Yandex Disk or Google Drive ({cite_platform}) and submit a new complaint.",
        "what": " ({title})",
        "no_description": "The complaint cannot be reviewed because it has no clear description of what happened ({cite}). "
                          "Describe what happened, where and when, give the offender's nickname, attach evidence and submit a new complaint.",
        "not_complaint": "The complaints section is not for questions, chatting or technical problems ({cite}). "
                         "Please ask in the game's Discord server ({discord}) or contact technical support ({support}).",
        "toxic": "The complaint cannot be reviewed because the text contains insults or profanity ({cite}). "
                 "Please submit a new complaint with a calm description and evidence.",
        "duplicate": "This complaint repeats one you already submitted, so it will not be reviewed ({cite}). Please wait for the decision on the first one.",
        "appeal": "Your appeal has been received: only senior administration can lift or change a penalty. "
                  "If you have not done so yet, add a screenshot of the penalty and a video supporting your position ({cite_req}). "
                  "Penalties can be appealed within 48 hours ({cite_time}).",
        "admin_complaint": "Your complaint about an administrator has been received: senior administration will review it. "
                           "Evidence is required: a video or screenshots showing the violation ({cite_req}).",
        "report_watch": "An administrator will look into this and watch the player{pid_part}. If you have a video of the "
                        "violation, file a complaint in the launcher so the offender can be penalized.",
        "pid_part": " [{pid}]",
        "report_need_id": "Please give the offender's ID and what they are doing, and an administrator will watch. If you have a video, file a complaint in the launcher.",
        "report_rp": "Administrators do not interfere in roleplay. If you think a player broke the rules, record a video and file a complaint in the launcher.",
        "report_appeal": "If you disagree with a penalty, file a complaint in the launcher within 48 hours ({cite_time}) with a screenshot of the penalty and a video.",
        "help_vehicle": "If your vehicle is stuck or flipped, press the tow truck button on the speedometer.",
        "help_generic": "An administrator will try to help you now, please stay where you are.",
        "help_service": "Administrators do not provide teleports, in-game money, vehicles or other property ({cite}).",
        "question_unknown": "You can ask other players or the game's Discord server ({discord}) about this.",
        "question_tech": "For technical problems and purchases, please contact technical support: {support}.",
        "question_complaint_howto": "Complaints are filed in the game launcher: give the offender's nickname, describe the situation and attach a video or screenshots.",
        "clarify": "Please clarify your question or complaint: what happened?",
        "help_ack": "An administrator is on it and will take a look. Describe what happened in the report so we can help faster.",
        "event_tp": "An administrator will confirm whether teleport to the event is open. Watch for administrator announcements in chat.",
        "offtopic_flood": "Reports are for contacting administrators. Off-topic messages and flooding may lead to a report mute ({cite}).",
        "account": "Account access, hacking and lost property cannot be resolved by in-game administrators. Please contact technical "
                   "support: {support}. An administrator will also review your request. Note: under {cite}, players are "
                   "responsible for the security of their account and property.",
        "payment": "Payment and donation issues are handled by technical support: {support}. Include the date, amount and payment "
                   "method and attach the receipt. An administrator will also review your request.",
        "threat": "Threats and taking conflicts outside the game are prohibited ({cite}). Senior "
                  "administration will review your report. If the threat concerns your safety in real life, contact the police.",
        "bye": "",
    },
    # ---------------- испанский ----------------
    "es": {
        "appeal_reject": "Tu apelación ha sido revisada: la sanción se aplicó correctamente y no hay motivos para retirarla. "
                         "Si tienes un video que demuestre lo contrario, envía una nueva queja con él ({cite_req}). La queja está cerrada.",
        "hello": "¡Hola!",
        "cite": "punto {ref} de {section}",
        "approve": "Tu queja ha sido revisada. Los materiales adjuntos muestran una infracción del {cite} ({title}){nick_part}. "
                   "Sanción según las reglas: {sanction}. El plazo exacto lo fija el administrador. ¡Gracias! La queja está cerrada.",
        "approve_nosanction": "Tu queja ha sido revisada. Los materiales adjuntos muestran una infracción del {cite} ({title}){nick_part}. "
                              "El administrador fijará la sanción según las reglas. ¡Gracias! La queja está cerrada.",
        "approve_term": "Tu queja ha sido revisada. Los materiales adjuntos muestran una infracción: {term}{nick_part}. "
                        "Sanción según las reglas: {sanction}. El plazo exacto lo fija el administrador. ¡Gracias! La queja está cerrada.",
        "nick_part": " por parte de {nick}",
        "need_evidence": "Gracias por la queja. Para comprobar la infracción{what} necesitamos un video con el momento de la infracción y el "
                         "apodo del jugador, ya que la queja debe incluir pruebas completas ({cite_req}). Sube el video a YouTube, imgur, "
                         "Rutube, Yandex Disk o Google Drive ({cite_platform}) y envía una nueva queja.",
        "what": " ({title})",
        "no_description": "La queja no puede revisarse porque no describe con claridad lo ocurrido ({cite}). Explica qué pasó, dónde "
                          "y cuándo, indica el apodo del infractor, adjunta pruebas y envía una nueva queja.",
        "not_complaint": "La sección de quejas no es para preguntas, conversaciones ni problemas técnicos ({cite}). "
                         "Pregunta en el servidor de Discord del juego ({discord}) o escribe al soporte técnico ({support}).",
        "toxic": "La queja no puede revisarse porque el texto contiene insultos o groserías ({cite}). Envía una nueva queja con una descripción tranquila y pruebas.",
        "duplicate": "Esta queja repite una anterior, por lo que no se revisará ({cite}). Espera la decisión sobre la primera.",
        "appeal": "Tu apelación ha sido recibida: solo la administración superior puede retirar o cambiar una sanción. "
                  "Si aún no lo hiciste, adjunta una captura de la sanción y un video que respalde tu postura ({cite_req}). "
                  "Las sanciones se pueden apelar en un plazo de 48 horas ({cite_time}).",
        "admin_complaint": "Tu queja sobre un administrador ha sido recibida: la revisará la administración superior. Se necesitan pruebas: video o capturas ({cite_req}).",
        "report_watch": "Un administrador revisará la situación y vigilará al jugador{pid_part}. Si tienes un video de la infracción, "
                        "presenta una queja en el launcher para que el infractor pueda ser sancionado.",
        "pid_part": " [{pid}]",
        "report_need_id": "Indica el ID del infractor y qué está haciendo, y un administrador lo vigilará. Si tienes video, presenta una queja en el launcher.",
        "report_rp": "La administración no interviene en el rol. Si crees que un jugador rompió las reglas, graba un video y presenta una queja en el launcher.",
        "report_appeal": "Si no estás de acuerdo con una sanción, presenta una queja en el launcher en 48 horas ({cite_time}) con una captura y un video.",
        "help_vehicle": "Si tu vehículo está atascado o volcado, pulsa el botón de grúa en el velocímetro.",
        "help_generic": "Un administrador intentará ayudarte ahora, quédate donde estás.",
        "help_service": "La administración no da teletransportes, dinero del juego, vehículos ni otros bienes ({cite}).",
        "question_unknown": "Puedes preguntar a otros jugadores o en el servidor de Discord del juego ({discord}).",
        "question_tech": "Para problemas técnicos y compras, escribe al soporte técnico: {support}.",
        "question_complaint_howto": "Las quejas se presentan en el launcher del juego: indica el apodo del infractor, describe la situación y adjunta video o capturas.",
        "clarify": "Por favor, aclara tu pregunta o queja: ¿qué pasó?",
        "help_ack": "Un administrador está atento y lo revisará. Describe en el reporte qué pasó para ayudarte más rápido.",
        "event_tp": "Un administrador confirmará si el teletransporte al evento está abierto. Atento a los anuncios de la administración en el chat.",
        "offtopic_flood": "Los reportes son para contactar con la administración. El offtopic y el flood pueden llevar a un silencio de reportes ({cite}).",
        "account": "Los problemas de acceso a la cuenta, hackeo y pérdida de bienes no los resuelve la administración del juego. Escribe al "
                   "soporte técnico: {support}. Un administrador también revisará tu solicitud. Según el {cite}, cada jugador es "
                   "responsable de la seguridad de su cuenta y sus bienes.",
        "payment": "Los pagos y donaciones los gestiona el soporte técnico: {support}. Indica fecha, importe y método de pago y adjunta "
                   "el recibo. Un administrador también revisará tu solicitud.",
        "threat": "Las amenazas y llevar conflictos fuera del juego están prohibidos ({cite}). La administración superior revisará el caso. "
                  "Si la amenaza afecta a tu seguridad real, contacta a la policía.",
        "bye": "",
    },
    # ---------------- португальский ----------------
    "pt": {
        "appeal_reject": "Seu recurso foi analisado: a punição foi aplicada corretamente e não há motivos para retirá-la. "
                         "Se você tem um vídeo que prove o contrário, faça uma nova denúncia com ele ({cite_req}). A denúncia está encerrada.",
        "hello": "Olá!",
        "cite": "item {ref} {section}",
        "approve": "Sua denúncia foi analisada. Os materiais anexados mostram uma violação do {cite} ({title}){nick_part}. "
                   "Punição pelas regras: {sanction}. O prazo exato é definido pelo administrador. Obrigado! A denúncia está encerrada.",
        "approve_nosanction": "Sua denúncia foi analisada. Os materiais anexados mostram uma violação do {cite} ({title}){nick_part}. "
                              "O administrador definirá a punição conforme as regras. Obrigado! A denúncia está encerrada.",
        "approve_term": "Sua denúncia foi analisada. Os materiais anexados mostram uma violação: {term}{nick_part}. "
                        "Punição pelas regras: {sanction}. O prazo exato é definido pelo administrador. Obrigado! A denúncia está encerrada.",
        "nick_part": " por {nick}",
        "need_evidence": "Obrigado pela denúncia. Para verificar a violação{what} precisamos de um vídeo com o momento da violação e o apelido "
                         "do jogador, pois a denúncia deve conter provas completas ({cite_req}). Envie o vídeo ao YouTube, imgur, Rutube, "
                         "Yandex Disk ou Google Drive ({cite_platform}) e faça uma nova denúncia.",
        "what": " ({title})",
        "no_description": "A denúncia não pode ser analisada porque não descreve com clareza o que aconteceu ({cite}). Explique o que "
                          "aconteceu, onde e quando, informe o apelido do infrator, anexe provas e faça uma nova denúncia.",
        "not_complaint": "A seção de denúncias não é para perguntas, conversas ou problemas técnicos ({cite}). "
                         "Pergunte no servidor do Discord do jogo ({discord}) ou fale com o suporte técnico ({support}).",
        "toxic": "A denúncia não pode ser analisada porque o texto contém insultos ou palavrões ({cite}). Faça uma nova denúncia com uma descrição calma e provas.",
        "duplicate": "Esta denúncia repete uma anterior, por isso não será analisada ({cite}). Aguarde a decisão sobre a primeira.",
        "appeal": "Seu recurso foi recebido: só a administração sênior pode retirar ou alterar uma punição. "
                  "Se ainda não fez isso, anexe uma captura da punição e um vídeo que comprove sua posição ({cite_req}). "
                  "É possível recorrer de uma punição em até 48 horas ({cite_time}).",
        "admin_complaint": "Sua denúncia sobre um administrador foi recebida: a administração sênior vai analisá-la. São necessárias provas: vídeo ou capturas ({cite_req}).",
        "report_watch": "Um administrador vai verificar a situação e observar o jogador{pid_part}. Se tiver um vídeo da violação, faça uma "
                        "denúncia no launcher para que o infrator possa ser punido.",
        "pid_part": " [{pid}]",
        "report_need_id": "Informe o ID do infrator e o que ele está fazendo, e um administrador vai observar. Se tiver vídeo, faça uma denúncia no launcher.",
        "report_rp": "A administração não interfere no RP. Se acha que um jogador quebrou as regras, grave um vídeo e faça uma denúncia no launcher.",
        "report_appeal": "Se não concorda com uma punição, faça uma denúncia no launcher em até 48 horas ({cite_time}) com uma captura e um vídeo.",
        "help_vehicle": "Se o seu veículo ficou preso ou capotou, aperte o botão de guincho no velocímetro.",
        "help_generic": "Um administrador vai tentar ajudar agora, fique onde está.",
        "help_service": "A administração não fornece teleporte, dinheiro do jogo, veículos ou outros bens ({cite}).",
        "question_unknown": "Você pode perguntar a outros jogadores ou no servidor do Discord do jogo ({discord}).",
        "question_tech": "Para problemas técnicos e compras, fale com o suporte técnico: {support}.",
        "question_complaint_howto": "As denúncias são feitas no launcher do jogo: informe o apelido do infrator, descreva a situação e anexe vídeo ou capturas.",
        "clarify": "Por favor, explique melhor sua pergunta ou denúncia: o que aconteceu?",
        "help_ack": "Um administrador está acompanhando e vai verificar. Descreva no report o que aconteceu para ajudarmos mais rápido.",
        "event_tp": "Um administrador confirmará se o teleporte para o evento está aberto. Acompanhe os anúncios da administração no chat.",
        "offtopic_flood": "Os reports servem para falar com a administração. Offtopic e flood podem levar a um silenciamento de reports ({cite}).",
        "account": "Problemas de acesso à conta, invasão e perda de bens não são resolvidos pela administração do jogo. Fale com o suporte "
                   "técnico: {support}. Um administrador também vai analisar seu pedido. Pelo {cite}, cada jogador é "
                   "responsável pela segurança da própria conta e dos bens.",
        "payment": "Pagamentos e doações são tratados pelo suporte técnico: {support}. Informe data, valor e forma de pagamento e anexe "
                   "o comprovante. Um administrador também vai analisar seu pedido.",
        "threat": "Ameaças e levar conflitos para fora do jogo são proibidos ({cite}). A administração sênior vai analisar o caso. "
                  "Se a ameaça envolve sua segurança real, procure a polícia.",
        "bye": "",
    },
}
