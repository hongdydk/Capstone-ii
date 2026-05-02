from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.rest_stop import RestStop
from app.schemas.optimize import RouteNodeSchema
from app.services import graphhopper as gh_svc
from app.services.optimizer import solve_tsp
from app.services.rest_stop_inserter import (
    MAX_DRIVE_SEC,
    RouteNode,
    _angle_diff,
    _bearing,
    _direction_bearing,
    _haversine_sec,
    plan_rest_stops_from_polyline,
)

router = APIRouter()


class DemoNode(BaseModel):
    name: str
    lat: float
    lon: float
    # 경유지는 상·하차 작업 지점이므로 기본적으로 법정 휴식으로 인정하지 않음.
    # 법정 휴식 인정 기준: ① 시스템 삽입 휴게소, ② 기사가 명시적으로 can_rest=True 설정한 경유지(식당 등)
    # TODO(상용화): 경유지 실제 체류 시간(dwell_time_min)을 입력받아
    #   dwell_time_min >= MIN_REST_MIN(15분) 이면 can_rest=True 로 자동 판정하는 로직 추가
    can_rest: bool = False  # False=상하차 작업점(누적 운전시간 유지), True=실제 휴식점(리셋)

    # 도착 시간 제약 (출발 기준 경과 분) — None 이면 제약 없음
    # 예) 일간 출발 기준 09:00 창고 도착 제약 → time_window=[60, 180] (움직임 1시간 ~ 3시간 후)
    # 주의: OR-Tools 해가 없으면 제약을 완화해서라도 경로를 반환합니다
    time_window: tuple[int, int] | None = None  # (earliest_min, latest_min)

    # 상차→하차 순서 제약: 이 노드(하차지)에서 내릴 화물을 실은 상차지 인덱스 (0-based, nodes 리스트 기준)
    # 예) 출발지(0)에서 싣고 경유지2(2)에서 내린다 → nodes[2].pickup_from_idx=0
    #   → 동일 상차지(0)에서 여러 하차지(2,3,4)를 설정할 수 있어 다중 납품 지원
    pickup_from_idx: int | None = None  # 이 하차지의 상차지 인덱스


class DemoRouteRequest(BaseModel):
    profile: Literal["car", "truck"] = "truck"
    nodes: list[DemoNode]  # [출발지, *경유지..., 목적지]


class RestStopOption(BaseModel):
    name: str
    lat: float
    lon: float
    type: str


class RouteAlternative(BaseModel):
    label: str
    route: list[RouteNodeSchema]
    polyline: list[list[float]]
    total_distance_km: float
    estimated_duration_min: float
    rest_stops_count: int
    legs: list[float]
    rest_stop_options: list[list[RestStopOption]]


class DemoRouteResponse(BaseModel):
    alternatives: list[RouteAlternative]


class PolylineRequest(BaseModel):
    profile: Literal["car", "truck"] = "truck"
    nodes: list[DemoNode]


class PolylineResponse(BaseModel):
    polyline: list[list[float]]


