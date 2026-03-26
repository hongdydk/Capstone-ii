"""OR-Tools 기반 경로 최적화 서비스

알고리즘 요약
─────────────────────────────────────────────────────────────────────────────
1. TMAP API(실패 시 Haversine 추정)로 모든 노드 쌍의 소요 시간 행렬 구성.
2. OR-Tools TSP 솔버로 필수 노드(출발 → 경유지 → 도착)의 최적 방문 순서 결정.
   - 출발지(start)와 도착지(end)는 서로 다른 노드로 취급합니다.
   - `RoutingIndexManager(n, 1, start_idx, end_idx)` 사용.
3. 정렬된 경로 위에서 연속 운전 누적 시간이 MAX_DRIVE_SEC 이상이 되기 전에
   경유 직전 지점에서 가장 가까운 휴게소를 삽입합니다.
4. 최종 노드 목록으로 총 거리·소요 시간과 함께 반환합니다.
─────────────────────────────────────────────────────────────────────────────
법정 규정 (화물자동차 운수사업법 시행규칙):
  • 연속 운전 2시간(7200초) 후 15분 이상 휴식 필수
"""

import asyncio
import logging
import math
from typing import Any

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.schemas.optimize import RouteNode
from app.services.tmap_service import get_route

logger = logging.getLogger(__name__)

MAX_DRIVE_SEC  = 120 * 60   # 법정 최대 연속 운전: 2시간 = 7200초
REST_PLAN_SEC  = 100 * 60   # 휴게 계획 임계값: 1시간 40분 = 6000초
                             # (법정 한도보다 20분 앞서 삽입 → 여유 확보)
MIN_REST_SEC   = 15 * 60    # 법정 최소 휴식: 15분 = 900초
AVG_SPEED_MPS  = 80_000 / 3600  # Haversine 추정 기준 속도: 80 km/h


# ── 유틸 ─────────────────────────────────────────────────────────────────────

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 WGS84 좌표 사이의 거리를 미터 단위로 반환합니다."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def haversine_sec(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Haversine 거리로 추정한 이동 시간(초)을 반환합니다 (평균 80 km/h 기준)."""
    return max(1, int(haversine_m(lat1, lon1, lat2, lon2) / AVG_SPEED_MPS))


def _detour_m(a: dict, r: dict, b: dict) -> float:
    """a → r → b 경로의 우회 비용(미터)을 반환합니다.

    직선 a→b 대비 r을 경유할 때 추가되는 거리입니다.
    휴게소 삽입 위치 비교에 사용되며, 값이 작을수록 경로 효율이 좋습니다.
    """
    return (
        haversine_m(a["lat"], a["lon"], r["lat"], r["lon"])
        + haversine_m(r["lat"], r["lon"], b["lat"], b["lon"])
    )


_SEOUL_LAT, _SEOUL_LON = 37.5665, 126.9780  # 서울 기준 좌표
_DIR_THRESHOLD_M = 30_000                    # 방향 판정 최소 거리 차이 (30 km)


def _vehicle_direction(origin: dict, destination: dict) -> str | None:
    """origin → destination 이동 방향을 서울 기준 거리 차이로 판정합니다.

    Returns:
        "상행": 서울을 향해 접근 (서울과의 거리가 줄어듦)
        "하행": 서울에서 멀어짐
        None  : 거리 차이가 threshold 미만 → 방향 불분명 (수도권 단거리 등)
    """
    d_origin = haversine_m(origin["lat"], origin["lon"], _SEOUL_LAT, _SEOUL_LON)
    d_dest   = haversine_m(destination["lat"], destination["lon"], _SEOUL_LAT, _SEOUL_LON)
    diff = d_origin - d_dest  # 양수 = 서울에 가까워짐 = 상행
    if abs(diff) < _DIR_THRESHOLD_M:
        return None
    return "상행" if diff > 0 else "하행"


# ── 시간 행렬 구성 ─────────────────────────────────────────────────────────────

