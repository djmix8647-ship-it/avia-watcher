"""Assert-based self-check для watcher.py. Без pytest/unittest, без сети.

Запуск: python test_watcher.py
"""
from datetime import datetime

import config
import watcher

TEST_ROUTE = {
    "origin": "AAA", "destination": "BBB",
    "departure_at": "2026-11", "return_at": None,
    "one_way": True, "currency": "rub",
}


def make_entry(price, depart="2026-11-10", ret=None, actual=None, link=None):
    return {"price": price, "depart_date": depart, "return_date": ret,
            "link": link, "actual": actual}


def test_is_anomaly_boundary():
    short_history = [10000] * (config.MIN_HISTORY_SAMPLES - 1)
    anomaly, baseline = watcher.is_anomaly(1000, short_history, 0.5)
    assert anomaly is False and baseline is None, "недостаточно истории — аномалия не проверяется"

    full_history = [10000] * config.MIN_HISTORY_SAMPLES
    anomaly, baseline = watcher.is_anomaly(1000, full_history, 0.5)
    assert anomaly is True and baseline == 10000

    anomaly, _ = watcher.is_anomaly(6000, full_history, 0.5)
    assert anomaly is False, "6000 не ниже 50% от медианы 10000"


def test_build_purchase_link():
    route = {"origin": "AAA", "destination": "BBB"}

    url, exact = watcher.build_purchase_link(route, {"link": "AAA1011BBB"})
    assert exact is True
    assert url == "https://www.aviasales.com/search/AAA1011BBB"

    url, exact = watcher.build_purchase_link(route, {"link": "/search/AAA1011BBB"})
    assert exact is True
    assert url == "https://www.aviasales.com/search/AAA1011BBB"

    trusted = "https://www.aviasales.com/search/AAA1011BBB?marker=1"
    url, exact = watcher.build_purchase_link(route, {"link": trusted})
    assert exact is True and url == trusted

    url, exact = watcher.build_purchase_link(route, {"link": "http://attacker.example/phish"})
    assert exact is False and "attacker.example" not in url

    url, exact = watcher.build_purchase_link(route, {"link": "https://evil.example/x"})
    assert exact is False and "evil.example" not in url

    url, exact = watcher.build_purchase_link(route, {"link": None})
    assert exact is False and url.startswith("https://search.aviasales.ru/?")


def test_route_id():
    r1 = dict(TEST_ROUTE)
    r2 = dict(TEST_ROUTE, currency="usd")
    assert watcher.route_id(r1) == watcher.route_id(dict(TEST_ROUTE))
    assert watcher.route_id(r1) != watcher.route_id(r2)


def test_redact_url():
    u1 = "https://api.travelpayouts.com/x?token=SECRET123&origin=AAA"
    assert "SECRET123" not in watcher.redact_url(u1)

    u2 = "https://api.telegram.org/bot123456:AAExampleTokenXYZ/sendMessage"
    assert "AAExampleTokenXYZ" not in watcher.redact_url(u2)


class _Patch:
    """Простая подмена атрибутов модуля watcher на время теста, без mock."""

    def __init__(self, **attrs):
        self._attrs = attrs
        self._originals = {}

    def __enter__(self):
        for name, value in self._attrs.items():
            self._originals[name] = getattr(watcher, name)
            setattr(watcher, name, value)
        return self

    def __exit__(self, *exc):
        for name, value in self._originals.items():
            setattr(watcher, name, value)


