"""Выгрузка парных слепых примеров для человеческой проверки (реальные тикеты, только локально).

Сторона X/Y перемешана заранее и записана в отдельный файл-ключ: оценщик его не видит. Выборка стратифицирована по языку:
все kk, до 20 uz, до 36 ru. Файлы кладутся в reports/private/final_quality (в .gitignore): в них тексты игроков.
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

QUOTA = {"kk": 99, "uz": 20, "ru": 36}


def main():
    pairs = [json.loads(l) for l in (C.PRIVATE / "blind_pairs_real.jsonl").read_text(encoding="utf-8").splitlines() if l]
    rnd = random.Random(C.SEED + 5)
    pick = []
    for lg, q in QUOTA.items():
        pool = [p for p in pairs if p["lang"] == lg]
        pick += rnd.sample(pool, min(q, len(pool)))
    rnd.shuffle(pick)
    path = C.PRIVATE / "human_review_pairs.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pair_id", "language", "player_text", "reply_X", "reply_Y",
                    "answers_the_request_X(1-5)", "answers_the_request_Y(1-5)", "complete_X(1-5)", "complete_Y(1-5)",
                    "natural_X(1-5)", "natural_Y(1-5)", "language_correct_X(yes/no)", "language_correct_Y(yes/no)",
                    "invented_facts_X(yes/no)", "invented_facts_Y(yes/no)", "forbidden_promise_X(yes/no)",
                    "forbidden_promise_Y(yes/no)", "preferred(X/Y/tie)", "comment"])
        for p in pick:
            w.writerow([p["pair_id"], p["lang"], p["player_text"], p["reply_X"], p["reply_Y"]] + [""] * 14)
    (C.PRIVATE / "HUMAN_REVIEW_README.md").write_text(
        "# Парная слепая проверка черновиков\n\n"
        "Файл `human_review_pairs.csv`: для каждого обращения два черновика X и Y, какая система написала какой, оценщик не знает.\n"
        "Ключ лежит отдельно (`blind_pairs_real.KEY.json`), открывать его до окончания оценки нельзя.\n\n"
        "Критерии: ответ по существу запроса; полнота (есть всё, что нужно по ситуации); естественность речи на языке игрока; "
        "правильный язык и алфавит (узбекский латиницей); выдуманные факты (пункты, сроки, ники, организации, наказания); "
        "запрещённые обещания (разбан, возврат, компенсация, гарантированное наказание).\n\n"
        "Казахские и узбекские пары должен оценивать носитель языка. Оценка LLM или регулярными выражениями не заменяет её.\n",
        encoding="utf-8")
    print(f"{len(pick)} пар -> {path}; по языкам:", {lg: sum(p['lang'] == lg for p in pick) for lg in QUOTA})


if __name__ == "__main__":
    main()
