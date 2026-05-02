from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.location_log import DrivingState, LocationLog
from app.models.trip import Trip
from app.schemas.location_log import LocationLogCreate, LocationLogRead
from app.services.rest_stop_inserter import REST_PLAN_SEC

# 정체 판단 속도 임계값 (km/h)
TRAFFIC_STOP_KMH: float = 5.0

# 휴게소 진입(resting) 후 누적 운전시간 리셋 — 법정 최소 휴식 15분 충족 시만 리셋
MIN_REST_SEC: int = 15 * 60


def classify_driving_state(speed_kmh: float | None) -> DrivingState:
    if speed_kmh is None:
        return DrivingState.unknown
    if speed_kmh <= TRAFFIC_STOP_KMH:
        return DrivingState.traffic_stop
    return DrivingState.driving


async def calc_accumulated_drive_sec(trip_id: int, db: AsyncSession) -> int:
    result = await db.execute(
        select(LocationLog)
        .where(
            LocationLog.trip_id == trip_id,
            LocationLog.state.in_([
                DrivingState.driving,
                DrivingState.traffic_stop,
                DrivingState.resting,
            ]),
        )
        .order_by(LocationLog.created_at)
    )
    logs = result.scalars().all()

    if not logs:
        return 0

    accumulated = 0
    rest_start = None

    for i in range(len(logs) - 1):
        curr, nxt = logs[i], logs[i + 1]
        interval = (nxt.created_at - curr.created_at).total_seconds()

        if curr.state == DrivingState.resting:
            if rest_start is None:
                rest_start = curr.created_at
            rest_duration = (nxt.created_at - rest_start).total_seconds()
            if rest_duration >= MIN_REST_SEC:
                accumulated = 0
        else:
            rest_start = None
            accumulated += int(interval)

    return accumulated


async def create_location_log_and_status(
    body: LocationLogCreate,
    db: AsyncSession,
) -> dict:
    trip = await db.get(Trip, body.trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    data = body.model_dump()
    if data["state"] == DrivingState.unknown and data["speed_kmh"] is not None:
        data["state"] = classify_driving_state(data["speed_kmh"])

    log = LocationLog(**data)
    db.add(log)
    await db.commit()
    await db.refresh(log)

    accumulated = await calc_accumulated_drive_sec(body.trip_id, db)
    needs_replan = accumulated >= REST_PLAN_SEC

    resp = LocationLogRead.model_validate(log).model_dump()
    resp["accumulated_drive_sec"] = accumulated
    resp["needs_replan"] = needs_replan
    return resp