def test_check_route_alert_and_dedup():
    conn = watcher.init_db(":memory:")
    route = dict(TEST_ROUTE)
    rid = watcher.route_id(route)

    for _ in range(config.MIN_HISTORY_SAMPLES):
        watcher.record_price(conn, rid, make_entry(10000))

    sent, record_calls = [], []
    original_record = watcher.record_price

    def fake_fetch(route, token, rate_limited_until):
        return make_entry(3000)

    def fake_send(route, price, depart_date, return_date, purchase_url, is_itinerary_specific):
        sent.append(price)

    def counting_record(conn_, rid_, entry_):
        record_calls.append(entry_["price"])
        original_record(conn_, rid_, entry_)

    with _Patch(fetch_cheapest=fake_fetch, send_telegram_alert=fake_send, record_price=counting_record):
        watcher.check_route(conn, route, {})
        assert sent == [3000], "аномалия должна вызвать ровно один алерт"
        assert record_calls == [3000], "наблюдение должно быть записано"

        watcher.check_route(conn, route, {})
        assert sent == [3000], "повторная попытка не должна дублировать уже отправленный алерт"
        assert record_calls == [3000, 3000], "но наблюдение всё равно пишется каждый цикл"


def test_send_failure_does_not_block_record_price():
    conn = watcher.init_db(":memory:")
    route = dict(TEST_ROUTE)
    rid = watcher.route_id(route)

    for _ in range(config.MIN_HISTORY_SAMPLES):
        watcher.record_price(conn, rid, make_entry(10000))

    record_calls = []
    original_record = watcher.record_price

    def fake_fetch(route, token, rate_limited_until):
        return make_entry(3000)

    def failing_send(*a, **kw):
        raise RuntimeError("simulated Telegram failure")

    def counting_record(conn_, rid_, entry_):
        record_calls.append(entry_["price"])
        original_record(conn_, rid_, entry_)

    with _Patch(fetch_cheapest=fake_fetch, send_telegram_alert=failing_send, record_price=counting_record):
        watcher.check_route(conn, route, {})

    assert record_calls == [3000], "record_price обязан вызваться, даже если отправка алерта упала"
    row = conn.execute("SELECT status FROM alerts WHERE route_id=?", (rid,)).fetchone()
    assert row[0] == "pending"


def test_flush_runs_even_when_fetch_returns_none():
    """REV-020: flush_pending_alerts должен доставлять отложенные алерты,
    даже если в этом цикле fetch_cheapest не вернул данных (сеть/429)."""
    conn = watcher.init_db(":memory:")
    route = dict(TEST_ROUTE)
    rid = watcher.route_id(route)

    watcher.claim_alert(conn, rid, route, make_entry(1234))

    sent = []

    def fake_fetch_none(route, token, rate_limited_until):
        return None

    def fake_send(route, price, depart_date, return_date, purchase_url, is_itinerary_specific):
        sent.append(price)

    with _Patch(fetch_cheapest=fake_fetch_none, send_telegram_alert=fake_send):
        watcher.check_route(conn, route, {})

    assert sent == [1234]
    row = conn.execute("SELECT status FROM alerts WHERE route_id=?", (rid,)).fetchone()
    assert row[0] == "sent"


def test_claim_persists_exact_link_used_by_flush():
    """REV-021: flush должен слать именно ту ссылку, что была вычислена и
    сохранена в claim_alert, а не пересчитывать её заново."""
    conn = watcher.init_db(":memory:")
    route = dict(TEST_ROUTE)
    rid = watcher.route_id(route)
    link = "https://www.aviasales.com/search/AAA1011BBB?marker=1"
    watcher.claim_alert(conn, rid, route, make_entry(555, link=link))

    seen = []

    def fake_send(route, price, depart_date, return_date, purchase_url, is_itinerary_specific):
        seen.append((purchase_url, is_itinerary_specific))

    with _Patch(send_telegram_alert=fake_send):
        watcher.flush_pending_alerts(conn, route, rid)

    assert seen == [(link, True)]