async def _build_route_alternative(
    label: str,
    ordered_nodes: list[RouteNode],
    time_matrix: list[list[int]],
    dist_matrix: list[list[int]],
    rest_candidates: list[dict],
    hint_polyline: list[list[float]],
    route_time_sec: int,
    profile: str,
) -> RouteAlternative:
    """단일 경로 대안을 빌드합니다.

    흐름:
    1. hint_polyline 근처 휴게소 필터
    2. 폴리라인 위 이상적 시간 지점 → Haversine 방향 필터로 가장 가까운 휴게소 선택
       (GH HTTP 호출 없음 — IC 루프 방지, 속도 향상)
    3. 휴게소 포함 전체 노드로 GH 재탐색 → 실제 폴리라인·시간·거리 확보
    4. 구간 legs · rest_stop_options 계산 (맨 마지막)
    """
    # 1. 경로 근처 휴게소 필터
    nearby_rests = gh_svc.filter_rest_by_route(rest_candidates, hint_polyline)

    # 2. 폴리라인 기반 법정 휴게소 삽입
    #    경유지가 있으면 각 구간을 독립 평가 (경유지에서 누적 운전시간 리셋)
    segment_times = [time_matrix[i][i + 1] for i in range(len(ordered_nodes) - 1)]
    final_route = plan_rest_stops_from_polyline(
        ordered_nodes,
        hint_polyline,
        route_time_sec,
        nearby_rests,
        segment_times=segment_times,
    )

    # 3. 폴리라인 및 시간·거리 확정
    #    휴게소 삽입 여부와 무관하게 hint_polyline을 그대로 사용합니다.
    #    GH로 휴게소 좌표를 재탐색하면 IC 루프(고속도로 이탈)가 발생하므로
    #    표시용 폴리라인은 hint_polyline을 유지합니다.
    #    (Kakao 내비가 실제 진입로를 처리하므로 문제 없음)
    rest_count = sum(1 for n in final_route if n.type == "rest_stop")
    full_polyline = hint_polyline
    total_sec    = sum(time_matrix[i][i + 1] for i in range(len(ordered_nodes) - 1))
    total_dist_m = sum(dist_matrix[i][i + 1] for i in range(len(ordered_nodes) - 1))

    total_dist_km = round(total_dist_m / 1000, 1)

    # 4-a. 구간 소요시간 (legs)
    #      휴게소 노드는 time_matrix에 없으므로 Haversine 추정값 사용
    coord_to_idx = {
        (round(n.lat, 6), round(n.lon, 6)): i
        for i, n in enumerate(ordered_nodes)
    }
    legs: list[float] = []
    for i in range(len(final_route) - 1):
        a, b = final_route[i], final_route[i + 1]
        ia = coord_to_idx.get((round(a.lat, 6), round(a.lon, 6)))
        ib = coord_to_idx.get((round(b.lat, 6), round(b.lon, 6)))
        if ia is not None and ib is not None:
            t = time_matrix[ia][ib]
        else:
            t = _haversine_sec(a.lat, a.lon, b.lat, b.lon)
        legs.append(round(t / 60, 1))

    # 4-b. 휴게소별 대안 top-5
    rest_stop_options: list[list[RestStopOption]] = []
    for idx, node in enumerate(final_route):
        if node.type != "rest_stop":
            continue
        prev_n = next(
            (final_route[j] for j in range(idx - 1, -1, -1) if final_route[j].type != "rest_stop"),
            None,
        )
        next_n = next(
            (final_route[j] for j in range(idx + 1, len(final_route)) if final_route[j].type != "rest_stop"),
            None,
        )
        if not prev_n or not next_n:
            rest_stop_options.append([])
            continue

        travel_brg = _bearing(prev_n.lat, prev_n.lon, next_n.lat, next_n.lon)

        def _detour_key(c: dict, pn: RouteNode = prev_n, nn: RouteNode = next_n, brg: float = travel_brg) -> tuple:
            cost = (
                _haversine_sec(pn.lat, pn.lon, c["latitude"], c["longitude"])
                + _haversine_sec(c["latitude"], c["longitude"], nn.lat, nn.lon)
            )
            dbok = _direction_bearing(c.get("direction"))
            return (0 if (dbok is None or _angle_diff(brg, dbok) < 90) else 1, cost)

        top5 = sorted(
            [c for c in nearby_rests if c.get("is_active", True)],
            key=_detour_key,
        )[:5]
        rest_stop_options.append([
            RestStopOption(
                name=c["name"], lat=c["latitude"], lon=c["longitude"],
                type=c.get("type", "truck_rest"),
            )
            for c in top5
        ])

    return RouteAlternative(
        label=label,
        route=[RouteNodeSchema(**n.to_dict()) for n in final_route],
        polyline=full_polyline,
        total_distance_km=total_dist_km,
        estimated_duration_min=round(total_sec / 60, 1),
        rest_stops_count=rest_count,
        legs=legs,
        rest_stop_options=rest_stop_options,
    )


@router.post("/polyline", response_model=PolylineResponse)
async def demo_polyline(req: PolylineRequest):
    """노드 순서대로 폴리라인 계산 (휴게소 변경 시 경로 갱신용)."""
    geo_nodes = [{"lat": n.lat, "lon": n.lon} for n in req.nodes]
    polyline = await gh_svc.get_route_geometry(geo_nodes, profile=req.profile)
    return PolylineResponse(polyline=polyline)


class TruckRestItem(BaseModel):
    id: int
    name: str
    lat: float
    lon: float
    type: str
    direction: str | None = None


@router.get("/truck-rests", response_model=list[TruckRestItem])
async def get_truck_rests(db: AsyncSession = Depends(get_db)):
    """지도 표시용 화물차 전용 휴게소 목록 (truck_rest + highway_rest)."""
    result = await db.execute(
        select(RestStop).where(
            RestStop.is_active == True,  # noqa: E712
            RestStop.type.in_(["truck_rest", "highway_rest"]),
        )
    )
    return [
        TruckRestItem(
            id=r.id,
            name=r.name,
            lat=r.latitude,
            lon=r.longitude,
            type=r.type.value,
            direction=r.direction,
        )
        for r in result.scalars().all()
    ]


