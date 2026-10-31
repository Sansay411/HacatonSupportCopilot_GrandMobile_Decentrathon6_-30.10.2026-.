"""Сравнение двух снимков experiments/final_polish/snapshot.py на одинаковых входах.

    python experiments/final_polish/compare.py pre post

Печатает и пишет в reports/final_polish/compare_<a>_<b>.json только агрегаты: тексты игроков наружу не попадают.
"""
from __future__ import annotations

import collections
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PRIVATE = ROOT / "reports" / "private" / "final_polish"
PUBLIC = ROOT / "reports" / "final_polish"

# формулировки, которых в черновиках быть не должно (утверждения о проверке и закрытии, благодарности, текущее состояние)
UNWANTED = {
    "по приложенным материалам": re.compile(r"по приложенным материалам|тіркелген материалдардан|ilova qilingan materiallarda|attached materials|materiales adjuntos|materiais anexados", re.I),
    "жалоба закрыта": re.compile(r"жалоба закрыта|шағым жабылды|shikoyat yopildi|complaint is closed|queja está cerrada|denúncia está encerrada", re.I),
    "благодарность": re.compile(r"спасибо|благодар|рахмет|rahmat|thank you|gracias|obrigad", re.I),
    "администратор на связи / сейчас": re.compile(r"на связи|aloqada|байланыста|сейчас постарается|is on it|está atento|está acompanhando|hozir yordam|қазір көмек", re.I),
    "следите за объявлениями": re.compile(r"следите за объявлени|хабарландыр|e.lonlarini|watch for administrator|atento a los anuncios|acompanhe os anúncios", re.I),
}


def load(tag: str, name: str) -> list[dict]:
    return [json.loads(x) for x in open(PRIVATE / f"{tag}_{name}.jsonl", encoding="utf-8")]


def lens(recs, key=lambda r: True):
    v = [len(r["text"]) for r in recs if key(r)]
    return {"n": len(v), "median": int(statistics.median(v)), "mean": round(statistics.mean(v), 1)} if v else {"n": 0}


def diversity(recs) -> dict:
    """Различных текстов на 1000 черновиков и доля самого частого текста: чем ниже доля, тем разнообразнее."""
    c = collections.Counter(r["text"] for r in recs)
    return {"distinct": len(c), "per_1000": round(len(c) / len(recs) * 1000, 1), "top_share": round(c.most_common(1)[0][1] / len(recs), 3)}


def main(a: str, b: str) -> None:
    out: dict = {"a": a, "b": b}
    for name in ("valid", "train"):
        A, B = load(a, name), load(b, name)
        assert [r["ticket_id"] for r in A] == [r["ticket_id"] for r in B]
        cat = sum(x["category"] != y["category"] for x, y in zip(A, B))
        pri = sum(x["priority"] != y["priority"] for x, y in zip(A, B))
        nh = collections.Counter(f"{x['needs_human']}->{y['needs_human']}" for x, y in zip(A, B) if x["needs_human"] != y["needs_human"])
        refs = sum(x["rule_refs"] != y["rule_refs"] for x, y in zip(A, B))
        intent = collections.Counter(f"{x['intent']}->{y['intent']}" for x, y in zip(A, B) if x["intent"] != y["intent"])
        cited_same_intent = sum(x["cited"] != y["cited"] for x, y in zip(A, B) if x["intent"] == y["intent"])
        lang = sum(x["reply_lang"] != y["reply_lang"] for x, y in zip(A, B))
        dup = sum(x["is_dup"] != y["is_dup"] for x, y in zip(A, B))
        text = sum(x["text"] != y["text"] for x, y in zip(A, B))
        phr = {k: [sum(bool(rx.search(r["text"])) for r in A), sum(bool(rx.search(r["text"])) for r in B)] for k, rx in UNWANTED.items()}
        per_intent = {}
        for it in ("approve", "need_evidence", "report_watch", "help_ack", "appeal", "event_tp", "help_generic"):
            per_intent[it] = {"a": lens(A, lambda r: r["intent"] == it), "b": lens(B, lambda r: r["intent"] == it)}
        # у нечеловеческих (needs_human=False) сценариев автоотправка допустима: сравниваем долю
        out[name] = {
            "n": len(A), "category_changed": cat, "priority_changed": pri, "needs_human_changed": dict(nh),
            "rule_refs_changed": refs, "cited_changed_same_intent": cited_same_intent, "intent_transitions": dict(intent),
            "reply_lang_changed": lang, "is_dup_changed": dup, "text_changed": text,
            "median_len_all": [lens(A)["median"], lens(B)["median"]],
            "median_len_complaint": [lens(A, lambda r: r["kind"] == "complaint")["median"], lens(B, lambda r: r["kind"] == "complaint")["median"]],
            "median_len_report": [lens(A, lambda r: r["kind"] == "report")["median"], lens(B, lambda r: r["kind"] == "report")["median"]],
            "diversity": {"a": diversity(A), "b": diversity(B)},
            "unwanted_phrases_a_b": phr, "per_intent": per_intent,
            "needs_human_share": [round(sum(r["needs_human"] for r in A) / len(A), 4), round(sum(r["needs_human"] for r in B) / len(B), 4)],
        }
    for name in ("synth", "tera"):
        A = json.loads((PRIVATE / f"{a}_{name}.json").read_text(encoding="utf-8"))
        B = json.loads((PRIVATE / f"{b}_{name}.json").read_text(encoding="utf-8"))
        key = "i" if name == "synth" else None
        out[name] = {
            "n": len(A),
            "category_changed": sum(x["category"] != y["category"] for x, y in zip(A, B)),
            "priority_changed": sum(x["priority"] != y["priority"] for x, y in zip(A, B)),
            "needs_human_changed": sum(x["needs_human"] != y["needs_human"] for x, y in zip(A, B)),
            "intent_changed": sum(x["intent"] != y["intent"] for x, y in zip(A, B)),
            "needs_human_all_b": all(y["needs_human"] for y in B) if name == "tera" else None,
            "scenario_ok_b": (sum(y["intent"] in y["ok"] for y in B if y["ok"]), sum(1 for y in B if y["ok"])) if name == "synth" else None,
        }
    out["latency_ms_p50_p95"] = {t: [json.loads((PUBLIC / f"{t}_aggregate.json").read_text(encoding="utf-8"))[s][k] for s in ("valid", "train") for k in ("latency_ms_p50", "latency_ms_p95")] for t in (a, b)}
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / f"compare_{a}_{b}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:3])