def test_pending_alert_delivered_despite_baseline_drift():
    """REV-017: если отправка падает, а цена продолжает записываться в
    историю, скользящая медиана может сдвинуться настолько, что новая
    аномалия перестанет обнаруживаться — но ранее отложенный алерт всё
    равно должен быть доставлен, как только отправка снова заработает."""
    conn = watcher.init_db(":memory:")
    route = dict(TEST_ROUTE)
    rid = watcher.route_id(route)

    for _ in range(config.MIN_HISTORY_SAMPLES):
        watcher.record_price(conn, rid, make_entry(10000))

    state = {"fail": True}
    sent = []

    def fake_fetch(route, token, rate_limited_until):
        return make_entry(3000)

    def flaky_send(route, price, depart_date, return_date, purchase_url, is_itinerary_specific):
        if state["fail"]:
            raise RuntimeError("simulated Telegram outage")
        sent.append(price)

    with _Patch(fetch_cheapest=fake_fetch, send_telegram_alert=flaky_send):
        watcher.check_route(conn, route, {})  # первая аномалия, claim, отправка падает

        # ещё несколько циклов: цена продолжает считаться аномальной и
        # записываться, пока медиана не сдвинется достаточно низко
        for _ in range(6):
            watcher.check_route(conn, route, {})

        history = watcher.get_recent_prices(conn, rid, config.HISTORY_WINDOW)
        anomaly_now, _ = watcher.is_anomaly(3000, history, config.ANOMALY_THRESHOLD)
        assert anomaly_now is False, "медиана должна была сдвинуться ниже порога срабатывания"

        # Telegram "восстановился" — снимаем backoff-таймер для теста и повторяем цикл
        conn.execute("UPDATE alerts SET next_attempt_at = NULL WHERE route_id = ?", (rid,))
        conn.commit()
        state["fail"] = False
        watcher.check_route(conn, route, {})

    assert sent == [3000], "ранее отложенный алерт обязан быть доставлен, несмотря на дрейф медианы"
    row = conn.execute("SELECT status FROM alerts WHERE route_id=?", (rid,)).fetchone()
    assert row[0] == "sent"


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, headers=None, url="https://api.travelpayouts.com/x"):
        self.status_code = status_code
        self._json_body = json_body
        self.headers = headers or {}
        self.url = url

    def json(self):
        return self._json_body


def test_telegram_429_uses_retry_after_not_generic_backoff():
    """REV-023: flush_pending_alerts должен взять next_attempt_at из
    Retry-After, а не из общего exponential backoff, при 429 от Telegram."""
    conn = watcher.init_db(":memory:")
    route = dict(TEST_ROUTE)
    rid = watcher.route_id(route)
    watcher.claim_alert(conn, rid, route, make_entry(777))

    def fake_post(url, json, timeout):
        return FakeResponse(status_code=429, headers={"Retry-After": "600"})

    original_post = watcher.requests.post
    watcher.requests.post = fake_post
    try:
        watcher.flush_pending_alerts(conn, route, rid)
    finally:
        watcher.requests.post = original_post

    row = conn.execute(
        "SELECT status, next_attempt_at FROM alerts WHERE route_id=?", (rid,)
    ).fetchone()
    assert row[0] == "pending"
    next_attempt_at = datetime.fromisoformat(row[1])
    now = datetime.now(next_attempt_at.tzinfo)
    delay = (next_attempt_at - now).total_seconds()
    # общий backoff на первой попытке был бы POLL_INTERVAL_SECONDS*2 (обычно
    # десятки секунд) — Retry-After=600 должен явно доминировать
    assert delay > 500, f"ожидали ~600с из Retry-After, получили {delay:.0f}с"


