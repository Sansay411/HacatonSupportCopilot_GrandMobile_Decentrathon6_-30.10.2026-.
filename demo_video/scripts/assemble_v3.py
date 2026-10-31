"""Монтаж версии 3: озвучка (ElevenLabs, файлы в voice/<lang>/) + музыка, картинка подгоняется под голос.

    python demo_video/scripts/dl... (озвучка уже скачана) ; python demo_video/scripts/assemble_v3.py --lang ru

Принцип: блок озвучки режется на абзацы по самым длинным паузам; абзац начинается, когда картинка доходит до «точки» (beats),
а если предыдущий абзац ещё не закончился, на этой точке кадр замирает (стоп-кадр записи) до конца реплики.
Слайды растягиваются под длину реплики. Музыка прижимается под голос, итог нормализуется до -16 LUFS.
Выход: final/sentra_demo_grand_mobile_v3_<lang>.mp4, final/timeline_v3_<lang>.json.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from assemble import FINAL, FPS, RAW, TRIM_HEAD, TRIM_TAIL, WORK, card_clip, duration, run

DV = FINAL.parent
DECK = WORK / "deck"
V3 = WORK / "v3"
XF, XF_PLAQUE, XF_END = 0.5, 0.4, 0.8
GAP = 0.3

# сцена -> (файл записи, блок озвучки, число абзацев, точки начала абзацев в секундах сцены после обрезки)
SCENES = {
    "sc1": ("01_command_center.mp4", "A", 2, [None, 3.0]),            # абзац 1 звучит ещё на плашках (абсолютное время 1,0)
    "sc2": ("02_triage.mp4", "B", 3, [1.7, 9.0, 23.0]),
    "sc3": ("03_safety.mp4", "C", 5, [1.9, 9.9, 24.9, 34.9, 38.9]),
    "sc4": ("04_escalation.mp4", "D", 3, [2.2, 9.5, 24.0]),
    "sc5": ("05_workspace.mp4", "E", 4, [2.05, 14.05, 24.05, 36.05]),
    "sc6": ("06_command_center_outro.mp4", "F", 1, [1.0]),
}
SLIDES = [("s1", "G1", "Слайд: задача"), ("s2", "G2", "Слайд: идея"), ("s3", "G3", "Слайд: стек"), ("s4", "G4", "Слайд: результаты"),
          ("s5", "G5", "Слайд: ограничения"), ("s6", "G6", "Слайд: роль человека"), ("s7", "G7", "Слайд: готовый MVP")]
TITLES = {"sc1": "Сцена 1: командный центр", "sec2": "Часть 1: разбор настоящего обращения", "sec3": "Часть 2: защита от выдуманного",
          "sec4": "Часть 3: обязательная эскалация", "sec5": "Часть 4: рабочее место модератора", "sc6": "Сцена 6: итог в командном центре",
          "sec6": "Как это устроено", "outro": "Финал", "intro": "Титул", "pl1": "Возможности Sentra"}


def split_paragraphs(src: Path, n: int, out_dir: Path) -> list[tuple[Path, float]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    total = duration(src)
    if n == 1:
        return [(src, total)]
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", "silencedetect=noise=-38dB:d=0.28", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", p.stderr)]
    sil = [(s, e) for s, e in zip(starts, ends) if 0.4 < s < total - 0.4]
    cuts = sorted(sorted(sil, key=lambda x: x[1] - x[0], reverse=True)[: n - 1])
    pieces, prev = [], 0.0
    for i, (s, e) in enumerate(cuts + [(total, total)]):
        a, b = prev, (s + e) / 2 if i < len(cuts) else total
        out = out_dir / f"{src.stem}_{i + 1}.wav"
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(src), "-ar", "48000", "-ac", "1", str(out)])
        pieces.append((out, b - a))
        prev = e if i < len(cuts) else total
    return pieces


def plan_scene(beats, durs, pre_end, used):
    off, prev_end, holds, starts = 0.0, pre_end, [], []
    for i, d in enumerate(durs):
        if beats[i] is None:
            starts.append(None)
            continue
        want = beats[i] + off
        start = max(want, prev_end + (GAP if prev_end > -1 else 0))
        if start > want + 1e-6:
            holds.append((beats[i], start - want))
            off += start - want
        starts.append(start)
        prev_end = start + d
    total = used + off
    end_hold = max(0.0, prev_end + 0.5 - total)
    return holds, end_hold, starts, total + end_hold


def build_scene(raw: Path, key: str, holds, end_hold, head, tail) -> Path:
    out = V3 / f"{key}.mp4"
    rd = duration(raw)
    a, b = head, rd - tail
    cuts = [0.0] + [h[0] for h in holds] + [b - a]
    pieces = []
    for j in range(len(cuts) - 1):
        hold = holds[j][1] if j < len(holds) else end_hold
        pieces.append(f"[0:v]trim=start={a + cuts[j]:.3f}:end={a + cuts[j + 1]:.3f},setpts=PTS-STARTPTS,fps={FPS}"
                      + (f",tpad=stop_mode=clone:stop_duration={hold:.3f}" if hold > 0.01 else "") + f"[p{j}]")
    g = ";".join(pieces) + ";" + "".join(f"[p{j}]" for j in range(len(cuts) - 1)) + f"concat=n={len(cuts) - 1}:v=1:a=0[v]"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-filter_complex", g, "-map", "[v]", "-c:v", "libx264", "-preset", "fast", "-crf", "12",
         "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", str(out)])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="ru")
    ap.add_argument("--music", default=str(Path.home() / "Downloads" / "zephiramusic-lo-fi-chill-584802.mp3"))
    ap.add_argument("--music-lufs", type=float, default=-24.0)
    args = ap.parse_args()
    vdir = DV / "voice" / args.lang
    V3.mkdir(parents=True, exist_ok=True)

    paras = {blk: [(vdir / "par" / f"{blk}{i}.mp3", duration(vdir / "par" / f"{blk}{i}.mp3")) for i in range(1, n + 1)]
             for _, blk, n, _ in SCENES.values()}
    vo = {k: (vdir / f"{k}.mp3", duration(vdir / f"{k}.mp3")) for k in ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "Z"]}
    for k, v in paras.items():
        print(k, [round(d, 1) for _, d in v])

    clips, audio = [], []          # audio: (файл, абсолютное время начала)
    def card(key, png, secs, xf, title=""):
        out = V3 / f"{key}.mp4"
        card_clip(png, out, secs)
        clips.append(dict(key=key, path=out, used=secs, xf=xf, title=title))

    card("intro", WORK / "card_intro.png", 2.8, 0.0, TITLES["intro"])
    card("pl1", DECK / "plaques-1.png", 2.4, 0.6, TITLES["pl1"])
    card("pl2", DECK / "plaques-2.png", 2.0, XF_PLAQUE)
    card("pl3", DECK / "plaques-3.png", 2.0, XF_PLAQUE)
    card("pl4", DECK / "plaques-4.png", 3.0, XF_PLAQUE)
    audio.append((paras["A"][0][0], 1.0))
    pre_end_abs = 1.0 + paras["A"][0][1]

    order = ["sc1", "sec2", "sc2", "sec3", "sc3", "sec4", "sc4", "sec5", "sc5", "sc6"]
    plans = {}
    for key in order:
        if key.startswith("sec"):
            card(key, DECK / f"sec-{key[3:]}.png", 1.6, XF, TITLES[key])
            continue
        fname, blk, n, beats = SCENES[key]
        raw = RAW / fname
        head, tail = TRIM_HEAD.get(fname, 0.0), TRIM_TAIL.get(fname, 0.0)
        used = duration(raw) - head - tail
        durs = [d for _, d in paras[blk]]
        start_abs = None
        pre_end = -10.0
        if key == "sc1":
            # старт сцены на итоговой шкале: после титула и плашек (как в версии 2)
            start_abs = 9.9
            pre_end = pre_end_abs - start_abs
        holds, end_hold, starts, total = plan_scene(beats, durs, pre_end, used)
        path = build_scene(raw, key, holds, end_hold, head, tail)
        clips.append(dict(key=key, path=path, used=total, xf=XF, title=TITLES.get(key, "")))
        plans[key] = (blk, starts, holds, end_hold)

    card("sec6", DECK / "sec-6.png", 1.8, XF, TITLES["sec6"])
    for key, blk, title in SLIDES:
        n = int(key[1])
        card(key, DECK / f"s-{n}.png", round(vo[blk][1] + 0.9, 2), XF, title)
    card("outro", WORK / "card_outro.png", round(vo["Z"][1] + 0.9, 2), XF_END, TITLES["outro"])

    t, starts_abs = 0.0, {}
    for i, c in enumerate(clips):
        if i:
            t -= c["xf"]
        c["start"] = t
        starts_abs[c["key"]] = t
        t += c["used"]
    total = t

    for key, (blk, starts, holds, end_hold) in plans.items():
        for i, st in enumerate(starts):
            if st is not None:
                audio.append((paras[blk][i][0], starts_abs[key] + st))
    for key, blk, _ in SLIDES:
        audio.append((vo[blk][0], starts_abs[key] + 0.4))
    audio.append((vo["Z"][0], starts_abs["outro"] + 0.3))

    parts = [f"[{i}:v]setpts=PTS-STARTPTS,fps={FPS},format=yuv420p[t{i}]" for i in range(len(clips))]
    prev = "[t0]"
    for i in range(1, len(clips)):
        parts.append(f"{prev}[t{i}]xfade=transition=fade:duration={clips[i]['xf']}:offset={clips[i]['start']:.3f}[v{i}]")
        prev = f"[v{i}]"
    marks = [(c["start"] + (c["xf"] / 2 if i else 0.0), c["title"]) for i, c in enumerate(clips) if c["title"]]
    meta = [";FFMETADATA1", "title=Sentra by LGTM: демонстрация для Grand Mobile"]
    for j, (st, title) in enumerate(marks):
        en = marks[j + 1][0] if j + 1 < len(marks) else total
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(st * 1000)}", f"END={int(en * 1000) - 1}", f"title={title}"]
    (V3 / "chapters.txt").write_text("\n".join(meta) + "\n", encoding="utf-8")

    silent = FINAL / f"sentra_demo_grand_mobile_v3_{args.lang}_silent.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for c in clips:
        cmd += ["-i", str(c["path"])]
    cmd += ["-i", str(V3 / "chapters.txt"), "-filter_complex", ";".join(parts), "-map", prev, "-map_metadata", str(len(clips)),
            "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709", "-color_range", "tv", "-r", str(FPS), "-an", "-movflags", "+faststart", str(silent)]
    run(cmd)

    # голос: все реплики на своих местах, потом нормализация
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for f, _ in audio:
        cmd += ["-i", str(f)]
    chain = [f"[{i}:a]aformat=sample_rates=48000:channel_layouts=mono,adelay={int(st * 1000)}:all=1[a{i}]" for i, (_, st) in enumerate(audio)]
    chain.append("".join(f"[a{i}]" for i in range(len(audio))) + f"amix=inputs={len(audio)}:normalize=0:duration=longest,"
                 f"highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=7,apad=whole_dur={total:.2f},atrim=0:{total:.2f}[v]")
    voice = V3 / "voice_track.wav"
    run(cmd + ["-filter_complex", ";".join(chain), "-map", "[v]", "-ar", "48000", "-ac", "1", str(voice)])

    # музыка: зацикленный трек под длину ролика
    music = Path(args.music)
    mdur = duration(music)
    loops = int(total // (mdur - 4)) + 2
    ins, ch, last = [], [], "[0:a]"
    for _ in range(loops):
        ins += ["-i", str(music)]
    for i in range(1, loops):
        ch.append(f"{last}[{i}:a]acrossfade=d=4:c1=tri:c2=tri[x{i}]")
        last = f"[x{i}]"
    ch.append(f"{last}atrim=0:{total:.3f},asetpts=PTS-STARTPTS,afade=t=in:st=0:d=2,afade=t=out:st={total - 4:.3f}:d=4[bed]")
    bed_raw = V3 / "bed_raw.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", *ins, "-filter_complex", ";".join(ch), "-map", "[bed]", "-ar", "48000", "-ac", "2", str(bed_raw)])
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(bed_raw), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
    cur = float([l.split()[1] for l in p.stderr.splitlines() if l.strip().startswith("I:")][-1])
    gain = args.music_lufs - cur

    mix = V3 / "mix.wav"
    fg = (f"[1:a]volume={gain:.2f}dB[m];[0:a]asplit=2[vk][vm];[m][vk]sidechaincompress=threshold=0.015:ratio=9:attack=20:release=600[duck];"
          f"[duck]aformat=channel_layouts=stereo[d2];[vm]aformat=channel_layouts=stereo[v2];[d2][v2]amix=inputs=2:normalize=0,"
          f"loudnorm=I=-16:TP=-1.5:LRA=9[o]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(voice), "-i", str(bed_raw), "-filter_complex", fg, "-map", "[o]", "-ar", "48000", str(mix)])

    final = FINAL / f"sentra_demo_grand_mobile_v3_{args.lang}.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(mix), "-map", "0:v", "-map", "1:a", "-map_metadata", "0", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", "-shortest", str(final)])

    tl = {"file": str(final.relative_to(DV.parent)).replace("\\", "/"), "total_s": round(total, 2),
          "segments": [{"key": c["key"], "title": c["title"], "start": round(c["start"], 2), "end": round(c["start"] + c["used"], 2)} for c in clips],
          "voice": [{"file": Path(f).name, "start": round(st, 2)} for f, st in audio],
          "holds": {k: {"at_s": [round(h[0], 1) for h in v[2]], "hold_s": [round(h[1], 1) for h in v[2]], "end_hold_s": round(v[3], 1)} for k, v in plans.items()}}
    (FINAL / f"timeline_v3_{args.lang}.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"total_s": tl["total_s"], "holds": tl["holds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
