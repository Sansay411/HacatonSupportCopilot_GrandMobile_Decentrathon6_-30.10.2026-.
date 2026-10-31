"""Запись настоящего браузера для демо-видео: Edge под управлением Playwright, кадры берутся через CDP screencast.

Почему не встроенная запись Playwright: она кодирует VP8 с потолком 1 Мбит/с, мелкий текст интерфейса на 1080p расплывается.
Здесь каждый кадр сохраняется как JPEG (качество 92), длительность кадра равна интервалу до следующего, затем ffmpeg
собирает постоянные 30 кадров/с в H.264. Ничего не дорисовывается: единственная добавка в кадре это указатель мыши,
который headless-браузер не рисует сам. Он вставляется скриптом на страницу и не меняет ни код, ни стили приложения.
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import random
import subprocess
import time
from pathlib import Path

from playwright.async_api import async_playwright

HOLD_K = 0.72     # коэффициент пауз: версия 4 ускорена для жюри
TYPE_K = 0.65     # скорость набора текста

W, H, FPS = 1920, 1080, 30
ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "demo_video" / "work"
RAW = ROOT / "demo_video" / "raw"

# Указатель и кольцо при нажатии. Popover переносит элемент в верхний слой, иначе указатель прятался бы под <dialog>.
CURSOR_JS = r"""
(() => {
  const css = 'position:fixed;inset:auto;left:0;top:0;width:28px;height:28px;margin:0;padding:0;border:0;background:transparent;'
    + 'overflow:visible;pointer-events:none;transform:translate3d(-80px,-80px,0);color:transparent';
  const make = () => {
    if (document.getElementById('__cur')) return;
    const c = document.createElement('div');
    c.id = '__cur'; c.setAttribute('popover', 'manual'); c.style.cssText = css;
    c.innerHTML = '<svg width="28" height="28" viewBox="0 0 28 28" style="position:absolute;left:0;top:0;filter:drop-shadow(0 1px 2px rgba(0,0,0,.55))">'
      + '<path d="M4 3 L4 21.5 L8.6 17.3 L11.9 24.6 L15 23.2 L11.8 16 L18.4 16 Z" fill="#fff" stroke="#0a0d0c" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    try { c.showPopover(); } catch (e) {}
    window.__cur = c;
  };
  const up = () => { const c = window.__cur; if (c) { try { c.hidePopover(); c.showPopover(); } catch (e) {} } };
  const orig = HTMLDialogElement.prototype.showModal;
  HTMLDialogElement.prototype.showModal = function () { const r = orig.apply(this, arguments); up(); return r; };
  const pos = e => { const c = window.__cur; if (c) c.style.transform = 'translate3d(' + (e.clientX - 4) + 'px,' + (e.clientY - 3) + 'px,0)'; };
  const ring = e => {
    const c = window.__cur; if (!c) return;
    const r = document.createElement('div');
    r.style.cssText = 'position:absolute;left:0;top:0;width:34px;height:34px;margin:-13px 0 0 -13px;border-radius:50%;'
      + 'border:2px solid rgba(47,217,181,.9);box-sizing:border-box;pointer-events:none';
    c.appendChild(r);
    r.animate([{ transform: 'scale(.35)', opacity: .95 }, { transform: 'scale(1.5)', opacity: 0 }], { duration: 480, easing: 'ease-out' }).onfinish = () => r.remove();
  };
  /* без красных волн проверки орфографии браузера под текстом (атрибут поля, на логику приложения не влияет) */
  addEventListener('focusin', e => { const t = e.target; if (t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT')) t.spellcheck = false; }, true);
  addEventListener('mousemove', pos, true);
  addEventListener('mousedown', e => { pos(e); ring(e); }, true);
  if (document.documentElement) make(); else document.addEventListener('DOMContentLoaded', make);
  new MutationObserver(() => { if (!document.getElementById('__cur') && document.documentElement) make(); }).observe(document, { childList: true });
})();
"""


def ease(t: float) -> float:
    return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2


class Rec:
    def __init__(self, base_url: str, *, capture: bool = True, shots: Path | None = None):
        self.base, self.capture = base_url.rstrip("/"), capture
        self.shots = shots
        self.x, self.y = W // 2, H // 2
        self.errors: list[str] = []
        self.marks = {}
        self.requests: list[dict] = []
        self.frames: list[tuple[float, str]] = []
        self._dir: Path | None = None
        self._name = ""
        self._last_rx = 0.0
        self._on = False
        self.clips: list[dict] = []

    # ---------------------------------------------------------------- браузер
    async def open(self):
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(channel="msedge", headless=True,
                                                      args=["--force-device-scale-factor=1", "--disable-features=TranslateUI",
                                                            "--disable-spell-checking"])
        self.ctx = await self.browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1, locale="ru-RU",
                                                  color_scheme="dark", permissions=["clipboard-read", "clipboard-write"])
        await self.ctx.add_init_script(CURSOR_JS)
        self.page = await self.ctx.new_page()
        self.page.on("console", lambda m: self.errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on("requestfailed", lambda r: self.errors.append(f"requestfailed: {r.url} {r.failure}"))

        def on_resp(r):
            u = r.url
            if u.startswith(self.base) and not u.startswith(self.base + "/static"):
                self.requests.append({"method": r.request.method, "path": u[len(self.base):], "status": r.status})
        self.page.on("response", on_resp)
        self.cdp = await self.ctx.new_cdp_session(self.page)
        self.cdp.on("Page.screencastFrame", self._frame)
        # CSP приложения запрещает eval, а wait_for_function вычисляет строку через eval: опрашиваем через CDP-evaluate
        self.page.wait_for_function = self._wait_js

    async def _wait_js(self, expr: str, timeout: float = 10000, **_):
        t0 = time.perf_counter()
        while not await self.page.evaluate(f"Boolean({expr})"):
            if (time.perf_counter() - t0) * 1000 > timeout:
                raise TimeoutError(f"не дождались: {expr[:140]}")
            await asyncio.sleep(0.1)

    async def close(self):
        await self.ctx.close()
        await self.browser.close()
        await self._pw.stop()

    async def goto(self, path_or_url: str, *, wait_fonts: bool = True):
        url = path_or_url if "://" in path_or_url else self.base + path_or_url
        await self.page.goto("about:blank")          # смена только #hash не перезагружает страницу и оставляет старые фильтры
        await self.page.goto(url, wait_until="load")
        if wait_fonts:
            await self.page.evaluate("document.fonts.ready.then(() => true)")
            await self.page.wait_for_timeout(250)
        self.x, self.y = W // 2, H // 2
        await self.page.mouse.move(self.x, self.y)

    # ---------------------------------------------------------------- запись
    def _frame(self, p):
        if not self._on:
            return
        ts = p["metadata"]["timestamp"]
        n = len(self.frames)
        name = f"f{n:06d}.jpg"
        (self._dir / name).write_bytes(base64.b64decode(p["data"]))
        self.frames.append((ts, name))
        self._last_rx = time.perf_counter()
        asyncio.get_running_loop().create_task(self.cdp.send("Page.screencastFrameAck", {"sessionId": p["sessionId"]}))

    def mark(self, label: str):
        """Отметка момента записи в секундах от начала клипа: по ним монтаж ставит реплики озвучки."""
        self.marks.setdefault(self._name, {})[label] = round(time.perf_counter() - self._t0, 2)

    async def start(self, name: str):
        self._name = name
        if not self.capture:
            self._t0 = time.perf_counter()
            return
        self._dir = WORK / "frames" / name
        if self._dir.exists():
            for f in self._dir.glob("*"):
                f.unlink()
        self._dir.mkdir(parents=True, exist_ok=True)
        self.frames = []
        self._on = True
        self._t0 = time.perf_counter()
        await self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": W, "maxHeight": H, "everyNthFrame": 1})
        # статичная страница не даёт кадров: подталкиваем отрисовку сдвигом указателя на пиксель
        await self.page.mouse.move(self.x + 1, self.y)
        await self.page.mouse.move(self.x, self.y)
        await self.page.wait_for_timeout(150)

    async def stop(self) -> dict:
        info = {"name": self._name, "wall_s": round(time.perf_counter() - self._t0, 2)}
        if not self.capture:
            self.clips.append(info)
            return info
        await self.page.wait_for_timeout(200)
        await self.cdp.send("Page.stopScreencast")
        self._on = False
        end_ts = self.frames[-1][0] + (time.perf_counter() - self._last_rx)
        lines = ["ffconcat version 1.0"]
        gaps = []
        for i, (ts, name) in enumerate(self.frames):
            nxt = self.frames[i + 1][0] if i + 1 < len(self.frames) else end_ts
            d = max(1 / 120, nxt - ts)
            gaps.append(d)
            lines += [f"file '{name}'", f"duration {d:.5f}"]
        lines.append(f"file '{self.frames[-1][1]}'")
        (self._dir / "list.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        RAW.mkdir(parents=True, exist_ok=True)
        out = RAW / f"{self._name}.mp4"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt",
               "-vf", f"fps={FPS},scale={W}:{H}:flags=lanczos+accurate_rnd:in_range=full:out_range=limited:in_color_matrix=bt601:out_color_matrix=bt709,format=yuv420p",
               "-c:v", "libx264", "-preset", "slow", "-crf", "15", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
               "-color_trc", "bt709", "-color_range", "tv", "-movflags", "+faststart", str(out)]
        await asyncio.to_thread(subprocess.run, cmd, cwd=self._dir, check=True)
        info.update(frames=len(self.frames), media_s=round(sum(gaps), 2), max_gap_s=round(max(gaps), 2),
                    mean_fps=round(len(self.frames) / max(0.01, sum(gaps)), 1), file=str(out.relative_to(ROOT)).replace("\\", "/"))
        self.clips.append(info)
        return info

    async def shot(self, name: str):
        """Снимок для репетиции и проверки; в видео не попадает."""
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            await self.page.screenshot(path=str(self.shots / f"{name}.png"))

    # ---------------------------------------------------------------- действия
    async def hold(self, s: float):
        # паузы длиннее полсекунды сокращены: зрителю-судье нужен темп, а не ожидание
        await self.page.wait_for_timeout(int((s * HOLD_K if s >= 0.5 else s) * 1000))

    async def glide(self, x: float, y: float, dur: float = 0.8, arc: float = 1.0):
        x0, y0 = self.x, self.y
        dist = math.hypot(x - x0, y - y0)
        if dist < 2:
            return
        dur = max(dur, min(1.8, dist / 2600))
        bend = min(46, dist * 0.07) * arc * random.choice((-1, 1))
        nx, ny = (-(y - y0) / dist, (x - x0) / dist)
        t0 = time.perf_counter()
        while True:
            f = (time.perf_counter() - t0) / dur
            if f >= 1:
                break
            e = ease(f)
            off = bend * math.sin(math.pi * e)
            await self.page.mouse.move(x0 + (x - x0) * e + nx * off, y0 + (y - y0) * e + ny * off)
            await asyncio.sleep(0.006)
        await self.page.mouse.move(x, y)
        self.x, self.y = x, y

    async def _center(self, loc, fx=0.5, fy=0.5):
        await loc.first.wait_for(state="visible", timeout=10000)
        box = await loc.first.bounding_box()
        if box is None:
            raise RuntimeError("нет рамки у элемента")
        return box["x"] + box["width"] * fx, box["y"] + box["height"] * fy

    async def to(self, loc, dur: float = 0.8, fx=0.5, fy=0.5):
        x, y = await self._center(loc, fx, fy)
        await self.glide(x, y, dur)

    async def click(self, loc, dur: float = 0.8, fx=0.5, fy=0.5, after: float = 0.35):
        await self.to(loc, dur, fx, fy)
        await self.hold(0.12)
        await self.page.mouse.down()
        await self.hold(0.07)
        await self.page.mouse.up()
        await self.hold(after)

    async def type(self, text: str, per_char: float = 0.032):
        per_char *= TYPE_K
        for ch in text:
            await self.page.keyboard.type(ch)
            await asyncio.sleep(per_char * random.uniform(0.55, 1.5) + (0.12 if ch in ".,:;" else 0))

    async def scroll(self, dy: float, dur: float = 1.4, at: tuple[float, float] | None = None):
        if at:
            await self.glide(at[0], at[1], 0.6)
        t0, done = time.perf_counter(), 0.0
        while True:
            f = (time.perf_counter() - t0) / dur
            target = dy if f >= 1 else dy * ease(f)
            step = target - done
            if abs(step) >= 0.5:
                await self.page.mouse.wheel(0, step)
                done += step
            if f >= 1:
                break
            await asyncio.sleep(0.008)

    async def scroll_into(self, loc, band: float = 0.30, dur: float = 1.3, at: tuple[float, float] | None = None):
        """Плавно прокрутить так, чтобы верх элемента оказался на доле `band` высоты окна."""
        await loc.first.wait_for(state="attached", timeout=10000)
        box = await loc.first.bounding_box()
        want = H * band
        dy = box["y"] - want
        if abs(dy) > 6:
            await self.scroll(dy, dur, at)

    def dump_log(self, path: Path, extra: dict | None = None):
        path.write_text(json.dumps({"clips": self.clips, "errors": self.errors, "requests": self.requests, **(extra or {})},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
