"""Конфигурация avia-watcher. Правьте этот файл, не watcher.py.

ПЕРЕД ЗАПУСКОМ: проверьте IATA-коды городов и даты — ошибка тут не ловится
кодом, просто даст пустые результаты.
"""
import os


def _load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

TRAVELPAYOUTS_TOKEN = os.environ.get("TRAVELPAYOUTS_TOKEN", "")
TRAVELPAYOUTS_MARKER = os.environ.get("TRAVELPAYOUTS_MARKER", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Аэропорты вылета и направления — матрица ORIGINS x DESTINATIONS.
# Пример: несколько аэропортов одного региона против одного направления.
ORIGINS = ["NAL"]        # Нальчик. Добавьте, например: "MRV", "OGZ", "GRV"
DESTINATIONS = ["MOW"]   # Москва (любой город из группы MOW: SVO/DME/VKO)

DEPARTURE_AT = "2026-11"   # YYYY-MM или YYYY-MM-DD
RETURN_AT = None           # None — только туда; иначе "YYYY-MM" / "YYYY-MM-DD"
ONE_WAY = RETURN_AT is None
CURRENCY = "rub"

ROUTES = [
    {
        "origin": origin,
        "destination": destination,
        "departure_at": DEPARTURE_AT,
        "return_at": RETURN_AT,
        "one_way": ONE_WAY,
        "currency": CURRENCY,
    }
    for origin in ORIGINS
    for destination in DESTINATIONS
]

ANOMALY_THRESHOLD = 0.5        # алерт, если цена ниже этой доли от медианы истории
MIN_HISTORY_SAMPLES = 5        # минимум наблюдений маршрута перед тем, как искать аномалии
HISTORY_WINDOW = 30            # сколько последних наблюдений использовать для медианы

POLL_INTERVAL_SECONDS = 20     # желаемый интервал опроса одного цикла (спецификация: 15-30с)
MAX_REQUESTS_PER_MINUTE = 60   # реально применяемый бюджет запросов к Travelpayouts
REQUEST_TIMEOUT_SECONDS = 10   # таймаут каждого HTTP-запроса (и к Travelpayouts, и к Telegram)
ALERT_MAX_AGE_SECONDS = 3600   # не отправлять алерт про тариф протухший дольше этого

DB_PATH = "prices.db"
