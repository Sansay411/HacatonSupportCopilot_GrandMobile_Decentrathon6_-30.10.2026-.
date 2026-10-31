"""Проверка готового видео: параметры, полное декодирование, чёрные кадры, замирания, контрольные кадры по сценам.

    python demo_video/scripts/verify_video.py [файл]
Результат печатается и пишется в demo_video/final/video_checks.json. Контрольные кадры: demo_video/work/check_frames/.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINAL, WORK = ROOT / "demo_video" / "final", ROOT / "demo_video" / "work"
video = Path(sys.argv[1]) if len(sys.argv) > 1 else FINAL / "sentra_demo_grand_mobile.mp4"


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main():
    res: dict = {"file": str(video.relative_to(ROOT)).replace("\\", "/"), "size_mb": round(video.stat().st_size / 1e6, 1)}
    p = json.loads(sh(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)]).stdout)
    v = [s for s in p["streams"] if s["codec_type"] == "video"][0]
    res["video"] = {"codec": v["codec_name"], "profile": v.get("profile"), "w": v["width"], "h": v["height"], "fps": v["r_frame_rate"],
                    "pix_fmt": v["pix_fmt"], "duration_s": round(float(p["format"]["duration"]), 2),
                    "bitrate_mbps": round(int(p["format"]["bit_rate"]) / 1e6, 2)}
    res["audio_streams"] = len([s for s in p["streams"] if s["codec_type"] == "audio"])
    res["chapters"] = len(json.loads(sh(["ffprobe", "-v", "error", "-show_chapters", "-of", "json", str(video)]).stdout)["chapters"])
    # полное декодирование без вывода: любые ошибки потока попадут в stderr
    dec = sh(["ffmpeg", "-v", "error", "-i", str(video), "-f", "null", "-"])
    res["decode_errors"] = [l for l in dec.stderr.splitlines() if l.strip()]
    # чёрные кадры
    bl = sh(["ffmpeg", "-i", str(video), "-vf", "blackdetect=d=0.2:pix_th=0.06", "-an", "-f", "null", "-"]).stderr
    res["black_segments"] = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", bl)
    # полностью неподвижные участки (даже указатель стоит) дольше 4,5 с: допустимы как пауза на чтение, но их надо знать
    fz = sh(["ffmpeg", "-i", str(video), "-vf", "freezedetect=n=-80dB:d=4.5", "-an", "-f", "null", "-"]).stderr
    starts = re.findall(r"freeze_start: ([\d.]+)", fz)
    ends = re.findall(r"freeze_end: ([\d.]+)", fz)
    res["frozen_segments_over_4_5s"] = [{"from": float(a), "to": float(b)} for a, b in zip(starts, ends)]
    # контрольные кадры: середина каждой сцены и границы переходов
    tl = json.loads((FINAL / "timeline.json").read_text(encoding="utf-8"))
    out_dir = WORK / "check_frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.png"):
        f.unlink()
    frames = []
    for i, s in enumerate(tl["scenes"]):
        for tag, t in (("mid", (s["from"] + s["to"]) / 2), ("end", s["to"] - 0.4)):
            name = f"{i:02d}_{tag}.png"
            sh(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", str(out_dir / name)])
            frames.append(name)
    res["check_frames"] = frames
    res["ok"] = not res["decode_errors"] and not res["black_segments"] and res["audio_streams"] == 0 \
        and res["video"]["w"] == 1920 and res["video"]["h"] == 1080 and res["video"]["codec"] == "h264"
    (FINAL / "video_checks.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
