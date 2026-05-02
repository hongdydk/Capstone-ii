from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.location_log import DrivingState


class LocationLogCreate(BaseModel):
    trip_id: int
    latitude: float
    longitude: float
    speed_kmh: Optional[float] = None
    state: DrivingState = DrivingState.unknown


class LocationLogRead(BaseModel):
    id: int
    trip_id: int
    latitude: float
    longitude: float
    speed_kmh: Optional[float]
    state: DrivingState
    recorded_at: datetime
    created_at: datetime
    updated_at: datetime
    # 서버 타임스탬프 기반 누적 운전시간(초) — POST 응답에만 채워짐, GET 목록은 0
    accumulated_drive_sec: int = 0
    # 재경로 계산 필요 여부 — accumulated_drive_sec >= REST_PLAN_SEC(6000) 시 True
    # 앱은 이 값이 True이면 POST /optimize/replan을 호출해야 함
    needs_replan: bool = False

    model_config = {"from_attributes": True}
