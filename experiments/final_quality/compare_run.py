"""Контролируемое сравнение A (шаблоны Sentra) и B (Qwen3.5-4B + RAG по правилам + guard) на одной выборке.

Выборка фиксируется ДО генерации: стратификация по языку ответа и сценарию, фиксированный seed, правила отбора в коде;
ни одна система в отборе не участвует. Сценарии берутся только из тех, где LLM разрешено переформулировать
(copilot.llm.DEFAULT_INTENTS), поэтому остальные 19 % тикетов в обеих системах одинаковы.

Режимы:
  real       тикеты valid (данные кейса): метрики-инварианты, латентность, слепые пары для человека. Тексты только локально.
  synthetic  tests/fixtures/synthetic_tickets.json на tests/fixtures/rules_mini.json: без данных кейса, можно отдавать судье-LLM.
Запуск: python experiments/final_quality/compare_run.py --mode real --n 150
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import re
import shutil
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
from common import ROOT  # noqa: E402

import numpy as np  # noqa: E402

from copilot import lang as lang_mod  # noqa: E402
from copilot.pipeline import Copilot  # noqa: E402

_spec = importlib.util.spec_from_file_location("eval_drafts", ROOT / "scripts" / "eval_drafts.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)          # независимый от production-guard список обещаний и проверка ссылок

SCENARIO_MARKERS = {   # грубый автоматический признак полноты ответа по сценарию (не оценка качества)
    "need_evidence": r"видео|video|бейне|videoz|dalil|yutub|youtube",
    "approve": r"рассмотр|ko.rib chiq|қаралды|администратор|administrator|әкімші",
    "appeal_reject": r"обжалован|жаза|jazo|шағым|shikoyat|рассмотр",
    "question_unknown": r"discord",
    "report_watch": r"администратор|administrator|әкімші|проследит|kuzat|бақыла",
    "clarify": r"уточн|aniqroq|нақтыла|что|nima|не болды",
}


def payload_of(d: dict) -> dict:
    p = {k: v for k, v in d.items() if k not in ("verdict", "punishment", "violation", "category", "priority")}
    p["messages"] = [m for m in d["messages"] if m["role"] != "admin"]
    return p


def stratified_sample(items, n, seed):
    """items: [(id, lang, intent)] -> список id. kk целиком, uz до 30 %, остальное ru; внутри языка пропорционально сценарию."""
    rnd = random.Random(seed)
    by_lang = defaultdict(list)
    for it in items:
        by_lang[it[1]].append(it)
    quota = {"kk": len(by_lang.get("kk", [])), "uz": min(len(by_lang.get("uz", [])), int(n * 0.3))}
    quota["ru"] = min(len(by_lang.get("ru", [])), n - quota["kk"] - quota["uz"])
    picked = []
    for lg, q in quota.items():
        pool = by_lang.get(lg, [])
        by_int = defaultdict(list)
        for it in pool:
            by_int[it[2]].append(it)
        tot = len(pool)
        shares = {k: len(v) / tot * q for k, v in by_int.items()}
        alloc = {k: int(s) for k, s in shares.items()}
        rest = q - sum(alloc.values())
        for k in sorted(shares, key=lambda k: shares[k] - alloc[k], reverse=True)[:rest]:
            alloc[k] += 1
        for k, a in alloc.items():
            picked += [x[0] for x in rnd.sample(sorted(by_int[k]), min(a, len(by_int[k])))]
    return picked


def det_checks(resp, known_refs, nick):
    bad = ev.check(resp, known_refs, None)
    text = resp["draft_reply"]["text"]
    m = re.findall(r"(?:ник\w*|nick\w*)\s*[:\-]?\s*([A-Za-z][\w.\-]{2,31})", text, re.I)
    if nick and any(x.lower() != nick.lower() for x in m):
        bad.append("nick_mismatch")
    return bad


def completeness(resp):
    d = resp["draft_reply"]
    text = d["text"].lower()
    cited = d["cited"]
    nums = [c.split(" ")[-1] for c in cited]
    cov = np.mean([n in text for n in nums]) if nums else None
    marker = SCENARIO_MARKERS.get(resp["_meta"]["intent"])
    return {"cite_coverage": cov, "scenario_marker": bool(re.search(marker, text)) if marker else None}


def pct(a, q):
    return round(float(np.percentile(a, q)), 3) if len(a) else None


def run_pair(cp_a, cp_b, gen, payloads, ids, known, nicks):
    """Прогон A и B на одинаковых payload. Возвращает записи по тикетам."""
    recs = []
    for i, p in zip(ids, payloads):
        t0 = time.perf_counter()
        a = cp_a.triage(p, use_dedup=False)
        ta = (time.perf_counter() - t0) * 1000
        n_log = len(gen.log)
        t0 = time.perf_counter()
        b = cp_b.triage(p, use_dedup=False)
        tb = (time.perf_counter() - t0) * 1000
        log = gen.log[n_log] if len(gen.log) > n_log else {}
        recs.append({"id": i, "a": a, "b": b, "ms_a": ta, "ms_b": tb, "log": log,
                     "bad_a": det_checks(a, known, nicks.get(i)), "bad_b": det_checks(b, known, nicks.get(i))})
    return recs


def summarize(recs, gen, title):
    n = len(recs)
    by_status = Counter(r["log"].get("status", "skipped") for r in recs)
    ok = [r for r in recs if r["log"].get("status") == "ok"]
    raw = [r for r in recs if r["log"].get("raw_text") is not None]
    # что поймал guard: независимая проверка сырых текстов Qwen до fallback
    raw_bad = Counter()
    for r in raw:
        t = r["log"]["raw_text"]
        resp = json.loads(json.dumps(r["a"]))
        resp["draft_reply"]["text"] = t
        for b in det_checks(resp, KNOWN, None):
            raw_bad[b] += 1
    lat_a = [r["ms_a"] for r in recs]
    lat_b = [r["ms_b"] for r in recs]
    gen_s = [r["log"]["seconds"] for r in recs if "seconds" in r["log"]]
    toks = [r["log"]["tokens_out"] for r in recs if "tokens_out" in r["log"]]
    out = {
        "title": title, "n": n, "status_B": dict(by_status),
        "b_text_used_share": round(len(ok) / n, 3),
        "needs_human_equal": sum(r["a"]["needs_human"] == r["b"]["needs_human"] for r in recs),
        "needs_human_changed_ids": [r["id"] for r in recs if r["a"]["needs_human"] != r["b"]["needs_human"]][:10],
        "category_equal": sum(r["a"]["category"] == r["b"]["category"] for r in recs),
        "cited_equal": sum(r["a"]["draft_reply"]["cited"] == r["b"]["draft_reply"]["cited"] or not r["log"].get("status") == "ok"
                           for r in recs),
        "final_invariant_failures": {"A": dict(Counter(x for r in recs for x in r["bad_a"])),
                                     "B_final": dict(Counter(x for r in recs for x in r["bad_b"]))},
        "raw_qwen_invariant_failures_before_guard": {"n_raw": len(raw), **dict(raw_bad)},
        "reject_reasons": dict(Counter(re.sub(r"\d+", "N", p)[:60] for r in recs for p in r["log"].get("problems", []))
                               .most_common(12)),
        "latency_ms_end_to_end": {"A": {"p50": pct(lat_a, 50), "p95": pct(lat_a, 95), "p99": pct(lat_a, 99)},
                                  "B": {"p50": pct(lat_b, 50), "p95": pct(lat_b, 95), "p99": pct(lat_b, 99),
                                        "max": round(max(lat_b), 1)}},
        "qwen_generation": {"seconds_p50": pct(gen_s, 50), "seconds_p95": pct(gen_s, 95), "seconds_mean": round(float(np.mean(gen_s)), 3) if gen_s else None,
                            "tokens_out_mean": round(float(np.mean(toks)), 1) if toks else None,
                            "tokens_per_second": round(float(np.sum(toks) / np.sum(gen_s)), 2) if gen_s else None},
        "text_length_chars": {"A_mean": round(float(np.mean([len(r["a"]["draft_reply"]["text"]) for r in recs])), 1),
                              "B_mean": round(float(np.mean([len(r["b"]["draft_reply"]["text"]) for r in recs])), 1)},
    }
    comp_a = [completeness(r["a"]) for r in recs]
    comp_b = [completeness(r["b"]) for r in recs]
    for name, comp in (("A", comp_a), ("B_final", comp_b)):
        cov = [c["cite_coverage"] for c in comp if c["cite_coverage"] is not None]
        mk = [c["scenario_marker"] for c in comp if c["scenario_marker"] is not None]
        out.setdefault("completeness_proxy", {})[name] = {
            "cite_coverage": round(float(np.mean(cov)), 3) if cov else None,
            "scenario_marker": round(float(np.mean(mk)), 3) if mk else None}
    by_lang = {}
    for lg in ("ru", "uz", "kk", "en"):
        sub = [r for r in recs if r["a"]["draft_reply"]["lang"] == lg]
        if sub:
            s_ok = [r for r in sub if r["log"].get("status") == "ok"]
            by_lang[lg] = {"n": len(sub), "b_text_used": len(s_ok), "b_used_share": round(len(s_ok) / len(sub), 3),
                           "rejected": sum(r["log"].get("status") == "rejected" for r in sub),
                           "errors": sum(r["log"].get("status") == "error" for r in sub),
                           "lang_detect_mismatch_B_final": sum("lang_detected" in r["bad_b"] for r in sub),
                           "lang_detect_mismatch_A": sum("lang_detected" in r["bad_a"] for r in sub),
                           "gen_seconds_p95": pct([r["log"]["seconds"] for r in sub if "seconds" in r["log"]], 95)}
    out["by_lang"] = by_lang
    out["by_intent"] = {k: {"n": c, "b_used": sum(1 for r in ok if r["a"]["_meta"]["intent"] == k)}
                        for k, c in Counter(r["a"]["_meta"]["intent"] for r in recs).items()}
    return out


KNOWN: set[str] = set()


def main():
    global KNOWN
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["real", "synthetic"], required=True)
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--quant", default="nf4")
    ap.add_argument("--max-new-tokens", type=int, default=170)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from qwen_gen import GEN_INTENTS, QwenGenerator

    tmp = None
    if args.mode == "real":
        cp_a = Copilot()
        rows = list(C.iter_jsonl(ROOT / "data/tickets_valid.jsonl"))
        pay = {d["ticket_id"]: payload_of(d) for d in rows}
        nicks = {d["ticket_id"]: d.get("reported_nick") for d in rows}
        # какие сценарии выбирает baseline без дедупа (выборка не зависит от Qwen)
        base = {i: cp_a.triage(p, use_dedup=False) for i, p in pay.items()}
        elig = [(i, r["draft_reply"]["lang"], r["_meta"]["intent"]) for i, r in base.items() if r["_meta"]["intent"] in GEN_INTENTS]
        ids = stratified_sample(elig, args.n, C.SEED)
        random.Random(C.SEED + 1).shuffle(ids)
        (C.PRIVATE / "sample_ids.json").write_text(json.dumps(ids), encoding="utf-8")
        print(f"eligible {len(elig)} of {len(base)}; sample {len(ids)}: {dict(Counter((base[i]['draft_reply']['lang'], base[i]['_meta']['intent']) for i in ids))}", flush=True)
        payloads = [pay[i] for i in ids]
    else:
        tmp = tempfile.mkdtemp()
        shutil.copy(ROOT / "tests/fixtures/rules_mini.json", Path(tmp) / "rules.json")
        cp_a = Copilot(tmp, Path(tmp) / "no_models")
        rows = json.loads((ROOT / "tests/fixtures/synthetic_tickets.json").read_text(encoding="utf-8"))
        payloads, ids, nicks = [], [], {}
        for r in rows:
            p = ev._payload(r)
            p["messages"] = [m for m in p["messages"] if m.get("role") != "admin"]
            payloads.append(p)
            ids.append(r.get("id") or f"syn{len(ids)}")
    KNOWN = {p.ref for p in cp_a.rules.points.values()}

    gen = QwenGenerator(quant=args.quant, max_new_tokens=args.max_new_tokens)
    print(f"model loaded in {gen.load_seconds}s", flush=True)
    cp_b = Copilot(cp_a.data_dir, cp_a.models_dir, llm=gen)
    import torch
    torch.cuda.reset_peak_memory_stats()
    recs = run_pair(cp_a, cp_b, gen, payloads, ids, KNOWN, nicks)
    rep = summarize(recs, gen, f"{args.mode} n={len(recs)}")
    rep["config"] = {"model": gen.model_id, "quant": gen.quant, "max_new_tokens": gen.max_new_tokens, "decoding": "greedy",
                     "repetition_penalty": gen.rep, "thinking": False, "load_seconds": gen.load_seconds,
                     "vram_peak_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
                     "torch": torch.__version__, "seed_sample": C.SEED}
    tag = args.tag
    (C.OUT / f"draft_compare_{args.mode}{tag}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))

    # приватные полные записи + слепые пары
    priv = [{"id": r["id"], "player_text": " ".join(m.get("text") or "" for m in p["messages"] if m.get("role", "player") == "player"),
             "lang": r["a"]["draft_reply"]["lang"], "intent": r["a"]["_meta"]["intent"], "category": r["a"]["category"],
             "A": r["a"]["draft_reply"]["text"], "B": r["b"]["draft_reply"]["text"], "B_status": r["log"].get("status"),
             "B_raw": r["log"].get("raw_text"), "B_problems": r["log"].get("problems"), "needs_human_A": r["a"]["needs_human"],
             "needs_human_B": r["b"]["needs_human"], "cited_A": r["a"]["draft_reply"]["cited"],
             "gen_seconds": r["log"].get("seconds")} for r, p in zip(recs, payloads)]
    base_dir = C.PRIVATE if args.mode == "real" else C.CACHE
    (base_dir / f"compare_{args.mode}{tag}.json").write_text(json.dumps(priv, ensure_ascii=False, indent=1), encoding="utf-8")
    rnd = random.Random(C.SEED + 2)
    pairs, key = [], {}
    for k, r in enumerate(priv):
        if r["B_status"] != "ok" or r["A"] == r["B"]:
            continue
        flip = rnd.random() < 0.5
        x, y = (r["B"], r["A"]) if flip else (r["A"], r["B"])
        pid = f"P{k:03d}"
        pairs.append({"pair_id": pid, "lang": r["lang"], "player_text": r["player_text"], "reply_X": x, "reply_Y": y})
        key[pid] = {"X": "B" if flip else "A", "Y": "A" if flip else "B", "id": r["id"]}
    (base_dir / f"blind_pairs_{args.mode}{tag}.jsonl").write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in pairs), encoding="utf-8")
    (base_dir / f"blind_pairs_{args.mode}{tag}.KEY.json").write_text(json.dumps(key, ensure_ascii=False), encoding="utf-8")
    print(f"blind pairs: {len(pairs)} -> {base_dir}", flush=True)
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
