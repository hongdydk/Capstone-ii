from typing import Literal

from pydantic import BaseModel


class RouteNodeSchema(BaseModel):
    """최적화 결과 경로 1개 노드. optimized_route JSONB 요소."""
    type: str  # origin | waypoint | destination | rest_stop
    name: str
    lat: float
    lon: float
    min_rest_minutes: int | None = None


class ExtraStopSchema(BaseModel):
    stop_type: str  # waypoint | destination | rest_preferred
    name: str
    lat: float
    lon: float
    note: str | None = None
    # 도착 허용 시간 범위 — 출발 기준 경과 초
    # 예) earliest_sec=3600, latest_sec=7200 → 출발 후 1~2시간 사이 도착
    earliest_sec: int | None = None
    latest_sec: int | None = None
    # 상차·하차 쌍 지정 — pickup_id 와 동일한 값을 가진 delivery stop 이 반드시 뒤에 방문됨
    # 예) pickup stop: pickup_id="cargo1", delivery stop: delivery_for="cargo1"
    pickup_id: str | None = None      # 이 경유지가 상차지임을 표시하는 식별자
    delivery_for: str | None = None   # 이 경유지가 어떤 pickup_id의 하차지인지


class OptimizeRequest(BaseModel):
    trip_id: int
    origin_name: str
    origin_lat: float
    origin_lon: float
    initial_drive_sec: int = 0
    route_mode: Literal["local", "long_distance", "auto"] = "auto"
    # 기사가 직접 입력 시 trip 등록값을 override
    vehicle_height_m: float | None = None
    vehicle_weight_kg: float | None = None
    vehicle_length_cm: float | None = None
    vehicle_width_cm: float | None = None
    extra_stops: list[ExtraStopSchema] | None = None


class OptimizeResponse(BaseModel):
    trip_id: int
    route: list[RouteNodeSchema]
    total_distance_km: float
    estimated_duration_min: float
    rest_stops_count: int


class ReplanRequest(BaseModel):
    trip_id: int
    current_lat: float
    current_lon: float
    current_name: str
    current_drive_sec: int
    remaining_waypoints: list[dict]
    dest_name: str
    dest_lat: float
    dest_lon: float
    is_emergency: bool = False  # 교통정체·사고 등 교통운수사업법 [별표3] 다항 긴급 예외 적용 여부
    route_mode: Literal["local", "long_distance", "auto"] = "auto"
    vehicle_height_m: float | None = None
    vehicle_weight_kg: float | None = None
    vehicle_length_cm: float | None = None
    vehicle_width_cm: float | None = None
