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
    stop_type: str  # waypoint | pickup | delivery | destination | rest_preferred
    name: str
    lat: float
    lon: float
    note: str | None = None
    # 도착 허용 시간 범위 — 출발 기준 경과 초
    # 예) earliest_sec=3600, latest_sec=7200 → 출발 후 1~2시간 사이 도착
    earliest_sec: int | None = None
    latest_sec: int | None = None
    # 상차·하차 그룹 지정 — 같은 cargo_id를 가진 pickup 노드가 delivery 노드보다 먼저 방문됨
    # 1:N (한 상차지 → 여러 하차지), N:1 (여러 상차지 → 한 하차지), N:M 모두 지원
    # 같은 cargo_id 내 모든 pickup × delivery 조합이 OR-Tools 순서 제약으로 자동 등록됨
    cargo_id: str | None = None  # 화물 묶음 식별자 (예: "A", "화물1")
    # 이 지점에서 상차(+) 또는 하차(-) 되는 화물 무게(kg)
    # 예) 상차지: 500.0, 하차지: -500.0 → 차량 누적 적재량 계산에 사용
    cargo_weight_kg: float | None = None


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
    dest_name: str | None = None
    dest_lat: float | None = None
    dest_lon: float | None = None
    is_emergency: bool = False  # 교통정체·사고 등 교통운수사업법 [별표3] 다항 긴급 예외 적용 여부
    route_mode: Literal["local", "long_distance", "auto"] = "auto"
    vehicle_height_m: float | None = None
    vehicle_weight_kg: float | None = None
    vehicle_length_cm: float | None = None
    vehicle_width_cm: float | None = None


# ── VRPTW 다차량 자동 배차 스키마 ──────────────────────────────────────────────

class DispatchNodeInput(BaseModel):
    """배송 노드 — 배송지 좌표·시간창·화물 중량."""
    name: str
    lat: float
    lon: float
    earliest_sec: int = 0         # 출발 기준 허용 최조 도착 경과 초
    latest_sec: int = 86400       # 출발 기준 허용 최대 도착 경과 초 (기본 24시간)
    cargo_weight_kg: float = 0.0  # 이 노드에서 배송하는 화물 중량(kg)


class DispatchVehicleInput(BaseModel):
    """투입 차량 — 이름과 최대 적재 중량."""
    name: str
    max_load_kg: float = 0.0  # 0이면 용량 제한 없음


class DispatchRequest(BaseModel):
    depot_name: str
    depot_lat: float
    depot_lon: float
    vehicles: list[DispatchVehicleInput]
    nodes: list[DispatchNodeInput]
    profile: str = "truck"
    time_limit_seconds: int = 30  # OR-Tools 탐색 시간 제한 (초)


class DispatchVehicleRoute(BaseModel):
    vehicle_name: str
    route: list[RouteNodeSchema]
    polyline: list[list[float]]
    total_distance_km: float
    estimated_duration_min: float
    total_load_kg: float
    rest_stops_count: int


class DispatchResponse(BaseModel):
    routes: list[DispatchVehicleRoute]
    unassigned_nodes: list[str]  # 배정하지 못한 노드 이름 목록
