"""Замер скорости и стоимости: настоящие вызовы, ничего не зашито.

    python scripts/bench.py --n 2000                 # пайплайн в процессе
    python scripts/bench.py --n 500 --http           # POST /triage по HTTP на настоящем uvicorn
    python scripts/bench.py --fixture --http         # на тестовых правилах, если данных кейса нет
    python scripts/bench.py --valid --http           # на настоящих обращениях data/tickets_valid.jsonl (нужны data/ и models/)

Ограничения кейса: стоимость не выше $0.002 за обращение, p95 до 5 секунд. Скрипт измеряет задержку каждого вызова
(time.perf_counter), стоимость берёт из счётчиков LLM (без LLM внешних вызовов нет и стоимость 0) и печатает, на какой
конфигурации сделан замер: тестовые или настоящие правила, есть ли ML-модели. Результат пишется в --out.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LIMIT_P95_MS = 5000
LIMIT_COST = 0.002


def corpus_valid(n: int) -> list[dict]:
    """Настоящие обращения валидации как есть (с заявителями и временем, дедупликация работает). Ответы админов убираются."""
    rows = [json.loads(x) for x in open(ROOT / "data/tickets_valid.jsonl", encoding="utf-8")]
    out = []
    for i in range(n):
        d = dict(rows[i % len(rows)])
        d["messages"] = [m for m in d.get("messages", []) if m.get("role") != "admin"]
        for k in ("verdict", "punishment", "violation", "status", "lang", "region"):
            d.pop(k, None)
        if i >= len(rows):
            d["reporter_hash"] = f"{d.get('reporter_hash')}-{i}"
        out.append(d)
    return out


def corpus(n: int) -> list[dict]:
    """n обращений: синтетическая выборка tests/fixtures, размноженная с разными заявителями (без дедупликации)."""
    rows = json.loads((ROOT / "tests/fixtures/synthetic_tickets.json").read_text(encoding="utf-8"))
    out = []
    for i in range(n):
        r = rows[i % len(rows)]
        out.append({"kind": r["kind"], "reporter_hash": f"bench-{i}", "created_at": f"2026-10-30T10:00:{i % 60:02d}Z",
                    "messages": [{"role": "player", "text": r["text"] + ("" if i < len(rows) else f" №{i}"),
                                  "attachments": r.get("att", 0)}]})
    return out


def pct(v: list[float], p: float) -> float:
    s = sorted(v)
    return s[min(len(s) - 1, int(p * len(s)))]


def stats(v: list[float]) -> dict:
    return {"n": len(v), "p50_ms": round(pct(v, .5), 2), "p95_ms": round(pct(v, .95), 2), "p99_ms": round(pct(v, .99), 2),
            "max_ms": round(max(v), 2), "mean_ms": round(sum(v) / len(v), 2)}


def run_inproc(items: list[dict]) -> tuple[list[float], dict]:
    from copilot.llm import from_env
    from copilot.pipeline import Copilot
    cp = Copilot(llm=from_env())
    cp.triage(items[0], use_dedup=False)                       # прогрев: первая загрузка не должна искажать p95
    lat = []
    for it in items:
        t0 = time.perf_counter()
        cp.triage(it, use_dedup=False)
        lat.append((time.perf_counter() - t0) * 1000)
    cfg = {"rules_synthetic": cp.rules_synthetic, "models_loaded": cp.category_model.loaded,
           "verdict_model_loaded": cp.verdict_model is not None, "llm": cp.llm is not None}
    cost = cp.llm.stats["cost_usd"] if cp.llm is not None else 0.0
    cfg["llm_calls"] = cp.llm.stats["calls"] if cp.llm is not None else 0
    cfg["_cost_total"] = cost
    return lat, cfg


def run_http(items: list[dict]) -> tuple[list[float], dict]:
    import httpx
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    tmp = Path(tempfile.mkdtemp(prefix="sentra-bench-"))
    env = dict(os.environ, COPILOT_DB=str(tmp / "bench.db"), PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "copilot.api:app", "--host", "127.0.0.1", "--port", str(port),
                             "--log-level", "warning"], cwd=ROOT, env=env)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(160):
            try:
                health = json.loads(urllib.request.urlopen(base + "/health", timeout=1).read())
                break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError("сервер не поднялся")
        if not health.get("ready"):
            raise RuntimeError("триаж недоступен: " + "; ".join(p["text"] for p in health["problems"] if p["level"] == "error"))
        lat = []
        with httpx.Client(base_url=base, timeout=30) as c:
            c.post("/triage", json=items[0])                   # прогрев
            for it in items:
                t0 = time.perf_counter()
                r = c.post("/triage", json=it)
                lat.append((time.perf_counter() - t0) * 1000)
                r.raise_for_status()
        cfg = {"rules_synthetic": health["rules_synthetic"], "models_loaded": health["model_loaded"],
               "verdict_model_loaded": health["verdict_model_loaded"], "llm": health["llm"], "_cost_total": 0.0, "llm_calls": 0}
        return lat, cfg
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--http", action="store_true", help="мерить POST /triage по HTTP, а не вызов пайплайна")
    ap.add_argument("--fixture", action="store_true", help="тестовые правила из tests/fixtures")
    ap.add_argument("--valid", action="store_true", help="настоящие обращения data/tickets_valid.jsonl вместо синтетических")
    ap.add_argument("--out", default=str(ROOT / "reports/bench_local.json"))
    args = ap.parse_args()
    if args.fixture:
        d = Path(tempfile.mkdtemp(prefix="sentra-bench-data-"))
        shutil.copy(ROOT / "tests/fixtures/rules_mini.json", d / "rules.json")
        os.environ["COPILOT_DATA"] = str(d)
    items = corpus_valid(args.n) if args.valid else corpus(args.n)
    lat, cfg = (run_http if args.http else run_inproc)(items)
    cost_total = cfg.pop("_cost_total")
    res = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "mode": "http" if args.http else "in-process",
        **stats(lat), "throughput_per_s": round(len(lat) / (sum(lat) / 1000), 1),
        "cost_usd_per_ticket": round(cost_total / len(lat), 6),
        "limits": {"p95_ms": LIMIT_P95_MS, "cost_usd_per_ticket": LIMIT_COST},
        "p95_within_limit": pct(lat, .95) <= LIMIT_P95_MS, "cost_within_limit": cost_total / len(lat) <= LIMIT_COST,
        "config": dict(cfg, corpus="data/tickets_valid.jsonl" if args.valid else "tests/fixtures/synthetic_tickets.json"),
        "host": {"python": platform.python_version(), "platform": platform.platform(), "cpus": os.cpu_count()},
        "note": ("Замер на ТЕСТОВЫХ правилах и без ML-моделей: данных кейса на машине нет. "
                 "Цифры ML-режима с реальными моделями не измерялись." if (cfg["rules_synthetic"] or not cfg["models_loaded"]) else
                 "Замер на правилах кейса и загруженных моделях."),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["p95_within_limit"] and res["cost_within_limit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
