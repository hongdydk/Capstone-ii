from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.trip import Trip, TripStatus
from app.models.vehicle import Vehicle
from app.models.rest_stop import RestStop
from app.schemas.optimize import (
    OptimizeRequest,
    OptimizeResponse,
    ReplanRequest,
    RouteNodeSchema,
    DispatchRequest,
    DispatchResponse,
    DispatchVehicleRoute,
)
from app.services import graphhopper as gh_svc
from app.services.optimizer import solve_tsp, validate_tsp_constraints, solve_vrptw
from app.services.rest_stop_inserter import RouteNode, insert_rest_stops, plan_rest_stops_from_polyline

router = APIRouter()


def _resolve_vehicle_params(trip: Trip, req: OptimizeRequest) -> dict:
    """기사 입력값 우선, 없으면 trip 등록값 사용."""
    return {
        "height_m": req.vehicle_height_m or trip.vehicle_height_m,
        "weight_kg": req.vehicle_weight_kg or trip.vehicle_weight_kg,
        "length_cm": req.vehicle_length_cm or trip.vehicle_length_cm,
        "width_cm": req.vehicle_width_cm or trip.vehicle_width_cm,
    }


@router.post("/", response_model=OptimizeResponse)
async def optimize(req: OptimizeRequest, db: AsyncSession = Depends(get_db)):
    """단일 차량 경로 최적화. trip_id로 경유지·목적지를 로드하고 최적 동선을 계산합니다."""
    trip = await db.get(Trip, req.trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    # ------------------------------------------------------------------
    # 1. 노드 구성 (출발지 + 경유지 + extra_stops + 목적지)
    # ------------------------------------------------------------------
    waypoints_raw: list[dict] = list(trip.waypoints or [])

    # cargo 제약 수집 (cargo_id → 노드 인덱스 목록)
    _cargo_pickups: dict[str, list[int]] = {}
    _cargo_deliveries: dict[str, list[int]] = {}

    # DB trip.waypoints의 cargo_id/cargo_role 수집
    for rel_i, wp in enumerate(waypoints_raw):
        node_idx = rel_i + 1  # origin이 index 0이므로 +1
        cid = wp.get("cargo_id")
        role = wp.get("cargo_role")
        if cid and role == "pickup":
            _cargo_pickups.setdefault(cid, []).append(node_idx)
        elif cid and role == "delivery":
            _cargo_deliveries.setdefault(cid, []).append(node_idx)

    extra_stops = req.extra_stops or []
    new_dest = None
    preferred_rest: list[dict] = []

    for es in extra_stops:
        if es.stop_type in ("waypoint", "pickup", "delivery"):
            wp: dict = {"name": es.name, "lat": es.lat, "lon": es.lon}
            if es.earliest_sec is not None:
                wp["earliest_sec"] = es.earliest_sec
            if es.latest_sec is not None:
                wp["latest_sec"] = es.latest_sec
            # cargo 제약 추적 — append 전에 현재 인덱스 계산
            if es.cargo_id:
                node_idx = len(waypoints_raw) + 1  # origin offset
                if es.stop_type == "pickup":
                    _cargo_pickups.setdefault(es.cargo_id, []).append(node_idx)
                elif es.stop_type == "delivery":
                    _cargo_deliveries.setdefault(es.cargo_id, []).append(node_idx)
            waypoints_raw.append(wp)
        elif es.stop_type == "destination":
            # 기존 목적지를 경유지로 후퇴
            waypoints_raw.append(
                {"name": trip.dest_name, "lat": trip.dest_lat, "lon": trip.dest_lon}
            )
            new_dest = es
        elif es.stop_type == "rest_preferred":
            preferred_rest.append(
                {"name": es.name, "latitude": es.lat, "longitude": es.lon, "is_active": True}
            )

    dest_name = new_dest.name if new_dest else trip.dest_name
    dest_lat = new_dest.lat if new_dest else trip.dest_lat
    dest_lon = new_dest.lon if new_dest else trip.dest_lon

    # 목적지가 없으면 마지막 하차(delivery) 경유지를 종료점으로 자동 선택
    # 하차 경유지도 없으면 마지막 경유지를 종료점으로 사용
    if dest_name is None:
        delivery_wps = [
            wp for wp in waypoints_raw
            if wp.get("cargo_role") == "delivery"
        ]
        endpoint_wp = delivery_wps[-1] if delivery_wps else (waypoints_raw[-1] if waypoints_raw else None)
        if endpoint_wp is None:
            raise HTTPException(status_code=400, detail="목적지 또는 경유지를 최소 1개 지정해 주세요.")
        waypoints_raw = [wp for wp in waypoints_raw if wp is not endpoint_wp]
        dest_name = endpoint_wp["name"]
        dest_lat  = endpoint_wp["lat"]
        dest_lon  = endpoint_wp["lon"]

    # 노드 순서: [출발지, ...경유지, 목적지]
    nodes: list[dict] = [
        {"name": req.origin_name, "lat": req.origin_lat, "lon": req.origin_lon}
    ]
    nodes += waypoints_raw
    nodes.append({"name": dest_name, "lat": dest_lat, "lon": dest_lon})

    # ------------------------------------------------------------------
    # 2. GraphHopper NxN 시간·거리 행렬 계산
    # ------------------------------------------------------------------
    time_matrix, dist_matrix = await gh_svc.build_time_matrix(nodes, profile="truck")

    # ------------------------------------------------------------------
    # 3. OR-Tools TSP 경유지 순서 최적화
    # ------------------------------------------------------------------
    # time_windows 구성: waypoints JSONB 또는 extra_stops의 earliest_sec/latest_sec 사용
    # 출발지/목적지는 제약 없음 (0 ~ 매우 큰 값)
    _INF = 10_000_000
    time_windows: list[tuple[int, int]] | None = None

    # waypoints_raw + extra_stops 에서 time window 수집
    tw_list: list[tuple[int, int]] = [(0, 0)]  # 출발지 고정 (경과 0초)
    has_any_tw = False
    for wp in waypoints_raw:
        e = wp.get("earliest_sec")
        l = wp.get("latest_sec")
        if e is not None or l is not None:
            has_any_tw = True
        tw_list.append((e or 0, l or _INF))
    tw_list.append((0, _INF))  # 목적지 제약 없음

    if has_any_tw:
        time_windows = tw_list

    # pickup_deliveries 구성: 같은 cargo_id의 pickup × delivery 전체 쌍 자동 생성
    # 1:N, N:1, N:M 모두 지원 — 중복 없이 모든 조합 등록
    pickup_deliveries: list[tuple[int, int]] | None = None
    pairs = [
        (pu_idx, del_idx)
        for cid in set(_cargo_pickups) & set(_cargo_deliveries)
        for pu_idx in _cargo_pickups[cid]
        for del_idx in _cargo_deliveries[cid]
    ]
    if pairs:
        pickup_deliveries = pairs

    # 제약 사전 검사 — 종류별 오류 메시지 반환
    node_names = [n["name"] for n in nodes]
    violation = validate_tsp_constraints(time_matrix, time_windows, pickup_deliveries, node_names)
    if violation:
        code, msg = violation
        raise HTTPException(status_code=code, detail=msg)

    tsp_order = solve_tsp(time_matrix, time_windows=time_windows, pickup_deliveries=pickup_deliveries)
    if tsp_order is None:
        raise HTTPException(
            status_code=422,
            detail="경로 계산 실패: 복합 제약 충돌로 가능한 경로가 없습니다. 시간창 범위나 경유지 순서를 조정해 주세요.",
        )

    ordered_nodes = [
        RouteNode(
            type="origin" if idx == 0 else (
                "destination" if idx == len(nodes) - 1 else "waypoint"
            ),
            name=nodes[idx]["name"],
            lat=nodes[idx]["lat"],
            lon=nodes[idx]["lon"],
        )
        for idx in tsp_order
    ]
    # 목적지 항상 마지막에
    dest_node = RouteNode(type="destination", name=dest_name, lat=dest_lat, lon=dest_lon)
    ordered_nodes.append(dest_node)

    # TSP 결과 기준 time/dist 행렬 재배열
    dest_idx = len(nodes) - 1  # 원본 노드 리스트에서 목적지 인덱스
    k = len(tsp_order)
    n_ordered = len(ordered_nodes)  # k + 1 (목적지 포함)

    final_matrix = [[0] * n_ordered for _ in range(n_ordered)]
    final_dist = [[0] * n_ordered for _ in range(n_ordered)]
    for i in range(k):
        for j in range(k):
            final_matrix[i][j] = time_matrix[tsp_order[i]][tsp_order[j]]
            final_dist[i][j] = dist_matrix[tsp_order[i]][tsp_order[j]]
        # 마지막 열: 각 경유지 → 목적지 시간/거리
        final_matrix[i][k] = time_matrix[tsp_order[i]][dest_idx]
        final_dist[i][k] = dist_matrix[tsp_order[i]][dest_idx]

    # ------------------------------------------------------------------
    # 4. 법정 휴게소 삽입
    # ------------------------------------------------------------------
    rest_result = await db.execute(
        select(RestStop).where(
            RestStop.is_active == True,  # noqa: E712
            RestStop.type != "depot",
        )
    )
    rest_stops_db = rest_result.scalars().all()
    rest_candidates = preferred_rest + [
        {
            "name": r.name,
            "latitude": r.latitude,
            "longitude": r.longitude,
            "is_active": r.is_active,
            "direction": r.direction,
            "type": r.type.value,
        }
        for r in rest_stops_db
    ]

    final_route = await insert_rest_stops(
        ordered_nodes,
        final_matrix,
        rest_candidates,
        initial_drive_sec=req.initial_drive_sec,
    )

    # ------------------------------------------------------------------
    # 5. 응답 계산 및 DB 저장
    # ------------------------------------------------------------------
    rest_count = sum(1 for n in final_route if n.type == "rest_stop")
    total_sec = sum(
        final_matrix[i][i + 1]
        for i in range(len(ordered_nodes) - 1)
    )
    total_distance_km = round(
        sum(final_dist[i][i + 1] for i in range(len(ordered_nodes) - 1)) / 1000, 1
    )

    route_dicts = [n.to_dict() for n in final_route]
    trip.optimized_route = {
        "route": route_dicts,
        "estimated_duration_min": round(total_sec / 60, 1),
        "rest_stops_count": rest_count,
    }
    trip.origin_name = req.origin_name
    trip.origin_lat = req.origin_lat
    trip.origin_lon = req.origin_lon
    trip.status = TripStatus.in_progress
    await db.commit()

    return OptimizeResponse(
        trip_id=trip.id,
        route=[RouteNodeSchema(**n.to_dict()) for n in final_route],
        total_distance_km=total_distance_km,
        estimated_duration_min=round(total_sec / 60, 1),
        rest_stops_count=rest_count,
    )


@router.post("/replan", response_model=OptimizeResponse)
async def replan(req: ReplanRequest, db: AsyncSession = Depends(get_db)):
    """운행 중 재경로 계산. 현재 위치와 잔여 경유지를 기반으로 재최적화합니다."""
    trip = await db.get(Trip, req.trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    nodes: list[dict] = [
        {"name": req.current_name, "lat": req.current_lat, "lon": req.current_lon}
    ]
    nodes += req.remaining_waypoints
    nodes.append({"name": req.dest_name, "lat": req.dest_lat, "lon": req.dest_lon})

    time_matrix, dist_matrix = await gh_svc.build_time_matrix(nodes, profile="truck")
    tsp_order = solve_tsp(time_matrix)

    ordered_nodes = [
        RouteNode(
            type="origin" if idx == 0 else (
                "destination" if idx == len(nodes) - 1 else "waypoint"
            ),
            name=nodes[idx]["name"],
            lat=nodes[idx]["lat"],
            lon=nodes[idx]["lon"],
        )
        for idx in tsp_order
    ]
    ordered_nodes.append(
        RouteNode(type="destination", name=req.dest_name, lat=req.dest_lat, lon=req.dest_lon)
    )

    rest_result = await db.execute(
        select(RestStop).where(
            RestStop.is_active == True,  # noqa: E712
            RestStop.type != "depot",
        )
    )
    rest_stops_db = [
        {"name": r.name, "latitude": r.latitude, "longitude": r.longitude, "is_active": True}
        for r in rest_result.scalars().all()
    ]

    dest_idx = len(nodes) - 1
    k = len(tsp_order)
    n = len(ordered_nodes)
    final_matrix = [[0] * n for _ in range(n)]
    final_dist = [[0] * n for _ in range(n)]
    for i in range(k):
        for j in range(k):
            final_matrix[i][j] = time_matrix[tsp_order[i]][tsp_order[j]]
            final_dist[i][j] = dist_matrix[tsp_order[i]][tsp_order[j]]
        final_matrix[i][k] = time_matrix[tsp_order[i]][dest_idx]
        final_dist[i][k] = dist_matrix[tsp_order[i]][dest_idx]

    final_route, _daily_limit = await insert_rest_stops(
        ordered_nodes, final_matrix, rest_stops_db,
        initial_drive_sec=req.current_drive_sec,
        is_emergency=req.is_emergency,
    )

    rest_count = sum(1 for nd in final_route if nd.type == "rest_stop")
    total_sec = sum(final_matrix[i][i + 1] for i in range(len(ordered_nodes) - 1))
    total_distance_km = round(
        sum(final_dist[i][i + 1] for i in range(len(ordered_nodes) - 1)) / 1000, 1
    )

    return OptimizeResponse(
        trip_id=req.trip_id,
        route=[RouteNodeSchema(**nd.to_dict()) for nd in final_route],
        total_distance_km=total_distance_km,
        estimated_duration_min=round(total_sec / 60, 1),
        rest_stops_count=rest_count,
    )


@router.post("/dispatch", response_model=DispatchResponse)
async def dispatch_multi(req: DispatchRequest, db: AsyncSession = Depends(get_db)):
    """다수 차량 VRPTW 자동 배차 최적화.

    - depot → 배송지 N곳 → depot 복귀
    - OR-Tools VRPTW: 시간창 + 적재 용량 제약 동시 적용
    - 차량별 법정 휴게소 자동 삽입
    - 배정 못한 노드는 unassigned_nodes 로 반환
    """
    if not req.vehicles:
        raise HTTPException(status_code=400, detail="차량을 1대 이상 지정해 주세요.")
    if not req.nodes:
        raise HTTPException(status_code=400, detail="배송 노드를 1개 이상 지정해 주세요.")

    # 1. 노드 구성: 인덱스 0 = depot, 1..N = 배송지
    all_geo = [{"name": req.depot_name, "lat": req.depot_lat, "lon": req.depot_lon}]
    all_geo += [{"name": n.name, "lat": n.lat, "lon": n.lon} for n in req.nodes]

    # 2. NxN 시간·거리 행렬
    time_matrix, dist_matrix = await gh_svc.build_time_matrix(all_geo, profile=req.profile)

    # 3. 시간창 구성 (depot = 제약 없음)
    _INF = sum(max(row) for row in time_matrix)
    time_windows: list[tuple[int, int]] = [(0, _INF)]  # depot
    for node in req.nodes:
        time_windows.append((node.earliest_sec, node.latest_sec if node.latest_sec else _INF))

    # 4. 용량 구성 (kg → 정수, 0.1 kg 정밀도)
    _UNIT = 10  # 1 kg = 10 단위
    has_capacity = any(v.max_load_kg > 0 for v in req.vehicles)
    vehicle_capacities: list[int] | None = None
    demands: list[int] | None = None
    if has_capacity:
        vehicle_capacities = [
            int(v.max_load_kg * _UNIT) if v.max_load_kg > 0 else 10_000_000
            for v in req.vehicles
        ]
        demands = [0] + [int(n.cargo_weight_kg * _UNIT) for n in req.nodes]

    # 5. VRPTW 최적화
    import math as _math
    _n_nodes = len(req.nodes)
    _n_veh   = len(req.vehicles)
    _max_per = max(1, _math.ceil(_n_nodes / _n_veh) + 1)
    result = solve_vrptw(
        time_matrix,
        num_vehicles=_n_veh,
        vehicle_capacities=vehicle_capacities,
        demands=demands,
        time_windows=time_windows,
        time_limit_seconds=req.time_limit_seconds,
        max_nodes_per_vehicle=_max_per,
    )
    if result is None:
        raise HTTPException(
            status_code=422,
            detail="VRPTW 계산 실패: 시간창·용량 제약을 동시에 만족하는 배차 조합이 없습니다.",
        )

    vehicle_routes_idx, unserved_idx = result

    # 6. 휴게소 후보 조회
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

    # 7. 차량별 결과 빌드
    routes_out: list[DispatchVehicleRoute] = []
    for vehicle, node_indices in zip(req.vehicles, vehicle_routes_idx):
        if not node_indices:
            continue  # 배정 노드 없는 차량은 제외

        # depot(origin) + 배정 노드(waypoint) + depot(destination) 구성
        ordered: list[RouteNode] = [
            RouteNode(type="origin", name=req.depot_name,
                      lat=req.depot_lat, lon=req.depot_lon, can_rest=False)
        ]
        for ni in node_indices:
            nd = req.nodes[ni - 1]  # ni는 1-based (0=depot)
            ordered.append(RouteNode(type="waypoint", name=nd.name,
                                     lat=nd.lat, lon=nd.lon, can_rest=False))
        ordered.append(
            RouteNode(type="destination", name=req.depot_name,
                      lat=req.depot_lat, lon=req.depot_lon, can_rest=False)
        )

        # 폴리라인·시간·거리 조회
        geo_nodes = [{"lat": n.lat, "lon": n.lon} for n in ordered]
        try:
            polyline, route_time_sec, route_dist_m = await gh_svc.get_route_with_stats(
                geo_nodes, profile=req.profile
            )
        except Exception:
            polyline = []
            all_idx = [0] + node_indices + [0]
            route_time_sec = sum(
                time_matrix[all_idx[i]][all_idx[i + 1]]
                for i in range(len(all_idx) - 1)
            )
            route_dist_m = 0

        # 구간 시간 (depot→n1, n1→n2, ..., nK→depot)
        all_idx = [0] + node_indices + [0]
        segment_times = [
            time_matrix[all_idx[i]][all_idx[i + 1]]
            for i in range(len(all_idx) - 1)
        ]

        # 법정 휴게소 삽입
        nearby = gh_svc.filter_rest_by_route(rest_candidates, polyline)
        final_route = plan_rest_stops_from_polyline(
            ordered, polyline, route_time_sec, nearby, segment_times=segment_times
        )

        total_load = round(sum(req.nodes[ni - 1].cargo_weight_kg for ni in node_indices), 1)
        rest_count = sum(1 for n in final_route if n.type == "rest_stop")

        routes_out.append(DispatchVehicleRoute(
            vehicle_name=vehicle.name,
            route=[RouteNodeSchema(**n.to_dict()) for n in final_route],
            polyline=polyline,
            total_distance_km=round(route_dist_m / 1000, 1),
            estimated_duration_min=round(route_time_sec / 60, 1),
            total_load_kg=total_load,
            rest_stops_count=rest_count,
        ))

    unassigned_names = [req.nodes[i - 1].name for i in unserved_idx]
    return DispatchResponse(routes=routes_out, unassigned_nodes=unassigned_names)