async def build_time_matrix(
    nodes: list[dict],
    vehicle_height: float | None = None,
    vehicle_weight: float | None = None,
    vehicle_length: float | None = None,
    vehicle_width: float | None = None,
    departure_time: str | None = None,
) -> list[list[int]]:
    """TMAP 화물차 경로 API로 모든 노드 쌍의 소요 시간(초) 행렬을 비동기로 구성합니다.

    차량 제원(높이·중량·길이·폭)을 전달하면 통행 제한 도로를 자동 우회합니다.
    departure_time(ISO-8601)을 전달하면 타임머신 예측 교통 API를 사용합니다.
    API 호출 실패 시 Haversine 추정값으로 fallback 합니다.
    동시 요청 수는 Semaphore 4개로 제한합니다 (TMAP 레이트 리밋 대응).
    """
    n = len(nodes)
    matrix: list[list[int]] = [[0] * n for _ in range(n)]
    sem = asyncio.Semaphore(4)

    async def _fetch(i: int, j: int) -> None:
        if i == j:
            return
        async with sem:
            try:
                result = await get_route(
                    nodes[i]["lat"], nodes[i]["lon"],
                    nodes[j]["lat"], nodes[j]["lon"],
                    vehicle_height=vehicle_height,
                    vehicle_weight=vehicle_weight,
                    vehicle_length=vehicle_length,
                    vehicle_width=vehicle_width,
                    departure_time=departure_time,
                )
                matrix[i][j] = max(1, int(result["duration_min"] * 60))
            except Exception:
                matrix[i][j] = haversine_sec(
                    nodes[i]["lat"], nodes[i]["lon"],
                    nodes[j]["lat"], nodes[j]["lon"],
                )

    await asyncio.gather(*[_fetch(i, j) for i in range(n) for j in range(n) if i != j])
    return matrix


# ── OR-Tools TSP 솔버 ─────────────────────────────────────────────────────────

def solve_tsp(time_matrix: list[list[int]], start: int = 0, end: int = -1) -> list[int]:
    """OR-Tools로 TSP를 풀고 방문 순서(노드 인덱스 목록)를 반환합니다.

    Args:
        time_matrix: n×n 소요 시간 행렬 (초).
        start: 출발 노드 인덱스 (기본 0).
        end: 도착 노드 인덱스 (기본 마지막 노드).

    Returns:
        start~end 까지의 방문 순서 인덱스 목록 (start, ..., end 포함).

    Notes:
        OR-Tools가 해를 찾지 못하면 입력 순서(0, 1, ..., n-1)를 그대로 반환합니다.
    """
    n = len(time_matrix)
    if end < 0:
        end = n - 1

    # 출발지와 도착지가 다른 오픈 TSP
    manager = pywrapcp.RoutingIndexManager(n, 1, [start], [end])
    routing = pywrapcp.RoutingModel(manager)

    def _transit(from_idx: int, to_idx: int) -> int:
        return time_matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]

    transit_cb = routing.RegisterTransitCallback(_transit)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb)

    # 최소 이동 시간 기반 탐색
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = 5

    solution = routing.SolveWithParameters(params)
    if solution is None:
        logger.warning("OR-Tools: 해 없음 — 입력 순서 그대로 반환 (nodes=%d)", n)
        return list(range(n))

    route: list[int] = []
    idx = routing.Start(0)
    while not routing.IsEnd(idx):
        route.append(manager.IndexToNode(idx))
        idx = solution.Value(routing.NextVar(idx))
    route.append(manager.IndexToNode(idx))  # 도착 노드 포함
    return route


# ── 법정 휴게 삽입 ────────────────────────────────────────────────────────────

