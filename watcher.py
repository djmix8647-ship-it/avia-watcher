"""avia-watcher: демон мониторинга аномально дешёвых авиабилетов.

Источник данных: GET https://api.travelpayouts.com/aviasales/v3/prices_for_dates
(существование подтверждено эмпирически — см. PLAN.md; точная схема полей
ответа не подтверждена официальной документацией — см. README, шаг
"первый запуск").
"""
import itertools
import logging
import math
import re
import sqlite3
import statistics
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("watcher")

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
TELEGRAM_URL_TMPL = "https://api.telegram.org/bot{token}/sendMessage"

TRUSTED_LINK_HOSTS = {
    "aviasales.com", "www.aviasales.com",
    "aviasales.ru", "www.aviasales.ru",
    "search.aviasales.ru",
}

_TOKEN_QS_RE = re.compile(r"([?&](?:token|X-Access-Token)=)[^&]*", re.IGNORECASE)
_BOT_PATH_RE = re.compile(r"/bot[0-9]+:[A-Za-z0-9_-]+/")


def redact_url(url):
    """Убирает значения токенов из URL перед логированием (REV-018)."""
    url = _TOKEN_QS_RE.sub(r"\1***", url)
    url = _BOT_PATH_RE.sub("/bot***/", url)
    return url


def route_id(route):
    return "{origin}-{destination}-{departure_at}-{return_at}-{one_way}-{currency}".format(
        origin=route["origin"],
        destination=route["destination"],
        departure_at=route["departure_at"],
        return_at=route.get("return_at") or "oneway",
        one_way=route.get("one_way", True),
        currency=route.get("currency", "rub"),
    )


