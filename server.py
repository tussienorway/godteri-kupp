"""Lokal app: godteritilbud under en prisgrense, hentet fra eTilbudsavis (Tjek).

Kjør: python server.py
Åpne: http://127.0.0.1:8765
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE_PATH = ROOT / "cache" / "offers.json"
PORT = 8765
HOST = "127.0.0.1"
MAX_PAGES = 3
PAGE_SIZE = 100
CACHE_TTL_S = 30 * 60
UA = "GodteriKupp/1.0 (lokal personlig app)"
IMAGE_HOST = "https://image-transformer-api.tjek.com/"

QUERIES = [
    "godteri",
    "smågodt",
    "sjokolade",
    "lakris",
    "karamell",
    "haribo",
    "nidar",
    "freia",
    "twist",
    "snickers",
    "kinder",
    "malaco",
    "drops",
    "seigmenn",
    "tyggegummi",
    "bounty",
    "twix",
    "halloween",
    "daim",
    "kvikk lunsj",
]

# Treff i varenavnet. Korte merker er ordgrenset. «skum» er ordgrenset så «skummelt» ikke treffer.
CANDY_RE = re.compile(
    r"godte|sjokolade|lakris|karamell|bolsje|drops|seigmenn|vingummi|marshmallow|"
    r"tyggis|tyggegummi|sukkertøy|sukkertoy|candy|sweets?|haribo|nidar|freia|"
    r"\btwist\b|snickers|\bbounty\b|\btwix\b|kit\s?kat|kvikk|\bnon\s?stop\b|"
    r"\bsmash\b|\bstratos\b|\bhobby\b|malaco|smørbukk|smorbukk|\bkinder\b|"
    r"skittles|wine\s?gums?|lakrids|fruktisar|gottes|\bdaim\b|\bjapp\b|\blion\b|"
    r"toblerone|after eight|m&m|party mix|smågodt|smagodt|godis|"
    r"påskeegg|paseegg|\bskum\b|\bgel[eé]\b|\bmars\b|marsipan|\bjelly\b|"
    r"toffifee|toffee|lakrisal|fruit dips|dippies",
    re.IGNORECASE,
)

# Mat og drikke som ofte nevner sjokolade, men ikke er godteri.
EXCLUDE_RE = re.compile(
    r"sjokolademelk|kakaomelk|yoghurt|youghurt|pudding|iskrem|\bis\b|"
    r"ispinne|fløte|pålegg|nutella|chips|potetgull|nøtt|peanøtt|"
    r"\bbrus\b|\bøl\b|\bvin\b|\bsaft\b|juice|\bkaffe\b|kakemiks|frokost|"
    r"pizza|grandiosa|pølse|\bost\b|\bmelk\b|smoothie|kjeks|\bkake\b|"
    r"boller|\bbrød\b|knekkebrød|vafler|sjokoladesaus|kokesjokolade|"
    r"bake|kakao\b|pulver|dressing|müsli|musli|havregryn|"
    r"donut|proteinbar|halslinser|halstablett|\btoddy\b",
    re.IGNORECASE,
)

# Pynt, tekstil og oppsamlingsutstyr som ligger i samme avis som godteriet.
NONFOOD_RE = re.compile(
    r"halskjede|bøtte|kostyme|polyester|lysende|edderkopp|\bpynt\b|"
    r"julepynt|ledlys|godteribolle|\bbolle\b|"
    r"serviett|stearin|ballong|peruk|tekstil|løpelengde|ansiktsmaling|"
    r"\bsminke\b|tallerk|verktøy|spøkelse",
    re.IGNORECASE,
)

# Sjokoladeplater som har «kake» i navnet, og derfor ikke skal ut.
BAR_RE = re.compile(
    r"sjokoladekake|kvikk\s*lunsj|\bsmash\b|\bstratos\b|\bhobby\b|\btwist\b|"
    r"\bfreia\b|\bnidar\b|\bdaim\b|\bjapp\b|\blion\b|\bbounty\b|snickers|"
    r"\btwix\b|\bmars\b|kit\s?kat|after eight|toblerone",
    re.IGNORECASE,
)

STORE_COLORS = {
    "REMA 1000": "#e30613",
    "KIWI": "#2f9e44",
    "Extra": "#d23732",
    "MENY": "#e4002b",
    "Meny": "#e4002b",
    "SPAR": "#d62828",
    "Joker": "#0b7a52",
    "Coop Prix": "#c99212",
    "Coop Mega": "#0b5e56",
    "Obs": "#004993",
    "Bunnpris": "#c9a227",
    "Europris": "#e10600",
    "Nille": "#7a1f6d",
    "Normal": "#111111",
    "Matkroken": "#1f6b4a",
    "Gigaboks": "#5b3a29",
}

_lock = threading.Lock()
_state = {
    "ready": False,
    "loading": False,
    "error": None,
    "fetched_at": None,
    "offers": [],
    "stats": {},
}
_api_key: str | None = None


def http_get(url: str, headers: dict | None = None, timeout: int = 30) -> bytes:
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()


def discover_api_key() -> str:
    global _api_key
    if _api_key:
        return _api_key
    html = http_get("https://etilbudsavis.no/", timeout=30).decode("utf-8", "replace")
    match = re.search(r"https://[^\"'\s]+entry-client-[^\"'\s]+\.js", html)
    if not match:
        raise RuntimeError("Fant ikke eTilbudsavis-scriptet. Siden kan ha endret seg.")
    js = http_get(match.group(0), timeout=40).decode("utf-8", "replace")
    key = re.search(r"browser:`([0-9a-f]{32})`", js)
    if not key:
        raise RuntimeError("Fant ikke offentlig API-nøkkel i eTilbudsavis.")
    _api_key = key.group(1)
    return _api_key


def fetch_query_page(query: str, offset: int, key: str) -> list[dict]:
    params = urllib.parse.urlencode(
        {"query": query, "limit": PAGE_SIZE, "offset": offset}
    )
    url = "https://squid-api.tjek.com/v2/offers/search?" + params
    last_err = None
    for attempt in range(3):
        try:
            raw = http_get(
                url,
                headers={"x-api-key": key, "Accept": "application/json"},
                timeout=40,
            )
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, list):
                return []
            return data
        except Exception as exc:  # nettverk, 429, JSON
            last_err = exc
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"Søk «{query}» feilet: {last_err}")


def is_candy(heading: str, description: str) -> bool:
    """Navnet må selv se ut som godteri. Beskrivelsen alene er for støyende:
    avisteksten nevner sjokolade ved siden av donuts, toddy og pynt.
    """
    heading = heading or ""
    description = description or ""
    text = f"{heading}\n{description}"
    if re.search(r"\bEUR\b", description):
        return False
    if NONFOOD_RE.search(heading) or NONFOOD_RE.search(description[:240]):
        return False
    if EXCLUDE_RE.search(heading):
        return False
    if re.search(r"\b(cola|brus|øl)\b", description, re.I) and not CANDY_RE.search(heading):
        return False
    if BAR_RE.search(heading) and not re.search(r"kakemiks|\bbake\b", text, re.I):
        return True
    if CANDY_RE.search(heading):
        return True
    if re.search(r"kalender", heading, re.I) and re.search(r"sjokolade|godteri", description, re.I):
        return True
    if re.search(r"gott\s*(&|og)\s*blandet", text, re.I):
        return True
    if re.search(r"utvalg|godteri|godtepose|halloweenpose|party mix", heading, re.I) and CANDY_RE.search(description):
        return True
    return False


def slug_for(offer: dict) -> str | None:
    dealer = offer.get("dealer") or {}
    markets = dealer.get("markets") or []
    for market in markets:
        if market.get("country_code") == "NO" and market.get("slug"):
            return market["slug"]
    if markets and markets[0].get("slug"):
        return markets[0]["slug"]
    return None


def offer_url(offer: dict) -> str:
    slug = slug_for(offer)
    oid = offer.get("id") or ""
    cid = offer.get("catalog_id") or ""
    if slug and oid and cid:
        return (
            f"https://etilbudsavis.no/{urllib.parse.quote(slug)}"
            f"?publication={urllib.parse.quote(cid)}&offer={urllib.parse.quote(oid)}"
        )
    heading = offer.get("heading") or "godteri"
    return "https://etilbudsavis.no/soek/" + urllib.parse.quote(heading)


def proxy_path(url: str | None) -> str | None:
    # Direkte bilde-URL, så siden virker på GitHub Pages og i andre nettlesere.
    if not url or not url.startswith(IMAGE_HOST):
        return None
    return url


def normalize(offer: dict) -> dict | None:
    dealer = offer.get("dealer") or {}
    country = (dealer.get("country") or {}).get("id")
    if country != "NO":
        return None
    pricing = offer.get("pricing") or {}
    if pricing.get("currency") != "NOK":
        return None
    price = pricing.get("price")
    if not isinstance(price, (int, float)) or price <= 0 or price >= 500:
        return None
    heading = (offer.get("heading") or "").strip()
    description = (offer.get("description") or "").strip()
    if not heading or not is_candy(heading, description):
        return None
    till = offer.get("run_till")
    if till:
        try:
            end = datetime.fromisoformat(till)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if end < datetime.now(timezone.utc):
                return None
        except ValueError:
            pass
    before = pricing.get("pre_price")
    if not isinstance(before, (int, float)) or before <= price:
        before = None
    savings = round(before - price, 2) if before else None
    store = (dealer.get("name") or "Ukjent butikk").strip()
    images = offer.get("images") or {}
    return {
        "id": offer.get("id"),
        "name": heading,
        "description": description[:280],
        "price": round(float(price), 2),
        "before": round(float(before), 2) if before else None,
        "savings": savings,
        "store": store,
        "color": STORE_COLORS.get(store, "#6b3a2a"),
        "image": proxy_path(images.get("view") or images.get("thumb")),
        "logo": proxy_path((offer.get("branding") or {}).get("logo") or dealer.get("logo")),
        "valid_from": offer.get("run_from"),
        "valid_until": offer.get("run_till"),
        "url": offer_url(offer),
        "currency": pricing.get("currency") or "NOK",
    }


def collect_offers() -> list[dict]:
    key = discover_api_key()
    jobs = [(query, page * PAGE_SIZE) for query in QUERIES for page in range(MAX_PAGES)]
    found: dict[str, dict] = {}
    errors = 0

    def work(job):
        query, offset = job
        return query, offset, fetch_query_page(query, offset, key)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(work, job) for job in jobs]
        for fut in as_completed(futures):
            try:
                _query, _offset, rows = fut.result()
            except Exception:
                errors += 1
                continue
            for row in rows:
                oid = row.get("id")
                if oid and oid not in found:
                    found[oid] = row
    offers = []
    seen = set()
    for row in found.values():
        item = normalize(row)
        if not item:
            continue
        key = (item["store"].casefold(), item["name"].casefold(), item["price"])
        if key in seen:
            continue
        seen.add(key)
        offers.append(item)
    offers.sort(key=lambda o: (o["price"], o["name"]))
    if not offers and errors:
        raise RuntimeError("Fikk ingen tilbud, og flere søk feilet.")
    return offers


def save_cache(offers: list[dict], fetched_at: str) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps({"fetched_at": fetched_at, "offers": offers}, ensure_ascii=False),
        encoding="utf-8",
    )


def load_cache() -> None:
    if not CACHE_PATH.exists():
        return
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    offers = data.get("offers") or []
    if not offers:
        return
    with _lock:
        _state["offers"] = offers
        _state["fetched_at"] = data.get("fetched_at")
        _state["ready"] = True
        _state["stats"] = summarize(offers)


def summarize(offers: list[dict]) -> dict:
    under = [o for o in offers if o["price"] < 120]
    stores = sorted({o["store"] for o in under})
    cheapest = under[0]["price"] if under else None
    return {
        "total": len(offers),
        "under_120": len(under),
        "stores": stores,
        "cheapest": cheapest,
    }


def refresh() -> None:
    with _lock:
        if _state["loading"]:
            return
        _state["loading"] = True
        _state["error"] = None
    try:
        offers = collect_offers()
        fetched_at = datetime.now(timezone.utc).isoformat()
        save_cache(offers, fetched_at)
        with _lock:
            _state["offers"] = offers
            _state["fetched_at"] = fetched_at
            _state["ready"] = True
            _state["stats"] = summarize(offers)
            _state["error"] = None
        print(f"Hentet {len(offers)} godteritilbud.", flush=True)
    except Exception as exc:
        with _lock:
            _state["error"] = str(exc)
            if _state["offers"]:
                _state["ready"] = True
        print(f"Henting feilet: {exc}", flush=True)
    finally:
        with _lock:
            _state["loading"] = False


def snapshot() -> dict:
    with _lock:
        return {
            "ready": _state["ready"],
            "loading": _state["loading"],
            "error": _state["error"],
            "fetched_at": _state["fetched_at"],
            "stats": _state["stats"],
            "offers": _state["offers"],
        }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            data = (ROOT / "index.html").read_bytes()
            self._send(200, data, "text/html; charset=utf-8")
            return
        if path == "/api/tilbud":
            payload = snapshot()
            # Ikke send hele korpuset før det er klart; klienten poller.
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        if path == "/api/refresh":
            threading.Thread(target=refresh, daemon=True).start()
            self._send(202, b'{"ok":true}', "application/json")
            return
        if path == "/api/bilde":
            self._image(parsed.query)
            return
        rel = urllib.parse.unquote(path).lstrip("/")
        if rel and ".." not in rel.split("/"):
            file = (ROOT / rel).resolve()
            if file.is_file() and ROOT.resolve() in file.parents:
                ctype = {
                    ".html": "text/html; charset=utf-8",
                    ".js": "text/javascript; charset=utf-8",
                    ".json": "application/json; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".svg": "image/svg+xml",
                    ".txt": "text/plain; charset=utf-8",
                }.get(file.suffix.lower())
                if ctype:
                    self._send(200, file.read_bytes(), ctype)
                    return
        self._send(404, b"ikke funnet", "text/plain; charset=utf-8")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def _image(self, query: str) -> None:
        params = urllib.parse.parse_qs(query)
        url = (params.get("u") or [""])[0]
        if not url.startswith(IMAGE_HOST):
            self._send(400, b"ugyldig bilde", "text/plain; charset=utf-8")
            return
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as res:
                data = res.read(2_000_000)
                ctype = res.headers.get("Content-Type", "image/webp")
            self._send(200, data, ctype.split(";")[0])
        except Exception:
            self._send(502, b"bilde utilgjengelig", "text/plain; charset=utf-8")


def serve(open_browser: bool) -> None:
    load_cache()
    threading.Thread(target=refresh, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"Godterikupp kjører på {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stoppet.", flush=True)


def once() -> int:
    offers = collect_offers()
    under = [o for o in offers if o["price"] < 120]
    print(f"godteri med pris: {len(offers)}")
    print(f"under 120 kr: {len(under)}")
    print("--- billigst ---")
    for o in under[:12]:
        print(f"{o['price']:>7}  {o['store']:<16}  {o['name']}")
    print("--- mistenkte (navn uten tydelig godteriord) ---")
    shown = 0
    for o in under:
        if CANDY_RE.search(o["name"]):
            continue
        print(f"{o['price']:>7}  {o['store']:<16}  {o['name']}  | {o['description'][:80]}")
        shown += 1
        if shown >= 25:
            break
    print(f"mistenkte vist: {shown}")
    return 0 if under else 1


def write_snapshot() -> int:
    offers = collect_offers()
    fetched_at = datetime.now(timezone.utc).isoformat()
    out = ROOT / "data" / "offers.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": fetched_at,
        "source": "eTilbudsavis",
        "max_price_default": 120,
        "offers": offers,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    under = sum(1 for o in offers if o["price"] < 120)
    print(f"Skrev {out} ({len(offers)} tilbud, {under} under 120 kr)", flush=True)
    return 0 if under else 1


if __name__ == "__main__":
    if "--once" in sys.argv:
        sys.exit(once())
    if "--snapshot" in sys.argv:
        sys.exit(write_snapshot())
    serve(open_browser="--open" in sys.argv)
