from typing import Any, Literal

from pydantic import BaseModel


class RouteNode(BaseModel):
    """최적화 경로의 단일 노드."""
    type: str           # "origin" | "waypoint" | "rest_stop" | "destination"
    name: str
    lat: float
    lon: float
    min_rest_minutes: int | None = None   # rest_stop 노드에만 사용
    estimated_arrival_min: float | None = None


class ExtraStop(BaseModel):
    """운전자 또는 관리자가 직접 추가하는 경유 지점.

    stop_type:
      "waypoint"       — 거래처·납품처 등 방문 필수 지점.
                         기존 waypoints 와 함께 TSP 순서 최적화 대상이 됩니다.
      "destination"    — 실제 카운터 등 최종 도착지 변경.
                         해당 지점이 새로운 최종 목적지가 되고,
                         원래 목적지는 경유지로 자동 삽입됩니다.
                         여러 개일 경우 마지막 항목이 최종 목적지,
                         나머지는 경유지로 처리됩니다.
      "rest_preferred" — 운전자가 선호하는 특정 휴게소·졸음쉬이터.
                         법정 휴게 삽입 후보 목록 맸 앞에 추가되어
                         우회 비용이 비슷할 경우 우선 선택됩니다.
    """
    name: str
    lat: float
    lon: float
    stop_type: Literal["waypoint", "destination", "rest_preferred"] = "waypoint"
    note: str | None = None   # 메모 (예: "오전 9시 이후 방문", "1층 냉장 하역")


# ── 1. 기사 경로 최적화 요청 ──────────────────────────────────────────────────

class OptimizeRequest(BaseModel):
    """기사 출발 → 단일 차량 경로 최적화.

    기사가 현재 위치(출발지)를 전달하면,
    trip에 저장된 경유지·목적지·차량 제원으로 최적 동선을 계산합니다.
    경유지·목적지는 관리자가 trip 생성 시 이미 DB에 저장되어 있습니다.
    """
    trip_id: int
    # 기사의 현재 출발 위치 (집, 차고지, 이전 배송지 등)
    origin_name: str = "출발지"
    origin_lat: float
    origin_lon: float
    # 운전자가 직접 추가하는 경유 지점 (선호 휴게소, 긴급 납품처 등)
    extra_stops: list[ExtraStop] = []
    # 누적 운전시간 이어받기 (기사가 이미 운전 중인 경우, 기본 0)
    initial_drive_sec: int = 0
    # 차량 제원 override (미입력 시 trip에 저장된 값 사용)
    vehicle_height_m: float | None = None
    vehicle_weight_kg: float | None = None
    vehicle_length_cm: float | None = None
    vehicle_width_cm: float | None = None


class OptimizeResponse(BaseModel):
    trip_id: int
    route: list[RouteNode]
    total_distance_km: float
    estimated_duration_min: float
    rest_stops_count: int


# ── 2. 시스템 재경로 요청 ──────────────────────────────────────────────────────

class ReplanRequest(BaseModel):
    """운행 중 재경로 요청 — 시스템 자동 트리거 또는 운전자 직접 호출.

    정체·경로 이탈 등으로 누적 운전시간이 한도에 가까워졌을 때
    현재 위치와 남은 경유지를 기반으로 경로를 재계산합니다.
    initial_drive_sec 이 insert_rest_stops() 로 그대로 전달되어
    즉시 휴게소 삽입이 필요하면 자동으로 처리됩니다.
    """
    trip_id: int
    current_lat: float
    current_lon: float
    current_name: str = "현재위치"
    current_drive_sec: int = 0          # 누적 운전시간 (초)
    remaining_waypoints: list[dict[str, Any]] = []
    # 운전자가 운행 중 추가하는 경유 지점 (거래처 추가, 선호 휴게소 지정)
    extra_stops: list[ExtraStop] = []
    dest_name: str
    dest_lat: float
    dest_lon: float
    # 화물차 제원
    vehicle_height_m: float | None = None
    vehicle_weight_kg: float | None = None
    vehicle_length_cm: float | None = None
    vehicle_width_cm: float | None = None


# ── 3. 배차 요청 (향후 구현 예정) ─────────────────────────────────────────────

class DispatchRequest(BaseModel):
    """관리자 다수 차량 배차 요청.

    TODO: OR-Tools CVRP 기반 다수 차량 배분 — 향후 구현 예정.
    여러 차량에 경유지를 최적 분배한 뒤 각 차량별 경로를 반환합니다.
    """
    # 차고지 (공통 출발점)
    depot_name: str
    depot_lat: float
    depot_lon: float
    # 배분할 전체 경유지 목록
    waypoints: list[dict[str, Any]]
    # 투입 차량 목록 [{"id": int, "height_m": float, "weight_kg": float, ...}]
    vehicles: list[dict[str, Any]]


class DispatchResponse(BaseModel):
    """배차 결과 — 차량별 최적 경로 목록."""
    # TODO: 구현 시 상세 필드 추가
    assignments: list[dict[str, Any]]   # [{"vehicle_id": int, "route": [...]}]