def insert_rest_stops(
    ordered_nodes: list[dict],
    time_matrix: list[list[int]],
    original_indices: list[int],
    rest_stops: list[dict],
    initial_drive_sec: int = 0,
) -> list[dict]:
    """최적 순서가 결정된 노드 목록에 법정 휴게 노드를 삽입합니다.

    단순히 임계값에 도달하면 삽입하는 대신, **우회 비용 최소화**를 통해
    가장 효율적인 동선을 유지합니다.

    알고리즘:
      1. 누적 운전시간 + 다음 구간 >= REST_PLAN_SEC(1h40m) 도달 시 삽입 후보.
      2. 법정 2시간 한도를 아직 넘지 않으면 1단계 앞을 비교:
         - 지금 삽입 시 최소 우회 비용 vs 다음 구간에서 삽입 시 최소 우회 비용
         - 다음 구간이 더 효율적(우회 적음)이고 여전히 법적으로 허용되면 1구간 미룸.
      3. 법정 2시간 초과가 불가피하면 즉시 삽입 (강제).
      4. 삽입 위치 결정 후 prev→r→curr 합계가 최소인 휴게소를 선택.

    Args:
        ordered_nodes:    TSP 솔버가 정렬한 노드 dict 목록.
        time_matrix:      원본 노드들의 n×n 초 단위 시간 행렬.
        original_indices: ordered_nodes[i]가 time_matrix에서 갖는 인덱스.
        rest_stops:       후보 휴게소 목록 [{"lat", "lon", "name"}, ...].
        initial_drive_sec: 이미 누적된 연속 운전 시간(초).
                           운전자가 운행 중 재계산 요청 시 0 이 아닌 값 전달.

    Returns:
        휴게 노드가 삽입된 새 노드 목록.
    """
    if not rest_stops:
        return list(ordered_nodes)

    result: list[dict] = []
    cumul_drive_sec = initial_drive_sec   # 누적 운전시간 이어받기
    n = len(ordered_nodes)

    for i, node in enumerate(ordered_nodes):
        if i > 0:
            prev = ordered_nodes[i - 1]
            seg_sec = time_matrix[original_indices[i - 1]][original_indices[i]]
            after_seg = cumul_drive_sec + seg_sec

            if after_seg >= REST_PLAN_SEC:
                insert_here = True

                # ── 1단계 앞 비교 ──────────────────────────────────────────
                # 법정 2시간을 아직 넘지 않고, 다음 구간이 존재할 때만 비교.
                # 다음 구간까지 포함해도 법정 한도 안이면 우회 비용이 더 작은
                # 쪽(지금 삽입 vs 다음 구간 삽입)을 선택한다.
                if after_seg < MAX_DRIVE_SEC and i + 1 < n:
                    next_seg_sec = time_matrix[original_indices[i]][original_indices[i + 1]]
                    # 다음 구간까지 가도 법정 한도 이내인 경우에만 defer 고려
                    if after_seg + next_seg_sec < MAX_DRIVE_SEC:
                        next_node = ordered_nodes[i + 1]
                        # 현재 위치(gap i-1→i)에서 삽입 시 최소 우회 비용
                        best_now  = min(_detour_m(prev, r, node)     for r in rest_stops)
                        # 다음 위치(gap i→i+1)에서 삽입 시 최소 우회 비용
                        best_next = min(_detour_m(node, r, next_node) for r in rest_stops)
                        if best_next < best_now:
                            insert_here = False   # 다음 구간이 더 효율적 → 미룸

                if insert_here:
                    # ── 우회 비용 최소 휴게소 선택 (prev→r→curr 합계 기준) ──
                    best_rest = min(
                        rest_stops,
                        key=lambda r: _detour_m(prev, r, node),
                    )
                    result.append(
                        {
                            **best_rest,
                            "type": "rest_stop",
                            "min_rest_minutes": MIN_REST_SEC // 60,
                        }
                    )
                    cumul_drive_sec = 0   # 휴식 완료 → 리셋

            cumul_drive_sec += seg_sec

        result.append(node)

    return result


# ── 퍼블릭 진입점 ─────────────────────────────────────────────────────────────

