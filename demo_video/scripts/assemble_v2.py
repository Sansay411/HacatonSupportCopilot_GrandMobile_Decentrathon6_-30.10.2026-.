"""Монтаж версии 2: титул, плашки возможностей, титулы частей, живое демо, слайды защиты, финал, музыка.

    python demo_video/scripts/render_deck.py
    python demo_video/scripts/assemble_v2.py [--music путь.mp3]

Записи сцен берутся из raw/ как есть (те же обрезки начала и хвоста, что в assemble.py). Карточки и слайды: assets/deck.html.
Выход: final/sentra_demo_grand_mobile_v2.mp4 (с музыкой), final/sentra_demo_grand_mobile_v2_silent.mp4 (без звука, для работы с озвучкой),
final/music_bed.wav (подложка нужной длины), final/timeline_v2.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from assemble import FINAL, FPS, RAW, TRIM_HEAD, TRIM_TAIL, WORK, card_clip, duration, run

DECK = WORK / "deck"
XF = 0.5
XF_PLAQUE = 0.4
XF_END = 0.8

# (ключ, источник, секунды карточки или None для записи, переход В этот сегмент, название для глав и таймлайна)
SEGMENTS = [
    ("intro", "card:" + str(WORK / "card_intro.png"), 2.8, 0.0, "Титул"),
    ("pl1", "card:" + str(DECK / "plaques-1.png"), 2.4, 0.6, "Возможности Sentra"),
    ("pl2", "card:" + str(DECK / "plaques-2.png"), 2.0, XF_PLAQUE, ""),
    ("pl3", "card:" + str(DECK / "plaques-3.png"), 2.0, XF_PLAQUE, ""),
    ("pl4", "card:" + str(DECK / "plaques-4.png"), 3.0, XF_PLAQUE, ""),
    ("sc1", "01_command_center.mp4", None, XF, "Сцена 1: командный центр"),
    ("sec2", "card:" + str(DECK / "sec-2.png"), 1.6, XF, "Часть 1: разбор настоящего обращения"),
    ("sc2", "02_triage.mp4", None, XF, ""),
    ("sec3", "card:" + str(DECK / "sec-3.png"), 1.6, XF, "Часть 2: защита от выдуманного"),
    ("sc3", "03_safety.mp4", None, XF, ""),
    ("sec4", "card:" + str(DECK / "sec-4.png"), 1.6, XF, "Часть 3: обязательная эскалация"),
    ("sc4", "04_escalation.mp4", None, XF, ""),
    ("sec5", "card:" + str(DECK / "sec-5.png"), 1.6, XF, "Часть 4: рабочее место модератора"),
    ("sc5", "05_workspace.mp4", None, XF, ""),
    ("sc6", "06_command_center_outro.mp4", None, XF, "Сцена 6: итог в командном центре"),
    ("sec6", "card:" + str(DECK / "sec-6.png"), 1.8, XF, "Как это устроено"),
    ("s1", "card:" + str(DECK / "s-1.png"), 7.0, XF, "Слайд: задача"),
    ("s2", "card:" + str(DECK / "s-2.png"), 8.0, XF, "Слайд: идея"),
    ("s3", "card:" + str(DECK / "s-3.png"), 6.5, XF, "Слайд: стек"),
    ("s4", "card:" + str(DECK / "s-4.png"), 8.5, XF, "Слайд: результаты"),
    ("s5", "card:" + str(DECK / "s-5.png"), 9.0, XF, "Слайд: ограничения"),
    ("s6", "card:" + str(DECK / "s-6.png"), 6.5, XF, "Слайд: роль человека"),
    ("s7", "card:" + str(DECK / "s-7.png"), 6.0, XF, "Слайд: готовый MVP"),
    ("outro", "card:" + str(WORK / "card_outro.png"), 3.6, XF_END, "Финал"),
]


def probe_audio_loudness(path: Path) -> float | None:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
    for line in p.stderr.splitlines()[::-1]:
        if line.strip().startswith("I:"):
            return float(line.split()[1])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--music", default=str(Path.home() / "Downloads" / "zephiramusic-lo-fi-chill-584802.mp3"))
    ap.add_argument("--music-lufs", type=float, default=-20.0, help="громкость подложки без голоса")
    args = ap.parse_args()

    clips = []
    for key, src, secs, xf, title in SEGMENTS:
        if src.startswith("card:"):
            png = Path(src[5:])
            if not png.exists():
                raise SystemExit(f"нет карточки {png}: сначала render_deck.py и assemble.py (карточки бренда)")
            out = DECK / f"{key}.mp4"
            card_clip(png, out, secs)
            clips.append(dict(key=key, path=out, head=0.0, tail=0.0, raw=secs, xf=xf, title=title))
        else:
            p = RAW / src
            if not p.exists():
                raise SystemExit(f"нет записи {p}")
            clips.append(dict(key=key, path=p, head=TRIM_HEAD.get(src, 0.0), tail=TRIM_TAIL.get(src, 0.0), raw=duration(p), xf=xf, title=title))

    starts, t = [], 0.0
    for i, c in enumerate(clips):
        c["used"] = c["raw"] - c["head"] - c["tail"]
        if i > 0:
            t -= c["xf"]          # переход перекрывает конец предыдущего и начало этого
        starts.append(t)
        c["start"] = t
        t += c["used"]
    total = t

    parts = [f"[{i}:v]trim=start={c['head']:.3f}:end={c['raw'] - c['tail']:.3f},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p[t{i}]"
             for i, c in enumerate(clips)]
    prev = "[t0]"
    for i in range(1, len(clips)):
        parts.append(f"{prev}[t{i}]xfade=transition=fade:duration={clips[i]['xf']}:offset={starts[i]:.3f}[v{i}]")
        prev = f"[v{i}]"
    graph = ";".join(parts)

    # главы: только сегменты с названием; граница на середине перехода
    marks = [(c["start"] + (c["xf"] / 2 if i else 0.0), c["title"]) for i, c in enumerate(clips) if c["title"]]
    meta = [";FFMETADATA1", "title=Sentra by LGTM: демонстрация для Grand Mobile"]
    for j, (st, title) in enumerate(marks):
        en = marks[j + 1][0] if j + 1 < len(marks) else total
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(st * 1000)}", f"END={int(en * 1000) - 1}", f"title={title}"]
    (WORK / "chapters_v2.txt").write_text("\n".join(meta) + "\n", encoding="utf-8")

    silent = FINAL / "sentra_demo_grand_mobile_v2_silent.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for c in clips:
        cmd += ["-i", str(c["path"])]
    cmd += ["-i", str(WORK / "chapters_v2.txt"), "-filter_complex", graph, "-map", prev, "-map_metadata", str(len(clips)),
            "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709", "-color_range", "tv", "-r", str(FPS), "-an", "-movflags", "+faststart", str(silent)]
    run(cmd)

    # подложка: трек, зацикленный с перекрытием, подогнанный по длине и по громкости
    music = Path(args.music)
    bed = FINAL / "music_bed.wav"
    mdur = duration(music)
    loops = int(total // (mdur - 4)) + 2
    ins = []
    for _ in range(loops):
        ins += ["-i", str(music)]
    chain, last = [], "[0:a]"
    for i in range(1, loops):
        chain.append(f"{last}[{i}:a]acrossfade=d=4:c1=tri:c2=tri[x{i}]")
        last = f"[x{i}]"
    chain.append(f"{last}atrim=0:{total:.3f},asetpts=PTS-STARTPTS,afade=t=in:st=0:d=2,afade=t=out:st={total - 4:.3f}:d=4[bed]")
    tmp = WORK / "bed_raw.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", *ins, "-filter_complex", ";".join(chain), "-map", "[bed]", "-ar", "48000", "-ac", "2", str(tmp)])
    cur = probe_audio_loudness(tmp)
    gain = args.music_lufs - (cur if cur is not None else -14.8)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-af", f"volume={gain:.2f}dB,alimiter=limit=0.89", "-ar", "48000", str(bed)])

    final = FINAL / "sentra_demo_grand_mobile_v2.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(bed), "-map", "0:v", "-map", "1:a", "-map_metadata", "0",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", "-shortest",
         "-metadata", "comment=Sentra by LGTM demo v2, lofi bed, no voice", str(final)])

    timeline = {"file": str(final.relative_to(FINAL.parent.parent)).replace("\\", "/"), "total_s": round(total, 2),
                "music": {"file": music.name, "source_duration_s": round(mdur, 1), "bed_lufs": args.music_lufs},
                "segments": [{"key": c["key"], "title": c["title"], "src": c["path"].name, "used_s": round(c["used"], 2),
                              "start": round(c["start"], 2), "end": round(c["start"] + c["used"], 2)} for c in clips]}
    (FINAL / "timeline_v2.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"total_s": timeline["total_s"], "file": timeline["file"]}, ensure_ascii=False))
    for s in timeline["segments"]:
        print(f"{s['start']:7.2f} - {s['end']:7.2f}  {s['key']:6s} {s['title']}")


if __name__ == "__main__":
    main()
