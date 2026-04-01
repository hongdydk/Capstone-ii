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


class OptimizeRequest(BaseModel):
    trip_id: int
    origin_name: str
    origin_lat: float
    origin_lon: float
    initial_drive_sec: int = 0
    route_mode: Literal["local", "long_distance"] = "long_distance"
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
    route_mode: Literal["local", "long_distance"] = "long_distance"
    vehicle_height_m: float | None = None
    vehicle_weight_kg: float | None = None
    vehicle_length_cm: float | None = None
    vehicle_width_cm: float | None = None
