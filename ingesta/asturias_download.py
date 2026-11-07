"""Descarga cortés del formulario real, con caché local y control de robots."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
import re
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from ingesta.common import TZ
from ingesta.parsers.asturias import POST_URL, inspect_html

USER_AGENT = "farmacias-guardia/0.1 (+https://github.com/Alfonsorm14/farmacias-guardia)"
ORIGIN = "https://www.farmasturias.org"


def robots_policy(text: str, url: str) -> tuple[bool, float]:
    """Reglas RFC 9309 (* y $); urllib.robotparser no interpreta esos patrones."""
    groups = []
    agents, rules, delay = [], [], 1.1
    active_rules = False
    for raw in text.splitlines() + ["User-agent: __fin__"]:
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (v.strip() for v in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if active_rules:
                groups.append((agents, rules, delay))
                agents, rules, delay, active_rules = [], [], 1.1, False
            agents.append(value.lower())
        elif agents:
            active_rules = True
            if key in ("allow", "disallow") and value:
                rules.append((key, value))
            elif key == "crawl-delay":
                delay = max(1.1, float(value))
    matches = [(max((len(a) for a in agents if a != "*" and a in USER_AGENT.lower()), default=0), rules, delay)
               for agents, rules, delay in groups
               if "*" in agents or any(a in USER_AGENT.lower() for a in agents)]
    if not matches:
        return True, 1.1
    best = max(x[0] for x in matches)
    path = urllib.parse.urlsplit(url).path
    query = urllib.parse.urlsplit(url).query
    target = path + ("?" + query if query else "")
    applicable = []
    wait = 1.1
    for score, rules, delay in matches:
        if score != best:
            continue
        wait = max(wait, delay)
        for key, pattern in rules:
            end = pattern.endswith("$")
            pattern = pattern[:-1] if end else pattern
            expression = re.escape(pattern).replace(r"\*", ".*") + ("$" if end else "")
            if re.match(expression, target):
                applicable.append((len(pattern.replace("*", "")), key == "allow"))
    return (max(applicable)[1] if applicable else True), wait


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError(f"Redirección no inspeccionada: {newurl}")


class Client:
    def __init__(self, cache: str | Path, ttl: float = 21600):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl
        self.delay = 1.1
        self.lock = threading.Lock()
        self.opener = urllib.request.build_opener(NoRedirect())
        self.robots = self._request(ORIGIN + "/robots.txt").decode("utf-8-sig")

    def _request(self, url: str, data: bytes | None = None) -> bytes:
        if urllib.parse.urlsplit(url).netloc != "www.farmasturias.org" or not url.startswith(ORIGIN + "/"):
            raise ValueError("Origen no inspeccionado")
        key = hashlib.sha256(url.encode() + b"\0" + (data or b"")).hexdigest()
        path = self.cache / (key + ".body")
        if path.exists() and time.time() - path.stat().st_mtime < self.ttl:
            return path.read_bytes()
        with self.lock:
            stamp = self.cache / "last_request"
            last = float(stamp.read_text()) if stamp.exists() else 0
            time.sleep(max(0, self.delay - (time.time() - last)))
            # Se guarda antes de enviar incluso cuando falla la conexión. Sin reintentos.
            stamp.write_text(str(time.time()))
        req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
        try:
            with self.opener.open(req, timeout=40) as response:
                content = response.read()
        except urllib.error.HTTPError as exc:
            # La evidencia del error se conserva separada de las respuestas válidas.
            path.with_suffix(".error").write_bytes(exc.read())
            raise
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(content)
        tmp.replace(path)
        return content

    def day(self, day: date) -> bytes:
        allowed, self.delay = robots_policy(self.robots, POST_URL)
        if not allowed:
            raise PermissionError("robots.txt prohíbe el buscador; descarga detenida")
        body = urllib.parse.urlencode({"busqueda": "1", "Fecha": day.strftime("%d/%m/%Y"),
            "txtMunicipio": "", "txtLocalidad": "", "btnBuscar": "Buscar"}).encode("ascii")
        try:
            content = self._request(POST_URL, body)
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Asturias {day}: POST {POST_URL}; {body.decode()}: {exc}") from exc
        inspect_html(content, day)
        return content


def download(directory: str | Path, *, start: date, end: date | None = None) -> dict:
    """Sin fin explícito, avanza hasta el primer día no publicado (no lo rellena)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    client = Client(directory / "cache")
    day = start
    report = {"method": "POST", "url": POST_URL, "dates": [], "empty_dates": [],
              "municipalities": [], "localities": [], "retrieved_at": datetime.now(TZ).isoformat()}
    municipalities, localities = set(), set()
    # Cuatro consultas como máximo en curso; el inicio de TODAS se separa con
    # el mismo candado y reloj. Una única instancia del comando por caché.
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {}
        ready = {}
        expected = start
        found_empty = False
        for _ in range(4):
            if end is None or day <= end:
                pending[pool.submit(client.day, day)] = day
                day += timedelta(days=1)
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                current = pending.pop(future)
                content = future.result()
                page = inspect_html(content, current)
                ready[current] = (content, page)
                if not page.rows and end is None:
                    found_empty = True
            while expected in ready:
                content, page = ready.pop(expected)
                target = directory / f"{expected}.html"
                temporary = target.with_suffix(".tmp")
                temporary.write_bytes(content)
                temporary.replace(target)
                if page.rows:
                    report["dates"].append(str(expected))
                    municipalities.update(r["MunicipioGuardias"] for r in page.rows)
                    localities.update(r["LocalidadGuardias"] for r in page.rows)
                else:
                    report["empty_dates"].append(str(expected))
                report["municipalities"] = sorted(municipalities)
                report["localities"] = sorted(localities)
                report["options"] = page.options
                (directory / "coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"Asturias {expected}: {len(page.rows)} fichas", flush=True)
                if not page.rows and end is None:
                    return report
                expected += timedelta(days=1)
            while len(pending) < 4 and not found_empty and (end is None or day <= end):
                pending[pool.submit(client.day, day)] = day
                day += timedelta(days=1)
    return report
