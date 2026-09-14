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
ORIGINS = ["NAL", "MRV", "STW", "OGZ", "GRV"]
# Нальчик, Минеральные Воды, Ставрополь, Владикавказ, Грозный
DESTINATIONS = ["MOW", "LED"]
# Москва (группа SVO/DME/VKO), Санкт-Петербург

CURRENCY = "rub"

# Маршруты без даты вылета — watcher.py разворачивает каждый в скользящее
# окно "текущий месяц + MONTHS_AHEAD-1 следующих", пересчитываемое заново на
# каждом прогоне. Это и значит "мониторить начиная с сегодняшнего дня": окно
# едет вперёд само, а не застывает на месяце, когда маршрут был добавлен.
# Через /add в Telegram можно добавить и маршрут с конкретной фиксированной
# датой — тогда он проверяется только на неё, без скользящего окна.
MONTHS_AHEAD = 3

ROUTES = [
    {"origin": origin, "destination": destination, "currency": CURRENCY}
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
