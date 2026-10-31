"""Общие функции аудита черновиков: загрузка valid, прогон Copilot, независимый список дефектов.

Список дефектов ниже не импортирует copilot.guard и copilot.verify: аудит должен находить то, что пропускают
действующие проверки. Тексты игроков остаются в reports/private/ (в .gitignore); наружу идут только агрегаты.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRIVATE = ROOT / "reports" / "private" / "draft_audit"
PUBLIC = ROOT / "reports" / "draft_audit"


def load_valid(path: Path | None = None) -> list[dict]:
    path = path or ROOT / "data" / "tickets_valid.jsonl"
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def player_payload(row: dict) -> dict:
    """Вход по контракту POST /triage: ответы админов вырезаны (это то, что мы предсказываем)."""
    p = dict(row)
    p["messages"] = [m for m in (row.get("messages") or []) if isinstance(m, dict) and m.get("role") != "admin"]
    return p


def run(rows: list[dict], cp=None, *, use_dedup: bool = True) -> list[dict]:
    """Прогон в порядке created_at, как в scripts/predict.py (дедупликация «за час»); результат в исходном порядке."""
    from copilot.pipeline import Copilot

    cp = cp or Copilot()
    order = sorted(range(len(rows)), key=lambda i: (rows[i].get("created_at") or "", i))
    out: dict[int, dict] = {}
    for i in order:
        out[i] = cp.triage(player_payload(rows[i]), use_dedup=use_dedup)
    return [out[i] for i in range(len(rows))]


def player_text(row: dict) -> str:
    return "\n".join((m.get("text") or "") for m in (row.get("messages") or []) if m.get("role", "player") == "player")


def dump(path: Path, objs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for o in objs:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------------------------------------------
# Независимые детекторы дефектов текста черновика. Каждый возвращает код дефекта или None.

# обещание результата, которого сервис не вправе давать (разбан, возврат, компенсация, гарантированное наказание)
PROMISE = re.compile("|".join([
    r"(будет|будут|будете)\s+(снят|снято|сняты|разбанен|разблокирован|возвращ[её]н|восстановлен|наказан|забанен)",
    r"\b(вернём|вернем|возместим|компенсируем|разбаним|снимем|восстановим|накажем|забаним|выдадим|начислим)\b",
    r"\b(бан|мут|варн|наказани\w*|блокировк\w*|деморган)\s+(уже\s+|был\s+|будет\s+)?(снят\w*|отмен[её]н\w*|аннулирован\w*)",
    r"гарантиру\w+|гарантия\b|обязательно\s+(разбан|вернем|вернём|снимем|накаж)",
    r"\b(деньги|средства|донат\w*|имущество|аккаунт\w*)\s+(будут\s+|были\s+|уже\s+)?(возвращ[её]н\w*|вернут\w*|восстановлен\w*)",
    r"қайтарамыз|алып тастаймыз|қалпына келтіреміз|жазалаймыз",
    r"qaytaramiz|olib tashlaymiz|tiklaymiz|bandan chiqaramiz|jazolaymiz|jazolanadi",
    r"\bwe(?:'ll| will) (unban|refund|restore|return|lift|ban|punish)\b|\bwill be (unbanned|refunded|restored|lifted|banned|punished)\b",
]), re.I)

# утверждения о том, что обращение «передано» кому-то; настоящего канала передачи в продукте нет
HANDOFF = re.compile(
    r"передан[оаы]?\s+(администратор|старшей|ответственн)|передал\s+администратор|"
    r"передано\s+(администратор|старшей)|ma’?muriyatga yuborildi|administratorga (ham )?yetkazildi|"
    r"администратору\b.{0,20}\bпередан|әкімшіге (де )?берілді|аға әкімшілікке (жіберілді|берілді)|"
    r"passed (this )?to (an )?(administrator|senior)|encaminhad[oa]|pasó a la administración|avisado a un administrador|"
    r"хабарламаңызды әкімшіге бердім|Murojaatingiz administratorga yetkazildi", re.I)

# срок/наказание названы жёстко, а не «по правилам»
HARD_SANCTION = re.compile(r"будет\s+(выдан|назначен)|наказание:\s*(бан|мут)|вы получите|получит бан", re.I)

# закрытие дела от имени сервиса
CLOSED = re.compile(r"жалоба закрыта|шағым жабылды|shikoyat yopildi|complaint is closed|queja está cerrada|denúncia está encerrada", re.I)
