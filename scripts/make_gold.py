"""Собирает dev-разметку valid: правила + ручные правки после просмотра всех 1000 строк.

Разметку делал участник команды по описаниям из taxonomy.json (это черновик
организаторов, подтверждённой разметки нет). Файл с результатом лежит в
data/labels/ и в репозиторий не попадает: это производные данные.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copilot.rules import load
from copilot.signals import extract
from copilot.taxonomy import label_rules, priority_rules
from copilot.ticket import from_dict

# индекс строки в tickets_valid.jsonl -> категория (без префикса kind)
OVERRIDES = {
    2: "dm", 9: "admin", 10: "admin", 24: "admin", 25: "admin", 26: "dm", 48: "admin", 66: "dm", 67: "dm",
    68: "admin", 69: "admin", 70: "dm", 75: "admin", 87: "admin", 90: "dm", 98: "dm", 100: "admin",
    104: "invalid", 107: "admin", 116: "admin", 122: "admin", 124: "admin", 134: "insult", 143: "admin",
    158: "admin", 162: "admin", 165: "admin", 173: "admin", 182: "other", 190: "admin", 194: "invalid",
    195: "admin", 201: "other", 202: "admin", 207: "admin", 211: "admin", 216: "admin", 218: "admin",
    222: "other", 229: "insult", 232: "admin", 234: "admin",
    259: "dm", 266: "admin", 267: "insult", 270: "admin", 276: "admin", 284: "invalid", 291: "dm",
    300: "admin", 307: "invalid", 312: "other", 318: "invalid", 324: "admin", 344: "admin", 348: "admin",
    349: "invalid", 354: "admin", 356: "admin", 358: "admin", 360: "admin", 373: "admin", 374: "invalid",
    380: "admin", 381: "admin", 386: "admin", 413: "dm", 429: "admin", 430: "admin", 447: "admin",
    462: "admin", 464: "admin", 467: "admin", 474: "admin", 482: "admin", 524: "admin",
    529: "admin", 547: "scam", 552: "admin", 554: "admin", 559: "insult", 560: "other", 563: "scam",
    565: "admin", 568: "other", 579: "admin", 580: "admin", 590: "invalid", 595: "invalid", 596: "admin",
    597: "admin", 606: "invalid", 607: "admin", 611: "admin", 618: "admin", 629: "insult", 630: "invalid",
    631: "other", 643: "invalid", 645: "other", 647: "invalid", 648: "invalid", 649: "invalid", 654: "scam",
    655: "admin", 663: "invalid", 667: "dm", 668: "scam", 673: "admin", 674: "invalid", 677: "admin",
    678: "admin", 685: "insult", 689: "invalid", 692: "admin", 695: "invalid", 705: "admin", 712: "invalid",
    715: "admin", 719: "invalid", 721: "insult", 723: "invalid", 736: "admin", 739: "admin", 747: "admin",
    748: "other", 754: "admin", 755: "admin", 756: "admin", 763: "invalid", 766: "invalid", 770: "scam",
    774: "other", 778: "admin", 791: "other", 792: "admin", 793: "cheat", 796: "scam", 797: "scam",
    799: "cheat", 803: "scam", 808: "invalid", 811: "other", 815: "admin",
    # репорты
    819: "offtopic", 820: "offtopic", 822: "help", 838: "offtopic", 841: "offtopic", 845: "offtopic",
    848: "help", 857: "help", 859: "help", 869: "help", 871: "offtopic", 872: "help", 875: "help",
    877: "help", 888: "help", 897: "help", 898: "account", 904: "offtopic", 907: "help", 909: "complaint",
    915: "help", 916: "offtopic", 920: "offtopic", 923: "help", 926: "help", 936: "help", 938: "offtopic",
    949: "help", 952: "offtopic", 959: "complaint", 963: "complaint", 972: "help", 983: "help",
    988: "complaint", 993: "help", 994: "help", 995: "help", 996: "complaint", 999: "help",
}
PRIORITY_OVERRIDES = {883: "p2"}


def main():
    root = Path(__file__).resolve().parents[1]
    rb = load(root / "data/rules.json")
    rows = [json.loads(l) for l in open(root / "data/tickets_valid.jsonl", encoding="utf-8")]
    gold = {}
    for i, d in enumerate(rows):
        t = from_dict(d)
        sig = extract(t.player_text, rb, t.rule_refs_raw, t.images, t.reported_nick)
        cat = label_rules(t.kind, sig, t.player_text)
        if i in OVERRIDES:
            cat = f"{t.kind}.{OVERRIDES[i]}"
        pr = PRIORITY_OVERRIDES.get(i) or priority_rules(cat, sig)
        gold[d["ticket_id"]] = {"category": cat, "priority": pr}
    out = root / "data/labels/valid_gold.json"
    out.parent.mkdir(parents=True, exist_ok=True)     # на чистой машине data/labels ещё нет
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=0), encoding="utf-8")
    from collections import Counter
    print(Counter(v["category"] for v in gold.values()).most_common())
    print(Counter(v["priority"] for v in gold.values()).most_common())


if __name__ == "__main__":
    main()
