from typing import Literal

from pydantic import BaseModel, Field


class StopTimeWindowInput(BaseModel):
    """노드별 도착 시간 제약 (캘린더 우선, 경과 초는 하위 호환).

    기준 시각은 요청의 reference_departure_at(또는 trip.departure_time 등)입니다.
    우선순위: 동일 경계에서 ISO/HH:MM 필드가 earliest_sec/latest_sec 보다 우선합니다.
    """

    # earliest_at: 이 시각 이전 도착 불가 (개점·오픈)
    earliest_at: str | None = Field(
        default=None,
        description="ISO-8601 — 이 시각 이전 도착 불가 (개점)",
    )
    # latest_at: 이 시각까지 도착 필요 (마감·must arrive by)
    latest_at: str | None = Field(
        default=None,
        description="ISO-8601 — 이 시각까지 도착 필요 (마감)",
    )
    tw_open: str | None = Field(
        default=None,
        description='당일 개점 시각 "HH:MM" (service_date 없으면 reference 날짜)',
    )
    tw_close: str | None = Field(
        default=None,
        description='당일 마감 시각 "HH:MM" — 이 시각까지 도착 (service_date 없으면 reference 날짜)',
    )
    service_date: str | None = Field(
        default=None,
        description='tw_open/tw_close 적용 일자 "YYYY-MM-DD"',
    )
    earliest_sec: int | None = Field(
        default=None,
        description="[deprecated] 출발 기준 최소 도착 경과 초 — 캘린더 필드가 있으면 무시",
    )
    latest_sec: int | None = Field(
        default=None,
        description="[deprecated] 출발 기준 최대 도착 경과 초 — 캘린더 필드가 있으면 무시",
    )


class RouteNodeSchema(BaseModel):
    """최적화 결과 경로 1개 노드. optimized_route JSONB 요소."""
    type: str  # origin | waypoint | destination | rest_stop
    name: str
    lat: float
    lon: float
    min_rest_minutes: int | None = None


class ExtraStopSchema(StopTimeWindowInput):
    stop_type: str  # waypoint | pickup | delivery | destination | rest_preferred
    name: str
    lat: float
    lon: float
    note: str | None = None
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
    reference_departure_at: str | None = Field(
        default=None,
        description="ISO-8601 — 모든 시간창 변환의 기준 출발 시각 (미지정 시 trip.departure_time 또는 현재 시각)",
    )
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
    reference_departure_at: str | None = Field(
        default=None,
        description="ISO-8601 — 재탐색 시각 기준(미지정 시 현재 시각, Asia/Seoul)",
    )
    vehicle_height_m: float | None = None
    vehicle_weight_kg: float | None = None
    vehicle_length_cm: float | None = None
    vehicle_width_cm: float | None = None

