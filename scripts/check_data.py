"""Проверка данных кейса и моделей: что на месте, что нет, пригодна ли структура.

    python scripts/check_data.py            # смотрит data/ и models/ (или COPILOT_DATA и COPILOT_MODELS)
    python scripts/check_data.py --json     # то же в JSON

Скрипт ничего не создаёт и не подменяет. Код возврата 0, если есть всё обязательное для работы триажа
(rules.json пригоден), и 1, если нет. Отсутствие моделей и выгрузок не ошибка, но выводится списком.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from copilot import datacheck  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    data = Path(os.environ.get("COPILOT_DATA", ROOT / "data"))
    models = Path(os.environ.get("COPILOT_MODELS", ROOT / "models"))
    rep = datacheck.full_report(data, models)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"data:   {data}\nmodels: {models}\n")
        for f in rep["files"]:
            mark = "есть" if f["present"] else "НЕТ "
            size = f" ({f['size']:,} байт)".replace(",", " ") if f["size"] else ""
            print(f"  [{mark}] {f['path']:<28} {f['role']:<13} {f['purpose']}{size}")
        for key, label in (("train", "tickets_train.jsonl.gz"), ("valid", "tickets_valid.jsonl")):
            t = rep[key]
            if t.get("present"):
                print(f"\n{label}: проверено {t['checked']} строк, целых {t['ok']}, битых {t['bad']}")
                for e in t["errors"]:
                    print("   ", e)
        if rep["rules_problems"]:
            print("\nrules.json непригоден:")
            for p in rep["rules_problems"]:
                print("  -", p)
        if rep["missing"]:
            print("\nНе хватает файлов (данные кейса приватные, в репозиторий не входят):")
            for m in rep["missing"]:
                print("  -", m)
        else:
            print("\nВсе файлы на месте.")
    return 0 if not rep["rules_problems"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
