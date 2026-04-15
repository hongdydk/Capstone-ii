from dataclasses import dataclass, field
from math import atan2, cos, radians, sin, sqrt

# 법정 상수 (변경 금지)
REST_PLAN_SEC: int = 6_000    # 1시간 40분 — 선제적 휴게 삽입 임계값
MAX_DRIVE_SEC: int = 7_200    # 2시간 — 법정 최대 연속 운전
MIN_REST_MIN: int  = 15       # 법정 최소 휴식 시간 (분)

# 긴급 예외 상수 — 화물자동차 운수사업법 시행규칙 [별표3] 다항
# 교통사고·차량고장·교통정체 등 불가피한 사유로 2시간 연속운전 후 휴게 확보가 불가능한 경우
EMERGENCY_EXTEND_SEC: int = 3_600   # 1시간 연장 허용 → 최대 연속 운전 10,800초(3시간)
EMERGENCY_REST_MIN: int   = 30      # 긴급 연장 사용 시 의무 휴식 시간 (분, 일반 15분의 2배)

# Kakao API가 경로를 찾지 못한 구간에 부여하는 대체값 (kakao.py 와 동일)
# 이 값이 행렬에 들어온 구간은 실제 이동이 불가능하므로 누적 운전시간 계산에서 제외
_UNREACHABLE_SEC: int = 10_800_000


@dataclass
class RouteNode:
    type: str   # origin | waypoint | destination | rest_stop
    name: str
    lat: float
    lon: float
    min_rest_minutes: int | None = field(default=None)

    def to_dict(self) -> dict:
        d = {"type": self.type, "name": self.name, "lat": self.lat, "lon": self.lon}
        if self.min_rest_minutes is not None:
            d["min_rest_minutes"] = self.min_rest_minutes
        return d


def _haversine_sec(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
    avg_speed_kmh: float = 80.0,
) -> int:
    """두 좌표 간 Haversine 거리를 평균 속도 기반 소요 시간(초)으로 환산합니다."""
    R = 6_371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    dist_km = 2 * R * atan2(sqrt(a), sqrt(1 - a))
    return int(dist_km / avg_speed_kmh * 3600)


def _pick_best_rest(
    prev: RouteNode, nxt: RouteNode, candidates: list[dict]
) -> dict | None:
    """우회 비용(prev → 휴게소 → next) Haversine 최소 후보를 반환합니다.

    highway_rest 우선 탐색 — 후보가 없을 때만 drowsy_shelter로 폴백합니다.
    화물차가 졸음쉼터에 진입하지 못하는 경우를 대비한 우선순위 정책입니다.
    """
    def _best_from(pool: list[dict]) -> dict | None:
        best: dict | None = None
        best_cost = float("inf")
        for c in pool:
            if not c.get("is_active", True):
                continue
            cost = (
                _haversine_sec(prev.lat, prev.lon, c["latitude"], c["longitude"])
                + _haversine_sec(c["latitude"], c["longitude"], nxt.lat, nxt.lon)
            )
            if cost < best_cost:
                best_cost = cost
                best = c
        return best

    # 1순위: highway_rest + preferred(type 없음)
    priority = [c for c in candidates if c.get("type") != "drowsy_shelter"]
    result = _best_from(priority)
    if result:
        return result

    # 2순위(폴백): drowsy_shelter
    return _best_from(candidates)


async def insert_rest_stops(
    ordered_nodes: list[RouteNode],
    time_matrix: list[list[int]],
    rest_candidates: list[dict],
    initial_drive_sec: int = 0,
    is_emergency: bool = False,
    picker=None,
) -> list[RouteNode]:
    """
    TSP 정렬된 노드 목록에 법정 휴게소를 삽입합니다.

    흐름:
    1. 구간별 누적 운전 시간 계산
    2. REST_PLAN_SEC 도달 시 picker 또는 Haversine으로 최적 휴게소 삽입
    3. 긴급 예외(is_emergency=True) 시 MAX_DRIVE_SEC + EMERGENCY_EXTEND_SEC 까지
       허용하고, 삽입 시 EMERGENCY_REST_MIN(30분) 적용

    Args:
        ordered_nodes    : TSP 결과 순서 (출발지 포함 + 목적지 포함)
        time_matrix      : ordered_nodes 인덱스 기준 NxN 시간 행렬
        rest_candidates  : DB에서 조회한 active 휴게소 목록
        initial_drive_sec: 현재 누적 운전 시간 (replan 시 전달)
        is_emergency     : 교통정체·사고 등 불가피한 사유로 긴급 예외 적용 여부
                           (화물자동차 운수사업법 시행규칙 [별표3] 다항)
        picker           : async (prev, nxt, candidates) -> dict | None
                           None이면 Haversine 기반 _pick_best_rest 사용
    """
    # 긴급 예외 여부에 따라 임계값·휴식시간 결정
    plan_threshold = REST_PLAN_SEC
    rest_minutes = MIN_REST_MIN
    if is_emergency:
        # 정체·불가피 상황: 최대 연속 운전 3시간까지 허용, 휴식 30분 의무
        plan_threshold = MAX_DRIVE_SEC + EMERGENCY_EXTEND_SEC  # 10,800초
        rest_minutes = EMERGENCY_REST_MIN

    result: list[RouteNode] = []
    accumulated = initial_drive_sec

    for i in range(len(ordered_nodes) - 1):
        result.append(ordered_nodes[i])
        seg_time = time_matrix[i][i + 1]

        # API 미반환 구간(_UNREACHABLE_SEC)은 실제 이동이 없으므로 누적에서 제외
        if seg_time >= _UNREACHABLE_SEC:
            continue

        if accumulated + seg_time >= plan_threshold:
            if picker is not None:
                best = await picker(ordered_nodes[i], ordered_nodes[i + 1], rest_candidates)
            else:
                best = _pick_best_rest(ordered_nodes[i], ordered_nodes[i + 1], rest_candidates)
            if best:
                result.append(
                    RouteNode(
                        type="rest_stop",
                        name=best["name"],
                        lat=best["latitude"],
                        lon=best["longitude"],
                        min_rest_minutes=rest_minutes,
                    )
                )
                accumulated = 0  # 휴게소 삽입 성공 시에만 리셋
            else:
                accumulated += seg_time  # 후보 없으면 계속 누적
        else:
            accumulated += seg_time

    result.append(ordered_nodes[-1])
    return result