async def optimize_route(
    origin: dict[str, Any],
    destination: dict[str, Any],
    waypoints: list[dict[str, Any]],
    rest_stops: list[dict[str, Any]],
    vehicle_height: float | None = None,
    vehicle_weight: float | None = None,
    vehicle_length: float | None = None,
    vehicle_width: float | None = None,
    initial_drive_sec: int = 0,
    extra_stops: list[dict[str, Any]] | None = None,
    departure_time: str | None = None,
) -> tuple[list[RouteNode], float, float]:
    """경로 최적화 메인 함수.

    Args:
        origin:            출발지 {"lat", "lon", "name"}.
        destination:       도착지 {"lat", "lon", "name"}.
        waypoints:         경유지 목록 (순서 최적화 대상).
        rest_stops:        휴게소 후보 목록 (삽입 한정, VRP 노드 아님).
        vehicle_height:    차량 높이 (m).
        vehicle_weight:    차량 총 중량 (kg).
        vehicle_length:    차량 길이 (cm).
        vehicle_width:     차량 폭 (cm).
        initial_drive_sec: 이미 누적된 연속 운전 시간(초). 운행 중 재계산 시 사용.
        extra_stops:       운전자/관리자 추가 지점 목록.
                           각 항목은 {"name", "lat", "lon", "stop_type"} 형태.
                           stop_type="waypoint"     → TSP 순서 최적화에 포함.
                           stop_type="destination"  → 새 최종 목적지 지정.
                                                       원래 destination 은 waypoints 로 편입.
                                                       여러 개면 마지막이 최종, 나머지는 waypoints.
                           stop_type="rest_preferred" → 휴게소 후보 목록 맨 앞에 추가.
        departure_time:    출발 예정 시각 (ISO-8601). trip.departure_time 에서 전달됨.
                           값이 있으면 타임머신 예측 교통 API를 사용합니다.

    Returns:
        (route_nodes, total_distance_km, estimated_duration_min)
    """
    extra_stops = extra_stops or []

    # ── extra_stops 분류 ──────────────────────────────────────────────────────
    # stop_type="waypoint"     → 기존 waypoints 에 병합 (TSP 최적화)
    # stop_type="destination"  → 새 최종 목적지 지정.
    #                            원래 destination 은 waypoints 로 편입.
    #                            여러 개일 경우 마지막이 최종, 나머지는 waypoints.
    # stop_type="rest_preferred" → 우선 선호 후보로 rest_stops 맨 앞에 삽입
    extra_waypoints  = [s for s in extra_stops if s.get("stop_type") == "waypoint"]
    extra_dests      = [s for s in extra_stops if s.get("stop_type") == "destination"]
    preferred_rest   = [s for s in extra_stops if s.get("stop_type") == "rest_preferred"]

    # ── 실제 최종 목적지 결정 ──────────────────────────────────────────────────
    if extra_dests:
        # 마지막 extra_dest 가 새 최종 목적지
        new_dest_raw = extra_dests[-1]
        final_destination = {
            "name": new_dest_raw["name"],
            "lat":  new_dest_raw["lat"],
            "lon":  new_dest_raw["lon"],
        }
        # 원래 destination + 중간 extra_dests → waypoints 편입 (TSP 최적화)
        demoted = [
            {"name": s["name"], "lat": s["lat"], "lon": s["lon"]}
            for s in extra_dests[:-1]
        ] + [{"name": destination["name"], "lat": destination["lat"], "lon": destination["lon"]}]
    else:
        final_destination = destination
        demoted = []

    merged_waypoints = (
        list(waypoints)
        + [{"name": s["name"], "lat": s["lat"], "lon": s["lon"]} for s in extra_waypoints]
        + demoted
    )
    # 선호 휴게소를 앞에 배치 → 우회 비용이 비슷할 때 우선 선택됨
    merged_rest_stops = [
        {"name": s["name"], "lat": s["lat"], "lon": s["lon"]}
        for s in preferred_rest
    ] + list(rest_stops)

    # ── 방향 필터: 이동 방향이 명확하면 반대 방향 쉼터 제외 ─────────────────
    # direction=None(미분류/양방향)은 항상 포함, preferred_rest 는 이미 direction 없음
    vehicle_dir = _vehicle_direction(origin, final_destination)
    if vehicle_dir is not None:
        merged_rest_stops = [
            r for r in merged_rest_stops
            if r.get("direction") is None or r.get("direction") == vehicle_dir
        ]
        logger.debug("방향 필터: %s → 쉼터 후보 %d개", vehicle_dir, len(merged_rest_stops))

    # ── 1. 필수 노드 목록 구성 ────────────────────────────────────────────────
    # 인덱스 0 = 출발, 1..m = 경유, m+1 = 도착
    required: list[dict] = [
        {**origin, "type": "origin"},
        *[{**w, "type": "waypoint"} for w in merged_waypoints],
        {**final_destination, "type": "destination"},
    ]
    n = len(required)

    # ── 2. 시간 행렬 구성 ─────────────────────────────────────────────────────
    matrix = await build_time_matrix(
        required,
        vehicle_height=vehicle_height,
        vehicle_weight=vehicle_weight,
        vehicle_length=vehicle_length,
        vehicle_width=vehicle_width,
        departure_time=departure_time,
    )

    # ── 3. TSP 최적화 (경유지 순서 결정) ─────────────────────────────────────
    if n <= 2:
        # 경유지 없음 — 직통
        tsp_order = list(range(n))
    else:
        tsp_order = solve_tsp(matrix, start=0, end=n - 1)

    ordered_nodes = [required[i] for i in tsp_order]

    # ── 4. 법정 휴게 노드 삽입 ────────────────────────────────────────────────
    final_nodes = insert_rest_stops(
        ordered_nodes, matrix, tsp_order, merged_rest_stops,
        initial_drive_sec=initial_drive_sec,
    )

    # ── 5. 최종 거리·시간 합산 ────────────────────────────────────────────────
    total_time_sec = 0
    total_dist_km = 0.0
    cumul_min = 0.0

    for i in range(1, len(final_nodes)):
        prev, curr = final_nodes[i - 1], final_nodes[i]

        if curr.get("type") == "rest_stop":
            # 휴게 노드 자체는 이동 없이 MIN_REST_SEC 대기
            total_time_sec += MIN_REST_SEC
            cumul_min += MIN_REST_SEC / 60
            curr["_estimated_arrival_min"] = round(cumul_min, 1)
            continue

        if prev.get("type") == "rest_stop":
            # 휴게소 → 다음 노드 구간: Haversine 추정 (TMAP 재호출 최소화)
            secs = haversine_sec(prev["lat"], prev["lon"], curr["lat"], curr["lon"])
            dist_km = haversine_m(prev["lat"], prev["lon"], curr["lat"], curr["lon"]) / 1000
        else:
            try:
                r = await get_route(
                    prev["lat"], prev["lon"], curr["lat"], curr["lon"],
                    vehicle_height=vehicle_height,
                    vehicle_weight=vehicle_weight,
                    vehicle_length=vehicle_length,
                    vehicle_width=vehicle_width,
                )
                secs = int(r["duration_min"] * 60)
                dist_km = r["distance_km"]
            except Exception:
                secs = haversine_sec(prev["lat"], prev["lon"], curr["lat"], curr["lon"])
                dist_km = haversine_m(prev["lat"], prev["lon"], curr["lat"], curr["lon"]) / 1000

        total_time_sec += secs
        total_dist_km += dist_km
        cumul_min += secs / 60
        curr["_estimated_arrival_min"] = round(cumul_min, 1)

    # ── 6. RouteNode 목록 생성 ────────────────────────────────────────────────
    route_nodes: list[RouteNode] = []
    for node in final_nodes:
        route_nodes.append(
            RouteNode(
                type=node.get("type", "waypoint"),
                name=node.get("name", ""),
                lat=node["lat"],
                lon=node["lon"],
                min_rest_minutes=node.get("min_rest_minutes"),
                estimated_arrival_min=node.get("_estimated_arrival_min"),
            )
        )

    return route_nodes, round(total_dist_km, 2), round(total_time_sec / 60, 1)
