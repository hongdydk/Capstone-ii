from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.location_log import DrivingState, LocationLog
from app.models.trip import Trip
from app.schemas.location_log import LocationLogCreate, LocationLogRead
from app.services.rest_stop_inserter import REST_PLAN_SEC

router = APIRouter()

# 정체 판단 속도 임계값 (km/h)
_TRAFFIC_STOP_KMH: float = 5.0

# 휴게소 진입(resting) 후 누적 운전시간 리셋 — 법정 최소 휴식 15분 충족 시만 리셋
_MIN_REST_SEC: int = 15 * 60


def classify_driving_state(speed_kmh: float | None) -> DrivingState:
    """speed_kmh 기반으로 주행 상태를 자동 판정합니다.

    판정 규칙:
      - None           → unknown  (GPS 수신 불가 등)
      - 0 ~ 5 km/h    → traffic_stop  (정체·완전 정지)
      - 5 km/h 초과   → driving

    resting 상태는 기사 앱이 명시적으로 전송해야 합니다.
    (휴게소 진입 등 의도적 정차와 정체를 속도만으로 구분 불가)
    """
    if speed_kmh is None:
        return DrivingState.unknown
    if speed_kmh <= _TRAFFIC_STOP_KMH:
        return DrivingState.traffic_stop
    return DrivingState.driving


async def _calc_accumulated_drive_sec(trip_id: int, db: AsyncSession) -> int:
    """해당 운행의 누적 연속 운전시간(초)을 서버 타임스탬프 기준으로 계산합니다.

    규칙:
    - driving / traffic_stop 구간 시간은 운전시간에 포함 (정체도 법적으로 운전 중)
    - resting 상태가 _MIN_REST_SEC 이상 지속되면 누적 리셋
    - unknown 구간은 무시 (GPS 수신 불가)
    - 폰 시간이 아닌 서버 created_at 기준으로 계산하여 시간 조작 차단
    """
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
    rest_start = None  # 현재 resting 구간 시작 시각

    for i in range(len(logs) - 1):
        curr, nxt = logs[i], logs[i + 1]
        interval = (nxt.created_at - curr.created_at).total_seconds()

        if curr.state == DrivingState.resting:
            if rest_start is None:
                rest_start = curr.created_at
            # resting 지속 시간이 법정 최소 휴식 이상이면 누적 리셋
            rest_duration = (nxt.created_at - rest_start).total_seconds()
            if rest_duration >= _MIN_REST_SEC:
                accumulated = 0
        else:
            rest_start = None
            # driving / traffic_stop → 운전시간 누적
            accumulated += int(interval)

    return accumulated


@router.post("/", response_model=LocationLogRead, status_code=201)
async def create_location_log(
    body: LocationLogCreate, db: AsyncSession = Depends(get_db)
):
    """기사 앱이 주기적으로 GPS 위치를 전송하는 엔드포인트.

    응답에 accumulated_drive_sec 포함:
    - 서버 타임스탬프 기준 누적 연속 운전시간(초)
    - 앱은 이 값으로 REST_PLAN_SEC(6000) 초과 임박 시 replan 호출 판단
    """
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

    # 저장 후 서버 타임스탬프 기준으로 누적 운전시간 계산
    accumulated = await _calc_accumulated_drive_sec(body.trip_id, db)

    # accumulated >= REST_PLAN_SEC(6000초) 이면 replan 필요
    # 앱은 needs_replan=True 수신 시 POST /optimize/replan 호출
    needs_replan = accumulated >= REST_PLAN_SEC

    resp = LocationLogRead.model_validate(log).model_dump()
    resp["accumulated_drive_sec"] = accumulated
    resp["needs_replan"] = needs_replan
    return resp


@router.get("/{trip_id}", response_model=list[LocationLogRead])
async def list_location_logs(trip_id: int, db: AsyncSession = Depends(get_db)):
    """관제 웹이 특정 운행의 위치 이력을 조회하는 엔드포인트."""
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    result = await db.execute(
        select(LocationLog)
        .where(LocationLog.trip_id == trip_id)
        .order_by(LocationLog.recorded_at)
    )
    return result.scalars().all()
