"""Что нужно сервису из данных кейса и в каком состоянии это лежит на диске.

Функции ничего не создают и не подменяют: они проверяют наличие файлов, структуру ``rules.json`` и разбор первых строк
выгрузок. Результат показывается в интерфейсе и в ``scripts/check_data.py``.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

# (путь относительно data/ или models/, роль, для чего нужен)
DATA_FILES = [
    ("data", "rules.json", "обязательный", "правила игры: без него триаж не работает"),
    ("data", "taxonomy.json", "желательный", "список категорий, которые всегда уходят человеку"),
    ("data", "tickets_train.jsonl.gz", "для обучения", "обучение моделей (make train)"),
    ("data", "tickets_valid.jsonl", "для проверки", "метрики (make eval) и make predict"),
    ("models", "category.pkl", "желательный", "ML-классификатор категории (создаётся make train)"),
    ("models", "verdict.pkl", "желательный", "модель исхода жалобы (создаётся make train)"),
]


def files_status(data_dir: Path, models_dir: Path) -> list[dict]:
    base = {"data": Path(data_dir), "models": Path(models_dir)}
    out = []
    for group, name, role, purpose in DATA_FILES:
        p = base[group] / name
        out.append({"path": f"{group}/{name}", "resolved": str(p), "role": role, "purpose": purpose,
                    "present": p.exists(), "size": p.stat().st_size if p.exists() else None})
    return out


def check_rules(path: Path) -> list[str]:
    """Ошибки структуры rules.json; пустой список значит, что файл пригоден."""
    problems = []
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"нет файла {path}"]
    except (ValueError, UnicodeDecodeError) as e:
        return [f"{path} не разбирается как JSON: {e}"]
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        return ["в rules.json нет списка «rules»"]
    seen: set[tuple] = set()
    n_points = 0
    for i, sec in enumerate(data["rules"]):
        if not isinstance(sec, dict) or "id" not in sec:
            problems.append(f"раздел №{i} без поля id")
            continue
        for j, p in enumerate(sec.get("points") or []):
            if not isinstance(p, dict) or not p.get("ref") or not isinstance(p.get("text"), str):
                problems.append(f"раздел {sec['id']}, пункт №{j}: нужны поля ref и text")
                continue
            key = (sec["id"], p["ref"])
            if key in seen:
                problems.append(f"раздел {sec['id']}: пункт {p['ref']} повторяется")
            seen.add(key)
            n_points += 1
    if n_points == 0:
        problems.append("в rules.json нет ни одного пункта")
    return problems


def check_tickets(path: Path, sample: int = 200) -> dict:
    """Разбор первых строк выгрузки обращений: сколько строк целых и что с остальными."""
    path = Path(path)
    if not path.exists():
        return {"path": str(path), "present": False}
    opener = gzip.open if path.suffix == ".gz" else open
    ok = bad = 0
    errors: list[str] = []
    with opener(path, "rt", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if i > sample:
                break
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if not isinstance(d, dict) or not isinstance(d.get("messages"), list):
                    raise ValueError("нет списка messages")
                ok += 1
            except ValueError as e:
                bad += 1
                if len(errors) < 5:
                    errors.append(f"строка {i}: {e}")
    return {"path": str(path), "present": True, "checked": ok + bad, "ok": ok, "bad": bad, "errors": errors}


def check_models(models_dir: Path) -> dict:
    """Модели только проверяются на наличие и размер: загрузка pickle происходит в самом сервисе."""
    out = {}
    for name in ("category.pkl", "verdict.pkl"):
        p = Path(models_dir) / name
        out[name] = {"present": p.exists(), "size": p.stat().st_size if p.exists() else None}
    return out


def full_report(data_dir: Path, models_dir: Path) -> dict:
    data_dir, models_dir = Path(data_dir), Path(models_dir)
    files = files_status(data_dir, models_dir)
    rules_problems = check_rules(data_dir / "rules.json") if (data_dir / "rules.json").exists() else ["нет файла rules.json"]
    return {"files": files, "missing": [f["path"] for f in files if not f["present"]],
            "rules_problems": rules_problems,
            "train": check_tickets(data_dir / "tickets_train.jsonl.gz"),
            "valid": check_tickets(data_dir / "tickets_valid.jsonl"),
            "models": check_models(models_dir)}
