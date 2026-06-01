"""캘린더·시각 시간창 → 출발 기준 경과 초 변환 (OR-Tools 입력용)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")

# reference 대비 허용 오프셋 범위 (초)
MAX_PAST_SEC = 7 * 24 * 3600
MAX_FUTURE_SEC = 30 * 24 * 3600


class TimeWindowValidationError(ValueError):
    """시간창 파싱·논리 오류 — API에서 422로 변환."""


def parse_instant(value: str) -> datetime:
    """ISO-8601 시각을 Asia/Seoul aware datetime으로 파싱."""
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SEOUL)
    return dt.astimezone(SEOUL)


def parse_service_date(value: str) -> date:
    return date.fromisoformat(value.strip())


def parse_clock(hhmm: str) -> tuple[int, int]:
    parts = hhmm.strip().split(":")
    if len(parts) != 2:
        raise TimeWindowValidationError(f"시각 형식은 HH:MM 이어야 합니다: {hhmm!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise TimeWindowValidationError(f"유효하지 않은 시각입니다: {hhmm!r}")
    return hour, minute


def clock_on_date(hhmm: str, day: date, *, tz: ZoneInfo = SEOUL) -> datetime:
    hour, minute = parse_clock(hhmm)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def resolve_reference_departure_at(
    explicit: str | None,
    *,
    trip_departure_time: str | None = None,
    default_now: bool = True,
) -> datetime:
    """요청·trip 출발 시각 중 기준 시각(anchor)을 결정합니다."""
    if explicit:
        return parse_instant(explicit)
    if trip_departure_time:
        return parse_instant(trip_departure_time)
    if default_now:
        return datetime.now(SEOUL)
    raise TimeWindowValidationError(
        "reference_departure_at(또는 trip.departure_time)이 필요합니다."
    )


def _has_calendar_earliest(
    *,
    earliest_at: str | None,
    tw_open: str | None,
) -> bool:
    return bool(earliest_at or tw_open)


def _has_calendar_latest(
    *,
    latest_at: str | None,
    tw_close: str | None,
) -> bool:
    return bool(latest_at or tw_close)


def _offset_sec(reference: datetime, instant: datetime) -> int:
    return int((instant - reference).total_seconds())


def _validate_bounds(
    earliest: int | None,
    latest: int | None,
    *,
    label: str = "노드",
) -> None:
    if earliest is not None and latest is not None and earliest > latest:
        raise TimeWindowValidationError(
            f"{label}: 도착 마감(latest)이 개점(earliest)보다 이릅니다."
        )
    for name, val in (("earliest", earliest), ("latest", latest)):
        if val is None:
            continue
        if val < -MAX_PAST_SEC:
            raise TimeWindowValidationError(
                f"{label}: {name} 시각이 기준 출발(reference_departure_at)보다 "
                f"너무 이전입니다 ({val}초)."
            )
        if val > MAX_FUTURE_SEC:
            raise TimeWindowValidationError(
                f"{label}: {name} 시각이 기준 출발보다 너무 미래입니다 ({val}초)."
            )


def resolve_time_window_bounds(
    reference: datetime,
    *,
    earliest_at: str | None = None,
    latest_at: str | None = None,
    tw_open: str | None = None,
    tw_close: str | None = None,
    service_date: str | None = None,
    earliest_sec: int | None = None,
    latest_sec: int | None = None,
    label: str = "노드",
) -> tuple[int | None, int | None]:
    """노드 도착 허용 구간을 reference 기준 경과 초 (earliest, latest)로 반환.

    우선순위: ISO/datetime 필드(earliest_at, latest_at, tw_open, tw_close)가
    동일 경계의 earliest_sec/latest_sec 보다 우선합니다.

    - earliest_at / tw_open: 이 시각 **이전** 도착 불가 (개점·오픈)
    - latest_at / tw_close: 이 시각 **까지** 도착 필요 (마감·폐점)
    """
    ref = reference.astimezone(SEOUL)
    svc_day = parse_service_date(service_date) if service_date else ref.date()

    use_calendar_e = _has_calendar_earliest(earliest_at=earliest_at, tw_open=tw_open)
    use_calendar_l = _has_calendar_latest(latest_at=latest_at, tw_close=tw_close)

    e: int | None = None
    l: int | None = None

    if use_calendar_e:
        if earliest_at:
            e = _offset_sec(ref, parse_instant(earliest_at))
        elif tw_open:
            e = _offset_sec(ref, clock_on_date(tw_open, svc_day))
    elif earliest_sec is not None:
        e = earliest_sec

    if use_calendar_l:
        if latest_at:
            l = _offset_sec(ref, parse_instant(latest_at))
        elif tw_close:
            l = _offset_sec(ref, clock_on_date(tw_close, svc_day))
    elif latest_sec is not None:
        l = latest_sec

    _validate_bounds(e, l, label=label)
    return e, l


def apply_resolved_windows_to_dict(
    wp: dict,
    reference: datetime,
    *,
    label: str | None = None,
) -> dict:
    """waypoint dict에 캘린더 필드가 있으면 earliest_sec/latest_sec로 정규화."""
    node_label = label or wp.get("name", "노드")
    e, l = resolve_time_window_bounds(
        reference,
        earliest_at=wp.get("earliest_at"),
        latest_at=wp.get("latest_at"),
        tw_open=wp.get("tw_open"),
        tw_close=wp.get("tw_close"),
        service_date=wp.get("service_date"),
        earliest_sec=wp.get("earliest_sec"),
        latest_sec=wp.get("latest_sec"),
        label=node_label,
    )
    if e is not None:
        wp["earliest_sec"] = e
    if l is not None:
        wp["latest_sec"] = l
    return wp


def copy_time_fields_to_dict(source: object, target: dict) -> None:
    """Pydantic 모델 또는 dict에서 시간창 입력 필드를 target에 복사."""
    if isinstance(source, dict):
        keys = (
            "earliest_at",
            "latest_at",
            "tw_open",
            "tw_close",
            "service_date",
            "earliest_sec",
            "latest_sec",
        )
        for k in keys:
            if k in source and source[k] is not None:
                target[k] = source[k]
        return
    for k in (
        "earliest_at",
        "latest_at",
        "tw_open",
        "tw_close",
        "service_date",
        "earliest_sec",
        "latest_sec",
    ):
        val = getattr(source, k, None)
        if val is not None:
            target[k] = val


def demo_time_window_to_sec(
    time_window: tuple[int, int] | None,
) -> tuple[int | None, int | None]:
    """deprecated demo time_window (분) → (earliest_sec, latest_sec)."""
    if not time_window:
        return None, None
    return time_window[0] * 60, time_window[1] * 60