def init_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id TEXT NOT NULL,
            price REAL NOT NULL,
            currency TEXT,
            depart_date TEXT,
            return_date TEXT,
            actual INTEGER,
            checked_at TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_route ON prices(route_id, checked_at)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS alerts (
            route_id TEXT NOT NULL,
            price REAL NOT NULL,
            depart_date TEXT,
            return_date TEXT,
            purchase_url TEXT NOT NULL,
            is_itinerary_specific INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT,
            PRIMARY KEY (route_id, price, depart_date, return_date)
        )"""
    )
    conn.commit()
    return conn


def fetch_cheapest(route, token, rate_limited_until):
    """Возвращает dict с ключами price/depart_date/return_date/link/actual,
    None если данных нет, ошибка сети/429, или схема ответа не распознана.
    При 429 записывает время следующей попытки в rate_limited_until[rid]."""
    rid = route_id(route)
    params = {
        "origin": route["origin"],
        "destination": route["destination"],
        "departure_at": route["departure_at"],
        "one_way": str(route.get("one_way", True)).lower(),
        "direct": "false",
        "sorting": "price",
        "unique": "false",
        "limit": 5,
        "page": 1,
        "currency": route.get("currency", "rub"),
    }
    if route.get("return_at"):
        params["return_at"] = route["return_at"]

    headers = {"X-Access-Token": token}

    try:
        resp = requests.get(API_URL, params=params, headers=headers,
                             timeout=config.REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        log.error("%s: сетевая ошибка при запросе к Travelpayouts (%s)", rid, type(e).__name__)
        return None

    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after else 60.0
        except ValueError:
            delay = 60.0
        rate_limited_until[rid] = time.monotonic() + delay
        log.warning("%s: Travelpayouts вернул 429, ждём %.0fс", rid, delay)
        return None

    if resp.status_code != 200:
        log.error("%s: Travelpayouts HTTP %s (%s)", rid, resp.status_code, redact_url(resp.url))
        return None

    try:
        payload = resp.json()
    except ValueError:
        log.error("%s: не удалось разобрать JSON-ответ Travelpayouts", rid)
        return None

    # REV-025: успешный HTTP-ответ с валидным JSON не гарантирует ожидаемую форму
    # (например, verhний уровень — список, а не dict, или data — не список dict'ов).
    # payload.get/item.get на неожиданном типе бросили бы AttributeError, которое
    # вышло бы из check_route до flush_pending_alerts (шаг 6) — валидируем типы
    # явно и всегда возвращаем None вместо падения на нераспознанной форме.
    if not isinstance(payload, dict):
        log.error("%s: неожиданная форма ответа Travelpayouts (не объект): %s",
                   rid, type(payload).__name__)
        return None

    data = payload.get("data") or []
    if not isinstance(data, list):
        log.error("%s: неожиданная форма поля data в ответе Travelpayouts: %s",
                   rid, type(data).__name__)
        return None
    if not data:
        log.info("%s: нет предложений на эти даты", rid)
        return None

    seen_keys = None
    for item in data:
        if not isinstance(item, dict):
            continue
        if seen_keys is None:
            seen_keys = sorted(item.keys())
        price = item.get("price")
        if price is None:
            price = item.get("value")
        if price is not None:
            return {
                "price": float(price),
                "depart_date": item.get("depart_date") or item.get("departure_at"),
                "return_date": item.get("return_date") or item.get("return_at"),
                "link": item.get("link"),
                "actual": item.get("actual"),
            }

    log.error(
        "%s: непустой ответ Travelpayouts, но не распознано поле цены — "
        "возможно, изменилась схема API. Ключи первого элемента: %s",
        rid, seen_keys,
    )
    return None


def get_recent_prices(conn, rid, limit):
    rows = conn.execute(
        "SELECT price FROM prices WHERE route_id = ? AND (actual IS NULL OR actual = 1) "
        "ORDER BY checked_at DESC LIMIT ?",
        (rid, limit),
    ).fetchall()
    return [r[0] for r in rows]


def record_price(conn, rid, entry):
    actual = entry.get("actual")
    conn.execute(
        "INSERT INTO prices (route_id, price, currency, depart_date, return_date, actual, checked_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            rid,
            entry["price"],
            None,
            entry.get("depart_date"),
            entry.get("return_date"),
            None if actual is None else int(bool(actual)),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def is_anomaly(current_price, history, threshold):
    if len(history) < config.MIN_HISTORY_SAMPLES:
        return False, None
    baseline = statistics.median(history)
    return current_price < baseline * threshold, baseline


def build_purchase_link(route, entry):
    """Возвращает (url, is_itinerary_specific)."""
    link = entry.get("link") if entry else None
    if link:
        parsed = urlparse(link)
        if parsed.scheme == "https" and parsed.netloc in TRUSTED_LINK_HOSTS:
            return link, True
        if not parsed.scheme and not parsed.netloc:
            path = link if link.startswith("/") else f"/search/{link}"
            return f"https://www.aviasales.com{path}", True
        # неизвестная схема/хост — не доверяем
    marker = config.TRAVELPAYOUTS_MARKER
    url = (
        f"https://search.aviasales.ru/?marker={marker}"
        f"&origin_iata={route['origin']}&destination_iata={route['destination']}"
        f"&locale=ru"
    )
    return url, False


def claim_alert(conn, rid, route, entry):
    # depart_date/return_date идут в PRIMARY KEY и в WHERE-сравнения по равенству —
    # в SQLite (как и в стандартном SQL) NULL никогда не равен NULL, так что для
    # one-way маршрутов (return_date отсутствует) UPDATE...WHERE return_date=?
    # никогда не нашёл бы свою же строку. Нормализуем None -> "" здесь и везде,
    # где alerts читается/пишется по этим колонкам.
    purchase_url, is_itinerary_specific = build_purchase_link(route, entry)
    conn.execute(
        "INSERT OR IGNORE INTO alerts "
        "(route_id, price, depart_date, return_date, purchase_url, is_itinerary_specific, "
        " status, created_at, attempt_count, next_attempt_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, 0, NULL)",
        (
            rid,
            entry["price"],
            entry.get("depart_date") or "",
            entry.get("return_date") or "",
            purchase_url,
            int(is_itinerary_specific),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


class TelegramRateLimited(Exception):
    """429 от Telegram — несёт Retry-After, чтобы flush_pending_alerts мог
    выставить next_attempt_at по нему, а не по общему backoff (REV-023)."""

    def __init__(self, retry_after_seconds):
        super().__init__(f"Telegram rate limited, retry_after={retry_after_seconds}")
        self.retry_after_seconds = retry_after_seconds


def send_telegram_alert(route, price, depart_date, return_date, purchase_url, is_itinerary_specific):
    currency = route.get("currency", "rub").upper()
    text = (
        f"\U0001F525 Аномально дешёвый билет!\n"
        f"{route['origin']} → {route['destination']}\n"
        f"Цена: {price:.0f} {currency}\n"
        f"Вылет: {depart_date or '?'}"
    )
    if return_date:
        text += f", обратно: {return_date}"
    text += f"\n{purchase_url}"
    if not is_itinerary_specific:
        text += "\n(ссылка — общий поиск по маршруту без предустановленных дат, уточните даты на сайте)"

    url = TELEGRAM_URL_TMPL.format(token=config.TELEGRAM_BOT_TOKEN)
    resp = requests.post(
        url,
        json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text},
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after else 60.0
        except ValueError:
            delay = 60.0
        raise TelegramRateLimited(delay)
    if resp.status_code != 200:
        raise requests.HTTPError(f"Telegram sendMessage failed: status={resp.status_code}")


def flush_pending_alerts(conn, route, rid):
    now = datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT price, depart_date, return_date, purchase_url, is_itinerary_specific, "
        "created_at, attempt_count, next_attempt_at "
        "FROM alerts WHERE route_id = ? AND status = 'pending'",
        (rid,),
    ).fetchall()

    for price, depart_date, return_date, purchase_url, is_itinerary_specific, \
            created_at, attempt_count, next_attempt_at in rows:
        if next_attempt_at:
            try:
                if datetime.fromisoformat(next_attempt_at) > now:
                    continue
            except ValueError:
                pass

        created = datetime.fromisoformat(created_at)
        if (now - created).total_seconds() > config.ALERT_MAX_AGE_SECONDS:
            conn.execute(
                "UPDATE alerts SET status='expired' WHERE route_id=? AND price=? "
                "AND depart_date=? AND return_date=?",
                (rid, price, depart_date, return_date),
            )
            conn.commit()
            log.warning(
                "%s: алерт на цену %.0f протух, не удавалось доставить (вероятна долгая "
                "недоступность Telegram или неверный TELEGRAM_CHAT_ID)", rid, price,
            )
            continue

        try:
            send_telegram_alert(route, price, depart_date, return_date,
                                 purchase_url, bool(is_itinerary_specific))
        except Exception as e:
            # НЕ log.exception/str(e) здесь: сетевые исключения requests (Timeout,
            # ConnectionError) содержат полный URL, включая TELEGRAM_BOT_TOKEN в пути
            # (REV-018) — логируем только тип исключения, никогда его текст/traceback.
            attempt_count += 1
            if isinstance(e, TelegramRateLimited):
                delay = e.retry_after_seconds  # REV-023: уважаем Retry-After, а не общий backoff
            else:
                delay = min(config.POLL_INTERVAL_SECONDS * (2 ** attempt_count), 3600)
            next_at = (now.timestamp() + delay)
            conn.execute(
                "UPDATE alerts SET attempt_count=?, next_attempt_at=? "
                "WHERE route_id=? AND price=? AND depart_date=? AND return_date=?",
                (attempt_count, datetime.fromtimestamp(next_at, tz=timezone.utc).isoformat(),
                 rid, price, depart_date, return_date),
            )
            conn.commit()
            log.error("%s: не удалось отправить алерт в Telegram (попытка %d, %s)",
                       rid, attempt_count, type(e).__name__)
        else:
            conn.execute(
                "UPDATE alerts SET status='sent' WHERE route_id=? AND price=? "
                "AND depart_date=? AND return_date=?",
                (rid, price, depart_date, return_date),
            )
            conn.commit()
            log.info("%s: алерт на цену %.0f доставлен в Telegram", rid, price)


def check_route(conn, route, rate_limited_until):
    rid = route_id(route)

    if rate_limited_until.get(rid, 0) > time.monotonic():
        log.info("%s: пропуск цикла — ждём окончания rate-limit", rid)
        entry = None
    else:
        entry = fetch_cheapest(route, config.TRAVELPAYOUTS_TOKEN, rate_limited_until)

    if entry is not None:
        history = get_recent_prices(conn, rid, config.HISTORY_WINDOW)

        if entry.get("actual") is not False and len(history) >= config.MIN_HISTORY_SAMPLES:
            anomaly, baseline = is_anomaly(entry["price"], history, config.ANOMALY_THRESHOLD)
            if anomaly:
                log.warning("%s: АНОМАЛИЯ цена=%.0f медиана=%.0f", rid, entry["price"], baseline)
                claim_alert(conn, rid, route, entry)
        else:
            log.info("%s: цена=%.0f (недостаточно истории или не actual)", rid, entry["price"])

        record_price(conn, rid, entry)

    flush_pending_alerts(conn, route, rid)


def compute_effective_interval():
    n = len(config.ROUTES)
    if n == 0 or config.MAX_REQUESTS_PER_MINUTE <= 0:
        return config.POLL_INTERVAL_SECONDS
    budget_interval = math.ceil(n * 60 / config.MAX_REQUESTS_PER_MINUTE)
    effective = max(config.POLL_INTERVAL_SECONDS, budget_interval)
    if effective > config.POLL_INTERVAL_SECONDS:
        log.warning(
            "POLL_INTERVAL_SECONDS=%d слишком мал для %d маршрутов при "
            "MAX_REQUESTS_PER_MINUTE=%d — реальный интервал между циклами: %dс",
            config.POLL_INTERVAL_SECONDS, n, config.MAX_REQUESTS_PER_MINUTE, effective,
        )
    return effective


def compute_request_spacing(interval, n):
    """Секунд между отдельными запросами внутри цикла (REV-024): n запросов,
    равномерно распределённых по interval секунд, гарантируют, что бюджет
    MAX_REQUESTS_PER_MINUTE не превышается всплеском в начале цикла."""
    if n <= 0:
        return interval
    return interval / n


def main():
    if not config.TRAVELPAYOUTS_TOKEN or not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        raise SystemExit("Заполните TRAVELPAYOUTS_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID в .env")

    if not config.ROUTES:
        raise SystemExit("ROUTES пуст — нечего опрашивать, проверьте config.py")

    conn = init_db(config.DB_PATH)
    interval = compute_effective_interval()
    rate_limited_until = {}
    n = len(config.ROUTES)
    # REV-024: N запросов не должны выстреливать пачкой в начале цикла — иначе
    # средний темп укладывается в бюджет, а мгновенный всплеск — нет. Каждый
    # маршрут опрашивается раз в `interval` секунд, но сами маршруты внутри
    # цикла равномерно разнесены по времени, а не выполняются одним блоком.
    spacing = compute_request_spacing(interval, n)

    log.info("Запуск: %d маршрут(ов), интервал %dс (шаг между запросами %.1fс)", n, interval, spacing)

    next_at = time.monotonic()
    routes_cycle = itertools.cycle(config.ROUTES)
    for route in routes_cycle:
        now = time.monotonic()
        if next_at > now:
            time.sleep(next_at - now)
        next_at += spacing

        rid = route_id(route)
        try:
            check_route(conn, route, rate_limited_until)
        except requests.RequestException as e:
            log.error("%s: ошибка сети/API (%s)", rid, type(e).__name__)
        except Exception:
            log.exception("%s: непредвиденная ошибка", rid)


if __name__ == "__main__":
    main()
