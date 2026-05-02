from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.location_log import LocationLog
from app.models.trip import Trip
from app.schemas.location_log import LocationLogCreate, LocationLogRead
from app.services.realtime import create_location_log_and_status

router = APIRouter()


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
    return await create_location_log_and_status(body, db)


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
