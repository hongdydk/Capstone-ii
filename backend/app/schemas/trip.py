from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from app.models.trip import TripStatus


class WaypointIn(BaseModel):
    name: str
    lat: float
    lon: float


class TripCreate(BaseModel):
    """관리자 배차 생성 요청.

    출발지는 기사가 출발 시점에 직접 전달하므로 여기서는 입력하지 않습니다.
    """
    driver_id: int
    vehicle_id: int
    # 목적지 — 관리자가 설정
    dest_name: str
    dest_lat: float
    dest_lon: float
    # 경유지 목록 — 관리자가 설정
    waypoints: list[WaypointIn] = []
    # 차량 제원 — 통행 제한 도로 자동 우회에 사용
    vehicle_height_m: float | None = None
    vehicle_weight_kg: float | None = None
    vehicle_length_cm: float | None = None
    vehicle_width_cm: float | None = None
    # 출발 예정 시각 (ISO-8601) — 타임머신 예측 교통 API 사용 시 설정
    # 예: "2026-03-26T08:00:00+0900"
    departure_time: str | None = None


class TripStatusUpdate(BaseModel):
    status: TripStatus


class TripResponse(BaseModel):
    id: int
    driver_id: int
    vehicle_id: int
    # 출발지 — 기사가 optimize 호출 시 채워짐 (그 전까지 null)
    origin_name: Optional[str]
    origin_lat: Optional[float]
    origin_lon: Optional[float]
    dest_name: str
    dest_lat: float
    dest_lon: float
    waypoints: Optional[Any]
    vehicle_height_m: Optional[float]
    vehicle_weight_kg: Optional[float]
    vehicle_length_cm: Optional[float]
    vehicle_width_cm: Optional[float]
    departure_time: Optional[str]
    status: TripStatus
    optimized_route: Optional[Any]
    total_driving_seconds: int
    total_rest_seconds: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}