def test_request_spacing_keeps_burst_within_budget():
    """REV-024: N запросов, равномерно разнесённых на compute_request_spacing
    секунд, не превышают MAX_REQUESTS_PER_MINUTE — даже мгновенным всплеском."""
    n = 100
    interval = 20
    budget = 60
    # имитируем ситуацию из ревью: 100 маршрутов, интервал 20с, бюджет 60/мин —
    # без реального MAX_REQUESTS_PER_MINUTE=60 здесь эффективный интервал
    # должен быть выставлен вызывающей стороной (compute_effective_interval),
    # но сама пропорция должна держать темп в рамках бюджета при любом interval.
    effective_interval = max(interval, -(-n * 60 // budget))  # эквивалент math.ceil
    spacing = watcher.compute_request_spacing(effective_interval, n)
    requests_per_minute = 60 / spacing
    assert requests_per_minute <= budget + 1e-6, (
        f"{requests_per_minute:.1f} запросов/мин превышает бюджет {budget}"
    )

    assert watcher.compute_request_spacing(20, 0) == 20  # без маршрутов — не делим на ноль


def test_fetch_cheapest_handles_malformed_shapes_without_raising():
    """REV-025/REV-027: неожиданная форма JSON (не dict, data не список,
    элементы не dict, нечисловая/NaN/Infinity цена) не должна бросать
    исключение — только None + лог, либо переход к следующему элементу."""
    route = dict(TEST_ROUTE)

    bad_bodies = [
        [], {"data": "not-a-list"}, {"data": ["not-a-dict"]}, {"data": [{}]},
        {"data": [{"price": "N/A"}]},
        {"data": [{"price": float("nan")}]},
        {"data": [{"price": float("inf")}]},
        {"data": [{"price": None, "value": "also-not-a-number"}]},
    ]
    for body in bad_bodies:
        def fake_get(url, params, headers, timeout, _body=body):
            return FakeResponse(status_code=200, json_body=_body)

        original_get = watcher.requests.get
        watcher.requests.get = fake_get
        try:
            result = watcher.fetch_cheapest(route, "token", {})
        finally:
            watcher.requests.get = original_get
        assert result is None, f"неожиданная форма {body!r} должна давать None, не исключение"

    # невалидный элемент, за которым идёт валидный — должен найти второй
    mixed_body = {"data": [{"price": "N/A"}, {"price": 4200, "depart_date": "2026-11-10"}]}

    def fake_get_mixed(url, params, headers, timeout):
        return FakeResponse(status_code=200, json_body=mixed_body)

    original_get = watcher.requests.get
    watcher.requests.get = fake_get_mixed
    try:
        result = watcher.fetch_cheapest(route, "token", {})
    finally:
        watcher.requests.get = original_get
    assert result is not None and result["price"] == 4200


def test_pacing_does_not_burst_after_a_slow_request():
    """REV-026: если предыдущий запрос занял дольше spacing, следующий не
    должен планироваться на уже прошедшее время (что привело бы к всплеску
    без пауз, пока график "догоняет" настоящее время)."""
    spacing = 5.0

    # штатный случай: пришли точно по расписанию
    assert watcher.next_schedule_time(prev_next_at=100.0, spacing=spacing, now=100.0) == 105.0

    # опоздали на 30с (например, медленный запрос) — следующий шаг планируется
    # от текущего момента, а не от устаревшего графика (100+5=105 уже в прошлом)
    next_at = watcher.next_schedule_time(prev_next_at=100.0, spacing=spacing, now=130.0)
    assert next_at == 135.0, "опоздание не должно накапливаться в очередь без пауз"
    assert next_at > 130.0, "следующий запрос обязан быть в будущем, а не немедленным"


def run_all():
    tests = [
        test_is_anomaly_boundary,
        test_build_purchase_link,
        test_route_id,
        test_redact_url,
        test_check_route_alert_and_dedup,
        test_send_failure_does_not_block_record_price,
        test_flush_runs_even_when_fetch_returns_none,
        test_claim_persists_exact_link_used_by_flush,
        test_pending_alert_delivered_despite_baseline_drift,
        test_telegram_429_uses_retry_after_not_generic_backoff,
        test_request_spacing_keeps_burst_within_budget,
        test_fetch_cheapest_handles_malformed_shapes_without_raising,
        test_pacing_does_not_burst_after_a_slow_request,
    ]
    for test in tests:
        test()
        print(f"OK: {test.__name__}")
    print("OK: все проверки прошли")


if __name__ == "__main__":
    run_all()
