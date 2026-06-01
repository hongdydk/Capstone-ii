"""time_windows 변환·검증 단위 테스트 (GraphHopper 불필요)."""

from datetime import datetime

import pytest

from app.services.time_windows import (
    TimeWindowValidationError,
    apply_resolved_windows_to_dict,
    clock_on_date,
    demo_time_window_to_sec,
    parse_instant,
    resolve_reference_departure_at,
    resolve_time_window_bounds,
    SEOUL,
)


REF = datetime(2026, 5, 15, 9, 0, tzinfo=SEOUL)


def test_parse_instant_naive_assumes_seoul():
    dt = parse_instant("2026-05-15T15:00:00")
    assert dt.tzinfo == SEOUL
    assert dt.hour == 15


def test_latest_at_must_arrive_by_offset():
    e, l = resolve_time_window_bounds(
        REF,
        latest_at="2026-05-15T15:00:00",
    )
    assert e is None
    assert l == 6 * 3600  # 09:00 → 15:00


def test_earliest_at_open_offset():
    e, l = resolve_time_window_bounds(
        REF,
        earliest_at="2026-05-15T10:30:00",
    )
    assert e == 90 * 60
    assert l is None


def test_tw_close_without_service_date_uses_reference_day():
    e, l = resolve_time_window_bounds(
        REF,
        tw_close="18:00",
    )
    assert e is None
    assert l == 9 * 3600


def test_tw_open_close_with_service_date():
    e, l = resolve_time_window_bounds(
        REF,
        tw_open="08:00",
        tw_close="12:00",
        service_date="2026-05-16",
    )
    assert e == 23 * 3600  # 다음날 08:00
    assert l == 27 * 3600  # 다음날 12:00


def test_datetime_wins_over_legacy_sec():
    _, l = resolve_time_window_bounds(
        REF,
        latest_at="2026-05-15T15:00:00",
        latest_sec=1,
    )
    assert l == 6 * 3600

    e, _ = resolve_time_window_bounds(
        REF,
        earliest_at="2026-05-15T10:00:00",
        earliest_sec=99999,
    )
    assert e == 3600


def test_legacy_sec_only():
    e, l = resolve_time_window_bounds(REF, earliest_sec=3600, latest_sec=7200)
    assert e == 3600
    assert l == 7200


def test_latest_before_earliest_raises():
    with pytest.raises(TimeWindowValidationError, match="마감"):
        resolve_time_window_bounds(
            REF,
            earliest_at="2026-05-15T18:00:00",
            latest_at="2026-05-15T12:00:00",
        )


def test_window_too_far_past_raises():
    with pytest.raises(TimeWindowValidationError, match="너무 이전"):
        resolve_time_window_bounds(
            REF,
            latest_at="2026-05-01T09:00:00",
        )


def test_apply_resolved_windows_to_dict():
    wp = {"name": "고객", "latest_at": "2026-05-15T15:00:00"}
    apply_resolved_windows_to_dict(wp, REF, label="고객")
    assert wp["latest_sec"] == 6 * 3600


def test_resolve_reference_explicit_over_trip():
    ref = resolve_reference_departure_at(
        "2026-05-15T08:00:00",
        trip_departure_time="2026-05-15T09:00:00",
    )
    assert ref.hour == 8


def test_demo_time_window_minutes_to_sec():
    assert demo_time_window_to_sec((60, 180)) == (3600, 10800)
    assert demo_time_window_to_sec(None) == (None, None)


def test_clock_on_date_invalid_raises():
    with pytest.raises(TimeWindowValidationError):
        clock_on_date("25:99", REF.date())
