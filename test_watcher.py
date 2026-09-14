"""Assert-based self-check для watcher.py. Без pytest/unittest, без сети.

Запуск: python test_watcher.py
"""
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
    ]
    for test in tests:
        test()
        print(f"OK: {test.__name__}")
    print("OK: все проверки прошли")


if __name__ == "__main__":
    run_all()