@router.post("/route", response_model=DemoRouteResponse)
async def demo_route(req: DemoRouteRequest, db: AsyncSession = Depends(get_db)):
    """DB trip 없이 노드 직접 입력 → GraphHopper + OR-Tools TSP + 법정 휴게소 삽입."""
    if len(req.nodes) < 2:
        raise HTTPException(status_code=400, detail="출발지와 목적지 최소 2개 필요")

    nodes = [{"name": n.name, "lat": n.lat, "lon": n.lon} for n in req.nodes]

    # 1. NxN 시간·거리 행렬
    time_matrix, dist_matrix = await gh_svc.build_time_matrix(nodes, profile=req.profile)

    # 2. TSP — time_window / pickup_from_idx 필드를 OR-Tools 형식으로 변환
    #    time_window: 분 단위를 초 단위로 변환 (* 60)
    #    pickup_from_idx: 하차 노드가 자신의 상차지를 가리킴 → (상차idx, 하차idx) 쌍 구성
    tsp_time_windows: list[tuple[int, int]] | None = None
    tsp_pickups: list[tuple[int, int]] | None = None

    if any(n.time_window for n in req.nodes):
        tsp_time_windows = [
            (tw[0] * 60, tw[1] * 60) if (tw := n.time_window) else (0, 10_000_000)
            for n in req.nodes
        ]

    pickup_pairs = [
        (n.pickup_from_idx, i)
        for i, n in enumerate(req.nodes)
        if n.pickup_from_idx is not None
    ]
    if pickup_pairs:
        tsp_pickups = pickup_pairs

    dest_idx = len(nodes) - 1
    tsp_order = solve_tsp(time_matrix, time_windows=tsp_time_windows, pickup_deliveries=tsp_pickups)
    if tsp_order and tsp_order[-1] == dest_idx:
        tsp_order = tsp_order[:-1]

    ordered_nodes: list[RouteNode] = [
        RouteNode(
            type="origin" if idx == 0 else "waypoint",
            name=nodes[idx]["name"],
            lat=nodes[idx]["lat"],
            lon=nodes[idx]["lon"],
            can_rest=req.nodes[idx].can_rest,
        )
        for idx in tsp_order
    ]
    ordered_nodes.append(RouteNode(
        type="destination",
        name=nodes[dest_idx]["name"],
        lat=nodes[dest_idx]["lat"],
        lon=nodes[dest_idx]["lon"],
        can_rest=req.nodes[dest_idx].can_rest,
    ))

    # 3. 행렬 재배열
    k = len(tsp_order)
    m = k + 1
    final_matrix = [[0] * m for _ in range(m)]
    final_dist   = [[0] * m for _ in range(m)]
    for i in range(k):
        for j in range(k):
            final_matrix[i][j] = time_matrix[tsp_order[i]][tsp_order[j]]
            final_dist[i][j]   = dist_matrix[tsp_order[i]][tsp_order[j]]
        final_matrix[i][k] = time_matrix[tsp_order[i]][dest_idx]
        final_dist[i][k]   = dist_matrix[tsp_order[i]][dest_idx]
    for j in range(k):
        final_matrix[k][j] = time_matrix[dest_idx][tsp_order[j]]
        final_dist[k][j]   = dist_matrix[dest_idx][tsp_order[j]]

    # 4. 전체 휴게소 후보 조회
    rest_result = await db.execute(
        select(RestStop).where(
            RestStop.is_active == True,  # noqa: E712
            RestStop.type != "depot",
        )
    )
    rest_candidates = [
        {
            "name": r.name,
            "latitude": r.latitude,
            "longitude": r.longitude,
            "is_active": r.is_active,
            "direction": r.direction,
            "type": r.type.value,
        }
        for r in rest_result.scalars().all()
    ]

    # 5. 대안 경로 폴리라인 (2노드: 최대 3개, N노드: 1개)
    geo_nodes_base = [{"lat": n.lat, "lon": n.lon} for n in ordered_nodes]
    alt_paths = await gh_svc.get_route_alternatives(geo_nodes_base, profile=req.profile)

    # 6. 각 대안별 빌드
    alternatives: list[RouteAlternative] = []
    for alt_idx, alt_path in enumerate(alt_paths):
        # 2노드 대안: 해당 경로의 실제 시간/거리로 행렬 오버라이드
        if len(ordered_nodes) == 2 and alt_path["time_sec"] > 0:
            t, d = alt_path["time_sec"], alt_path["dist_m"]
            alt_matrix = [[0, t], [t, 0]]
            alt_dist_m = [[0, d], [d, 0]]
        else:
            alt_matrix = final_matrix
            alt_dist_m = final_dist

        alt = await _build_route_alternative(
            label=f"경로 {alt_idx + 1}",
            ordered_nodes=ordered_nodes,
            time_matrix=alt_matrix,
            dist_matrix=alt_dist_m,
            rest_candidates=rest_candidates,
            hint_polyline=alt_path["polyline"],
            route_time_sec=alt_path["time_sec"],
            profile=req.profile,
        )
        alternatives.append(alt)

    return DemoRouteResponse(alternatives=alternatives)
