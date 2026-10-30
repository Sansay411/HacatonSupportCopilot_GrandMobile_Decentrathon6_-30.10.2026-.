"""make suggest-templates

Бонус кейса: автоматические кандидаты в новые шаблоны ответов по кластерам похожих обращений.

1. Каждый тикет train проходит через Copilot.triage: берём category, _meta.intent и текст черновика.
2. Внутри категории тексты игроков кластеризуются (TF-IDF по символьным n-граммам + MiniBatchKMeans).
3. Для кластера считаются самые частые ответы админов (ники и числа заменены на плейсхолдеры).
4. Кластеры, где ответы повторяются, а сценарии drafts.py их покрывают плохо, помечаются кандидатами.

Выход:
  reports/private/template_suggestions.json          с примерами из данных, не коммитить
  reports/template_suggestions_summary.md            агрегаты и формулировки шаблонов
  reports/template_suggestions_summary.json          то же для GET /templates
"""
from __future__ import annotations

import argparse
import gzip
import json
import multiprocessing as mp
import os
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from copilot.pipeline import Copilot  # noqa: E402
from copilot.template_suggest import Params, build_suggestions, public_view, render_markdown, stock_replies  # noqa: E402

_CP: Copilot | None = None


def _open(path: str):
    return gzip.open(path, "rt", encoding="utf-8") if path.endswith(".gz") else open(path, encoding="utf-8")


def _last_admin_reply(row: dict) -> str:
    adm = [m.get("text") or "" for m in row.get("messages") or [] if m.get("role") == "admin"]
    return adm[-1] if adm else ""


def _triage_row(row: dict) -> dict:
    r = _CP.triage(row, use_dedup=False)
    return {"category": r["category"], "intent": r["_meta"]["intent"], "draft": r["draft_reply"]["text"]}


def _init_worker() -> None:
    global _CP
    _CP = Copilot()


def load_records(path: str, limit: int | None, workers: int) -> list[dict]:
    rows = []
    with _open(path) as f:
        for line in f:
            row = json.loads(line)
            if _last_admin_reply(row).strip():
                rows.append(row)
            if limit and len(rows) >= limit:
                break
    t0 = time.time()
    print(f"тикетов с ответом админа: {len(rows)}; triage в {workers} процесс(ов)...", flush=True)
    if workers > 1:
        ctx = mp.get_context("fork")
        with ctx.Pool(workers, initializer=_init_worker) as pool:
            res = pool.map(_triage_row, rows, chunksize=500)
    else:
        _init_worker()
        res = [_triage_row(r) for r in rows]
    print(f"triage: {time.time() - t0:.0f} с", flush=True)
    out = []
    for row, r in zip(rows, res):
        player = "\n".join(m.get("text") or "" for m in row["messages"] if m.get("role", "player") == "player")
        out.append({"ticket_id": row.get("ticket_id"), "kind": row.get("kind"), "lang": row.get("lang"),
                    "player_text": player, "reply": _last_admin_reply(row), **r})
    return out


def cached_records(args) -> list[dict]:
    """triage 118 тыс. тикетов занимает около двух минут, поэтому результат кэшируется (в reports/private/).

    Ключ кэша: файл train, лимит и время обучения моделей. Кэш содержит тексты игроков, не коммитить.
    """
    models = [ROOT / "models/category.pkl", ROOT / "models/verdict.pkl"]
    st = Path(args.train).stat()
    key = [st.st_size, int(st.st_mtime), args.limit] + [int(m.stat().st_mtime) if m.exists() else 0 for m in models]
    path = ROOT / "reports/private/triage_cache.pkl"
    if not args.no_cache and path.exists():
        with open(path, "rb") as f:
            saved = pickle.load(f)
        if saved.get("key") == key:
            print(f"кэш triage: {len(saved['records'])} тикетов", flush=True)
            return saved["records"]
    records = load_records(args.train, args.limit, args.workers)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump({"key": key, "records": records}, f)
    return records


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default=str(ROOT / "data/tickets_train.jsonl.gz"))
    ap.add_argument("--limit", type=int, default=None, help="взять первые N тикетов с ответом (для проверки)")
    ap.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--categories", nargs="*", default=None)
    ap.add_argument("--private-out", default=str(ROOT / "reports/private/template_suggestions.json"))
    ap.add_argument("--summary-md", default=str(ROOT / "reports/template_suggestions_summary.md"))
    ap.add_argument("--summary-json", default=str(ROOT / "reports/template_suggestions_summary.json"))
    d = Params()
    ap.add_argument("--min-cluster", type=int, default=d.min_cluster)
    ap.add_argument("--min-reply-count", type=int, default=d.min_reply_count)
    ap.add_argument("--min-reply-share", type=float, default=d.min_reply_share)
    ap.add_argument("--merge-sim", type=float, default=d.merge_sim)
    ap.add_argument("--no-cache", action="store_true", help="не использовать кэш triage в reports/private/")
    ap.add_argument("--min-lift", type=float, default=d.min_lift)
    ap.add_argument("--stock-share", type=float, default=d.stock_share)
    ap.add_argument("--stock-min-count", type=int, default=d.stock_min_count)
    ap.add_argument("--intent-share-ok", type=float, default=d.intent_share_ok)
    ap.add_argument("--draft-sim-ok", type=float, default=d.draft_sim_ok)
    ap.add_argument("--max-k", type=int, default=d.max_k)
    ap.add_argument("--per-cluster", type=int, default=d.per_cluster)
    args = ap.parse_args()

    P = Params(min_cluster=args.min_cluster, min_reply_count=args.min_reply_count,
               min_reply_share=args.min_reply_share, min_lift=args.min_lift, merge_sim=args.merge_sim,
               stock_share=args.stock_share, stock_min_count=args.stock_min_count, intent_share_ok=args.intent_share_ok,
               draft_sim_ok=args.draft_sim_ok, max_k=args.max_k, per_cluster=args.per_cluster)
    records = cached_records(args)
    cp = Copilot()
    t0 = time.time()
    clusters = build_suggestions(records, cp.rules, P, args.categories)
    print(f"кластеризация: {time.time() - t0:.0f} с, кластеров: {len(clusters)}", flush=True)

    summary = public_view(clusters, P, {"tickets": len(records), "source": "train"}, stock_replies(records, P))
    for path in (args.private_out, args.summary_md, args.summary_json):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(args.private_out).write_text(json.dumps({"params": summary["meta"]["params"], "clusters": clusters},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    Path(args.summary_json).write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(args.summary_md).write_text(render_markdown(summary), encoding="utf-8")
    t = summary["totals"]
    print(f"кандидатов: {t['candidates']} из {t['clusters']} кластеров; записано: {args.summary_md}")


if __name__ == "__main__":
    main()
