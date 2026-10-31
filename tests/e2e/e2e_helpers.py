"""Общие классы сквозных тестов: сервер в подпроцессе и страница с журналом ошибок консоли."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_RULES = ROOT / "tests/fixtures/rules_mini.json"
_HTTP_NOISE = re.compile(r"Failed to load resource: the server responded with a status of ([45]\d\d)")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """Процесс uvicorn с отдельной папкой данных и базой; restart() имитирует перезапуск сервера."""

    def __init__(self, tmp, *, rules=True, db="sentra.db"):
        self.tmp, self.port = tmp, _free_port()
        self.data = tmp / "data"
        self.data.mkdir(exist_ok=True)
        if rules:
            shutil.copy(FIXTURE_RULES, self.data / "rules.json")
        self.env = dict(os.environ, COPILOT_DATA=str(self.data), COPILOT_MODELS=str(tmp / "no_models"),
                        COPILOT_DB=str(tmp / db), COPILOT_METRICS=str(ROOT / "reports/metrics.json"),
                        COPILOT_TEMPLATES=str(ROOT / "tests/fixtures/template_summary_synthetic.json"),
                        COPILOT_TEMPLATES_PRIVATE=str(tmp / "нет.json"), PYTHONIOENCODING="utf-8")
        for k in ("COPILOT_LLM_BASE_URL", "COPILOT_LLM_API_KEY", "COPILOT_LLM_MODEL"):
            self.env.pop(k, None)
        self.proc = None
        self.log = open(tmp / f"server-{self.port}.log", "wb")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "copilot.api:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=ROOT, env=self.env, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + 45
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("сервер завершился при запуске, см. лог " + self.log.name)
            try:
                urllib.request.urlopen(self.url + "/health", timeout=1).read()
                return self
            except OSError:
                time.sleep(0.25)
        raise RuntimeError("сервер не поднялся за 45 секунд")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def restart(self):
        self.stop()
        return self.start()

    def get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def post(self, path, body, headers=None):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))


class Page:
    """Страница с журналом ошибок консоли: любая ошибка JS, запроса или консоли проваливает тест."""

    def __init__(self, browser, base_url):
        self.ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU",
                                       permissions=["clipboard-read", "clipboard-write"], base_url=base_url)
        # шрифты Google не нужны для проверки логики, а сеть в тестах не должна влиять на результат
        self.ctx.route("**/fonts.googleapis.com/**", lambda r: r.fulfill(status=200, content_type="text/css", body=""))
        self.ctx.route("**/fonts.gstatic.com/**", lambda r: r.fulfill(status=200, body=""))
        self.page = self.ctx.new_page()
        self.errors: list[str] = []
        self.dialogs: list[str] = []
        self.http_noise: list[str] = []      # 4xx и 5xx на заведомо плохой ввод или режим сбоя: браузер пишет их в консоль сам
        self.page.on("console", self._console)
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on("requestfailed", lambda r: None if "ERR_ABORTED" in str(r.failure) else self.errors.append(f"requestfailed: {r.url} {r.failure}"))
        self.page.on("response", lambda r: self.errors.append(f"http {r.status}: {r.url}") if r.status >= 500 and r.status != 503 else None)
        self.page.on("dialog", lambda d: (self.dialogs.append(d.message), d.dismiss()))

    def _console(self, m):
        if m.type != "error":
            return
        hit = _HTTP_NOISE.search(m.text)
        if hit:
            self.http_noise.append(hit.group(1))
        else:
            self.errors.append(f"console.{m.type}: {m.text}")

    def close(self):
        self.ctx.close()
