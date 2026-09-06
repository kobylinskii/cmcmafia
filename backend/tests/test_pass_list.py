"""Список ФИО на пропуск для игроков не из МГУ.

Клуб заказывает пропуска списком заранее, поэтому неделя здесь не
календарная: она переключается на наступающую в клубный рубеж (по умолчанию
воскресенье 18:00 МСК). Проверяются обе половины: арифметика рубежа и отбор
людей внутри окна.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.pass_list_service import week_window
from app.timeutil import CLUB_TZ
from tests.conftest import BOT_HEADERS, make_bot_admin

ADMIN_TG = 9100


def _moscow(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=CLUB_TZ)


def test_week_flips_exactly_at_the_rollover():
    """Игра, начинающаяся ровно в момент рубежа, относится к новой неделе."""
    just_before = week_window(weekday=6, time_hhmm="18:00", now=_moscow("2026-09-06 17:59"))
    at_rollover = week_window(weekday=6, time_hhmm="18:00", now=_moscow("2026-09-06 18:00"))
    midweek = week_window(weekday=6, time_hhmm="18:00", now=_moscow("2026-09-02 12:00"))

    assert just_before == (_moscow("2026-08-30 18:00"), _moscow("2026-09-06 18:00"))
    assert at_rollover == (_moscow("2026-09-06 18:00"), _moscow("2026-09-13 18:00"))
    # Середина недели попадает в то же окно, что и последние минуты перед
    # рубежом -- иначе список «дёргался» бы в течение недели.
    assert midweek == just_before
    assert at_rollover[1] - at_rollover[0] == timedelta(days=7)


def _register_bot_player(client, *, telegram_id: int, nickname: str, affiliation: str,
                         full_name: str | None) -> dict:
    resp = client.post(
        "/api/bot/players/register",
        headers=BOT_HEADERS,
        params={"telegram_id": telegram_id},
        json={
            "telegram_id": telegram_id,
            "phone": f"7900{telegram_id:07d}",
            "nickname": nickname,
            "salutation": "господин",
            "full_name": full_name,
            "affiliation": affiliation,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_session(client, *, starts_at: datetime, game_type: str = "funky") -> int:
    resp = client.post(
        "/api/bot/admin/sessions",
        headers=BOT_HEADERS,
        params={"telegram_id": ADMIN_TG},
        json={
            "starts_at": starts_at.isoformat(),
            "location": "ВМК МГУ",
            "game_type": game_type,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _register(client, *, game_id: int, telegram_id: int, role_kind: str = "player") -> None:
    resp = client.post(
        f"/api/bot/sessions/{game_id}/register",
        headers=BOT_HEADERS,
        params={"telegram_id": telegram_id},
        json={"telegram_id": telegram_id, "role_kind": role_kind},
    )
    assert resp.status_code == 200 and resp.json()["ok"], resp.text


def _pass_list(client, headers) -> dict:
    resp = client.get("/api/admin/pass-list", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _settings_for_a_wide_window(client, headers) -> tuple[datetime, datetime]:
    """Ставит рубеж на завтра 23:59, чтобы внутри окна гарантированно было
    больше суток будущего -- иначе тест зависел бы от часа своего запуска."""
    tomorrow = datetime.now(CLUB_TZ) + timedelta(days=1)
    resp = client.put(
        "/api/admin/settings/pass-week",
        headers=headers,
        json={
            "pass_week_rollover_weekday": tomorrow.weekday(),
            "pass_week_rollover_time": "23:59",
        },
    )
    assert resp.status_code == 200, resp.text
    return week_window(weekday=tomorrow.weekday(), time_hhmm="23:59")


def test_only_people_who_need_a_pass_and_only_this_week(admin):
    client, headers = admin
    make_bot_admin(ADMIN_TG, nickname="Ведущий", slug="host-admin")
    _, week_end = _settings_for_a_wide_window(client, headers)

    outsider = _register_bot_player(
        client, telegram_id=9001, nickname="Чужак", affiliation="outside_need_pass",
        full_name="Иванов Иван Иванович",
    )
    _register_bot_player(
        client, telegram_id=9002, nickname="Свой", affiliation="vmk",
        full_name="Петров Пётр Петрович",
    )
    _register_bot_player(
        client, telegram_id=9003, nickname="Мгушник", affiliation="mgu_no_pass",
        full_name="Сидоров Сидор Сидорович",
    )
    _register_bot_player(
        client, telegram_id=9004, nickname="Поздний", affiliation="outside_need_pass",
        full_name="Кузнецов Кузьма Кузьмич",
    )

    this_week = _create_session(client, starts_at=datetime.now(CLUB_TZ) + timedelta(hours=2))
    next_week = _create_session(client, starts_at=week_end + timedelta(hours=2))
    for telegram_id in (9001, 9002, 9003):
        _register(client, game_id=this_week, telegram_id=telegram_id)
    _register(client, game_id=next_week, telegram_id=9004)

    entries = _pass_list(client, headers)["entries"]
    assert [e["nickname"] for e in entries] == [outsider["nickname"]]
    assert entries[0]["full_name"] == "Иванов Иван Иванович"
    assert [g["game_id"] for g in entries[0]["games"]] == [this_week]


def test_staff_reserve_and_unconfirmed_all_need_a_pass(admin):
    """Пропуск нужен человеку, а не его роли: ведущий, запасной и ещё не
    подтверждённый админом новичок проходят через ту же вертушку."""
    client, headers = admin
    make_bot_admin(ADMIN_TG, nickname="Ведущий", slug="host-admin")
    _settings_for_a_wide_window(client, headers)

    for telegram_id, nickname, full_name in (
        (9011, "Судья", "Аксёнов Артём Артёмович"),
        (9012, "Запасной", "Борисов Борис Борисович"),
        (9013, "Основной", "Власов Влад Владович"),
    ):
        _register_bot_player(
            client, telegram_id=telegram_id, nickname=nickname,
            affiliation="outside_need_pass", full_name=full_name,
        )

    game_id = _create_session(client, starts_at=datetime.now(CLUB_TZ) + timedelta(hours=3))
    _register(client, game_id=game_id, telegram_id=9011, role_kind="staff")
    _register(client, game_id=game_id, telegram_id=9013, role_kind="player")
    reserve = client.post(
        f"/api/bot/sessions/{game_id}/reserve",
        headers=BOT_HEADERS,
        params={"telegram_id": 9012},
        json={"telegram_id": 9012},
    )
    assert reserve.status_code == 200 and reserve.json()["ok"], reserve.text

    entries = _pass_list(client, headers)["entries"]
    by_name = {e["full_name"]: e for e in entries}
    assert set(by_name) == {
        "Аксёнов Артём Артёмович",
        "Борисов Борис Борисович",
        "Власов Влад Владович",
    }
    assert by_name["Аксёнов Артём Артёмович"]["games"][0]["role"] == "host"
    assert by_name["Борисов Борис Борисович"]["games"][0]["role"] == "reserve"
    assert by_name["Власов Влад Владович"]["games"][0]["role"] == "player"
    # Все трое пришли из бота и админом ещё не проверены -- пропуск им всё
    # равно нужен, но статус виден, чтобы админ мог решить иначе.
    assert {e["confirmation_status"] for e in entries} == {"pending"}


def test_rollover_setting_round_trips_and_is_validated(admin):
    client, headers = admin

    default = client.get("/api/admin/settings/pass-week", headers=headers).json()
    assert default == {"pass_week_rollover_weekday": 6, "pass_week_rollover_time": "18:00"}

    updated = client.put(
        "/api/admin/settings/pass-week",
        headers=headers,
        json={"pass_week_rollover_weekday": 4, "pass_week_rollover_time": "20:30"},
    )
    assert updated.status_code == 200, updated.text
    assert client.get("/api/admin/settings/pass-week", headers=headers).json() == {
        "pass_week_rollover_weekday": 4,
        "pass_week_rollover_time": "20:30",
    }

    for bad in ({"pass_week_rollover_weekday": 7, "pass_week_rollover_time": "20:30"},
                {"pass_week_rollover_weekday": 4, "pass_week_rollover_time": "25:00"},
                {"pass_week_rollover_weekday": 4, "pass_week_rollover_time": "8:00"}):
        assert client.put("/api/admin/settings/pass-week", headers=headers, json=bad).status_code == 422
