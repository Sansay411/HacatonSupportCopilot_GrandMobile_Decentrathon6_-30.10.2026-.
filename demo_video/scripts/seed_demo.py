"""Синтетические обращения для демо-базы. Тексты придуманы для этого видео, к данным кейса отношения не имеют.

Каждое обращение создаётся тем же вызовом POST /tickets, что и кнопка «Новое обращение»: пайплайн разбирает его по-настоящему,
результат ни в одном поле не задан заранее. Скрипт только печатает, что получилось.

    python demo_video/scripts/seed_demo.py [base_url]
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:8765"

SEEDS = [
    dict(kind="complaint", text="Test_Aim наводится через стены и убивает с первого выстрела, записал видео, ссылка ниже",
         reported_nick="Test_Aim", reporter="p-2001", attachments=1, evidence_urls=["https://youtu.be/demo-clip-001"]),
    dict(kind="complaint", text="Demo_Driver сбил меня на машине возле банка без причины, это второй раз за вечер, скриншот приложил",
         reported_nick="Demo_Driver", reporter="p-2002", attachments=1, server="3"),
    dict(kind="complaint", text="Sample_Trader взял деньги за дом и не передал ключи, сделка была в чате, прошу проверить",
         reported_nick="Sample_Trader", reporter="p-2003", attachments=2),
    dict(kind="complaint", text="Администратор Admin_Test выдал мне наказание без объяснений и не ответил на вопрос в чате",
         reporter="p-2004"),
    dict(kind="complaint", text="Не согласен с блокировкой аккаунта, прошу пересмотреть, нарушение я не совершал",
         reporter="p-2005"),
    dict(kind="report", text="Как сменить ник персонажа и где посмотреть правила сервера?", reporter="p-2006"),
    dict(kind="report", text="Кто-то зашёл в мой аккаунт, пароль я не менял, из инвентаря пропали вещи, нужна помощь",
         reporter="p-2007"),
    dict(kind="report", text="Застрял в текстурах возле порта, персонаж не двигается, помогите", reporter="p-2008"),
    dict(kind="complaint", text="User_Loud оскорблял меня в голосовом чате, запись у меня есть", reported_nick="User_Loud",
         reporter="p-2009", attachments=1),
    dict(kind="report", text="ааа ааа ааа ааа ааа ааа ааа ааа ааа ааа ааа ааа ааа ааа", reporter="p-2010"),
    dict(kind="complaint", text="Fake_Seller рекламирует продажу игровой валюты за реальные деньги в общем чате, скриншот есть",
         reported_nick="Fake_Seller", reporter="p-2011", attachments=1),
    dict(kind="report", text="Оплатил покупку, деньги списались, но ничего не получил. Прошу проверить платёж", reporter="p-3104"),
    dict(kind="complaint", text="Test_Cheat softdan foydalanyapti, uchib yuribdi, 5.2 OP", reported_nick="Test_Cheat",
         reporter="p-2012", server_lang="uz"),
]


def post(base: str, body: dict) -> dict:
    req = urllib.request.Request(base + "/tickets", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))["ticket"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code}: {e.read().decode('utf-8')[:300]}")


def seed(base: str = BASE) -> list[dict]:
    out = []
    for body in SEEDS:
        t = post(base, body)
        out.append({"id": t["id"], "kind": t["kind"], "category": t["category"], "priority": t["priority"],
                    "needs_human": t["needs_human"], "dup": bool(t.get("is_duplicate")), "spam": bool(t.get("is_spam"))})
    return out


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else BASE
    for row in seed(base):
        print(row)
