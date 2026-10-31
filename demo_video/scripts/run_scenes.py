"""Запуск сцен: репетиция без записи (--dry) или запись кадров.

    python demo_video/scripts/run_scenes.py --scenes 1,2,3,4,5,6 [--dry] [--seed] [--tag take1]

--seed создаёт 12 синтетических обращений в базе до первой сцены (нужно один раз после сброса базы).
Репетиция делает те же действия, но не пишет кадры и сохраняет снимки в demo_video/work/rehearsal/.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rec_lib import ROOT, WORK, Rec
from scenes import BASE, SCENES
from seed_demo import seed


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", default="1,2,3,4,5,6")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--tag", default="run")
    args = ap.parse_args()
    log: dict = {"tag": args.tag, "dry": args.dry, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    if args.seed:
        log["seed"] = seed(BASE)
        print("seed:", len(log["seed"]), "обращений")
    r = Rec(BASE, capture=not args.dry, shots=WORK / "rehearsal" if args.dry else None)
    await r.open()
    try:
        for key in args.scenes.split(","):
            fn = SCENES[key.strip()]
            t0 = time.perf_counter()
            print(f"сцена {key}: {fn.__name__} ...", flush=True)
            await fn(r, log)
            print(f"  готово за {time.perf_counter() - t0:.1f} с", flush=True)
        log["marks"] = r.marks
        log["requests"] = r.requests
        log["errors"] = r.errors
        log["clips"] = r.clips
    except Exception:
        log["requests"], log["errors"], log["clips"] = r.requests, r.errors, r.clips
        try:
            await r.shot("FAIL")
        except Exception:
            pass
        raise
    finally:
        (WORK / f"run_log_{args.tag}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        await r.close()
    print("ошибки консоли и сети:", r.errors or "нет")
    for c in r.clips:
        print(c)


asyncio.run(main())
