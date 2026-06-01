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
    DispatchVehicleInput,
    DispatchNodeInput,
)
from app.services import graphhopper as gh_svc
from app.services.optimizer import (
    solve_tsp,
    validate_tsp_constraints,
    solve_vrptw,
    solve_vrptw_with_vehicle_end_policy,
)
from app.services.rest_stop_inserter import RouteNode, plan_rest_stops_from_polyline_async
from app.services.time_windows import (
    TimeWindowValidationError,
    apply_resolved_windows_to_dict,
    copy_time_fields_to_dict,
    resolve_reference_departure_at,
    resolve_time_window_bounds,
)


def _vehicle_has_start(vehicle: DispatchVehicleInput) -> bool:
    return vehicle.start_lat is not None and vehicle.start_lon is not None


def _resolve_dispatch_mode(req: DispatchRequest) -> str:
    """depot_centered | vehicle_starts — 차량 start가 있으면 분산 출발 우선."""
    has_depot = req.depot_lat is not None and req.depot_lon is not None
    any_start = any(_vehicle_has_start(v) for v in req.vehicles)
    all_starts = all(_vehicle_has_start(v) for v in req.vehicles)
    partial_start = any_start and not all_starts

    if partial_start:
        raise HTTPException(
            status_code=400,
            detail="분산 배차 시 모든 차량에 start_lat·start_lon을 지정해 주세요.",
        )

    if req.dispatch_mode == "depot_centered":
        if not has_depot:
            raise HTTPException(
                status_code=400,
                detail="depot_centered 모드에는 depot_lat·depot_lon이 필요합니다.",
            )
        if any_start:
            raise HTTPException(
                status_code=400,
                detail="depot_centered 모드에는 차량 start 좌표를 넣지 마세요.",
            )
        return "depot_centered"

    if req.dispatch_mode == "vehicle_starts":
        if not all_starts:
            raise HTTPException(
                status_code=400,
                detail="vehicle_starts 모드에는 모든 차량에 start_lat·start_lon이 필요합니다.",
            )
        return "vehicle_starts"

    if any_start:
        if not all_starts:
            raise HTTPException(
                status_code=400,
                detail="분산 배차 시 모든 차량에 start_lat·start_lon을 지정해 주세요.",
            )
        return "vehicle_starts"

    if has_depot:
        return "depot_centered"

    raise HTTPException(
        status_code=400,
        detail="중앙 차고지(depot_lat·depot_lon) 또는 모든 차량의 기사 현재 위치(start_lat·start_lon)가 필요합니다.",
    )


def _build_dispatch_time_windows(
    reference,
    nodes: list[DispatchNodeInput],
    *,
    prefix_unrestricted: int = 0,
    suffix_unrestricted: int = 0,
    inf: int,
) -> list[tuple[int, int]]:
    time_windows: list[tuple[int, int]] = [(0, inf)] * prefix_unrestricted
    for node in nodes:
        try:
            e, l = resolve_time_window_bounds(
                reference,
                earliest_at=node.earliest_at,
                latest_at=node.latest_at,
                tw_open=node.tw_open,
                tw_close=node.tw_close,
                service_date=node.service_date,
                earliest_sec=node.earliest_sec,
                latest_sec=node.latest_sec,
                label=node.name,
            )
        except TimeWindowValidationError as exc:
            raise _http_422_from_time_window(exc) from exc
        time_windows.append((e if e is not None else 0, l if l is not None else inf))
    time_windows.extend([(0, inf)] * suffix_unrestricted)
    return time_windows


def _http_422_from_time_window(exc: TimeWindowValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _normalize_waypoints_time_windows(
    waypoints: list[dict],
    reference,
    *,
    extra_labels: dict[int, str] | None = None,
) -> None:
    """경유지 dict 목록의 캘린더 시간창을 earliest_sec/latest_sec로 일괄 변환."""
    for i, wp in enumerate(waypoints):
        label = (extra_labels or {}).get(i) or wp.get("name", f"경유지 {i + 1}")
        apply_resolved_windows_to_dict(wp, reference, label=label)

router = APIRouter()


def _build_cargo_pickup_deliveries(
    waypoints: list[dict],
    *,
    start_index: int = 1,
) -> list[tuple[int, int]]:
    """경유지 dict 목록에서 cargo_id 기준 pickup→delivery OR-Tools 쌍을 생성합니다.

    start_index: 출발지가 0일 때 첫 경유지의 노드 인덱스 (기본 1).
    cargo_role 없으면 stop_type pickup/delivery 로 폴백합니다.
    """
    pickups: dict[str, list[int]] = {}
    deliveries: dict[str, list[int]] = {}
    for i, wp in enumerate(waypoints):
        cid = wp.get("cargo_id")
        if not cid:
            continue
        role = wp.get("cargo_role")
        if role not in ("pickup", "delivery"):
            st = wp.get("stop_type")
            role = st if st in ("pickup", "delivery") else None
        if role == "pickup":
            pickups.setdefault(cid, []).append(start_index + i)
        elif role == "delivery":
            deliveries.setdefault(cid, []).append(start_index + i)
    return [
        (pu, dl)
        for cid in set(pickups) & set(deliveries)
        for pu in pickups[cid]
        for dl in deliveries[cid]
    ]


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

    try:
        reference = resolve_reference_departure_at(
            req.reference_departure_at,
            trip_departure_time=trip.departure_time,
        )
    except TimeWindowValidationError as exc:
        raise _http_422_from_time_window(exc) from exc

    # ------------------------------------------------------------------
    # 1. 노드 구성 (출발지 + 경유지 + extra_stops + 목적지)
    # ------------------------------------------------------------------
    waypoints_raw: list[dict] = list(trip.waypoints or [])

    extra_stops = req.extra_stops or []
    new_dest = None
    preferred_rest: list[dict] = []

    for es in extra_stops:
        if es.stop_type in ("waypoint", "pickup", "delivery"):
            wp: dict = {"name": es.name, "lat": es.lat, "lon": es.lon}
            copy_time_fields_to_dict(es, wp)
            if es.cargo_id:
                wp["cargo_id"] = es.cargo_id
            if es.stop_type in ("pickup", "delivery"):
                wp["cargo_role"] = es.stop_type
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

    try:
        _normalize_waypoints_time_windows(waypoints_raw, reference)
    except TimeWindowValidationError as exc:
        raise _http_422_from_time_window(exc) from exc

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

    # pickup_deliveries: 같은 cargo_id 내 pickup × delivery (1:N, N:1, N:M)
    pairs = _build_cargo_pickup_deliveries(waypoints_raw, start_index=1)
    pickup_deliveries: list[tuple[int, int]] | None = pairs or None

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

    # 폴리라인 기반 휴게소 삽입 (도로 형상 반영 + 반대차선 방지)
    geo_nodes_opt = [{"lat": n.lat, "lon": n.lon} for n in ordered_nodes]
    try:
        polyline_opt, route_time_sec_opt, _ = await gh_svc.get_route_with_stats(
            geo_nodes_opt, profile="truck"
        )
    except Exception:
        polyline_opt = []
        route_time_sec_opt = sum(
            final_matrix[i][i + 1] for i in range(len(ordered_nodes) - 1)
        )
    nearby_opt = gh_svc.filter_rest_by_route(rest_candidates, polyline_opt) if polyline_opt else rest_candidates
    segment_times_opt = [final_matrix[i][i + 1] for i in range(len(ordered_nodes) - 1)]
    final_route = await plan_rest_stops_from_polyline_async(
        ordered_nodes,
        polyline_opt,
        route_time_sec_opt,
        nearby_opt,
        initial_drive_sec=req.initial_drive_sec,
        segment_times=segment_times_opt,
        profile="truck",
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

    try:
        reference = resolve_reference_departure_at(
            req.reference_departure_at,
            trip_departure_time=None,
        )
    except TimeWindowValidationError as exc:
        raise _http_422_from_time_window(exc) from exc

    # dest가 None이면 마지막 remaining_waypoints를 목적지로 승격
    remaining_wps = list(req.remaining_waypoints)
    dest_name = req.dest_name
    dest_lat  = req.dest_lat
    dest_lon  = req.dest_lon
    if dest_name is None or dest_lat is None or dest_lon is None:
        if not remaining_wps:
            raise HTTPException(
                status_code=400,
                detail="dest 또는 remaining_waypoints를 1개 이상 지정해 주세요.",
            )
        last_wp   = remaining_wps.pop()
        dest_name = last_wp.get("name", "목적지")
        dest_lat  = float(last_wp["lat"])
        dest_lon  = float(last_wp["lon"])

    try:
        _normalize_waypoints_time_windows(remaining_wps, reference)
    except TimeWindowValidationError as exc:
        raise _http_422_from_time_window(exc) from exc

    nodes: list[dict] = [
        {"name": req.current_name, "lat": req.current_lat, "lon": req.current_lon}
    ]
    nodes += remaining_wps
    nodes.append({"name": dest_name, "lat": dest_lat, "lon": dest_lon})

    time_matrix, dist_matrix = await gh_svc.build_time_matrix(nodes, profile="truck")

    # 잔여 경유지 cargo_id / cargo_role → 상차→하차 순서 제약 (optimize·demo와 동일)
    pickup_deliveries: list[tuple[int, int]] | None = None
    pairs = _build_cargo_pickup_deliveries(remaining_wps, start_index=1)
    if pairs:
        pickup_deliveries = pairs

    _INF = 10_000_000
    time_windows: list[tuple[int, int]] | None = None
    if any(wp.get("earliest_sec") is not None or wp.get("latest_sec") is not None for wp in remaining_wps):
        time_windows = [(0, 0)]  # 현재 위치(출발)
        for wp in remaining_wps:
            e, l = wp.get("earliest_sec"), wp.get("latest_sec")
            time_windows.append((e or 0, l or _INF))
        time_windows.append((0, _INF))  # 목적지

    node_names = [n["name"] for n in nodes]
    violation = validate_tsp_constraints(
        time_matrix, time_windows, pickup_deliveries, node_names
    )
    if violation:
        code, msg = violation
        raise HTTPException(status_code=code, detail=msg)

    tsp_order = solve_tsp(
        time_matrix, time_windows=time_windows, pickup_deliveries=pickup_deliveries
    )
    if tsp_order is None:
        raise HTTPException(
            status_code=422,
            detail="경로 계산 실패: 복합 제약 충돌로 가능한 경로가 없습니다.",
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
    ordered_nodes.append(
        RouteNode(type="destination", name=dest_name, lat=dest_lat, lon=dest_lon)
    )

    rest_result = await db.execute(
        select(RestStop).where(
            RestStop.is_active == True,  # noqa: E712
            RestStop.type != "depot",
        )
    )
    rest_stops_db = [
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

    # 폴리라인 기반 휴게소 삽입 (Fix 1: 튜플 언패킹 제거, Fix 5: 정밀도 향상)
    geo_nodes_r = [{"lat": n.lat, "lon": n.lon} for n in ordered_nodes]
    try:
        polyline_r, route_time_sec_r, _ = await gh_svc.get_route_with_stats(
            geo_nodes_r, profile="truck"
        )
    except Exception:
        polyline_r = []
        route_time_sec_r = sum(
            final_matrix[i][i + 1] for i in range(len(ordered_nodes) - 1)
        )
    nearby_r = gh_svc.filter_rest_by_route(rest_stops_db, polyline_r) if polyline_r else rest_stops_db
    segment_times_r = [final_matrix[i][i + 1] for i in range(len(ordered_nodes) - 1)]
    final_route = await plan_rest_stops_from_polyline_async(
        ordered_nodes,
        polyline_r,
        route_time_sec_r,
        nearby_r,
        initial_drive_sec=req.current_drive_sec,
        is_emergency=req.is_emergency,
        segment_times=segment_times_r,
        profile="truck",
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


@router.post(
    "/dispatch",
    response_model=DispatchResponse,
    response_model_exclude_none=True,
)
async def dispatch_multi(req: DispatchRequest, db: AsyncSession = Depends(get_db)):
    """다수 차량 VRPTW 자동 배차 최적화.

    - depot_centered: 차고지 → 배송지 → 차고지 (기존)
    - vehicle_starts: 차량별 기사 현재 위치 출발, 기본 open_end(마지막 배송지 종료)
    - OR-Tools VRPTW: 시간창 + 적재 용량 제약
    - 차량별 법정 휴게소 자동 삽입
    """
    if not req.vehicles:
        raise HTTPException(status_code=400, detail="차량을 1대 이상 지정해 주세요.")
    if not req.nodes:
        raise HTTPException(status_code=400, detail="배송 노드를 1개 이상 지정해 주세요.")

    dispatch_mode = _resolve_dispatch_mode(req)

    try:
        reference = resolve_reference_departure_at(req.reference_departure_at)
    except TimeWindowValidationError as exc:
        raise _http_422_from_time_window(exc) from exc

    import math as _math

    _UNIT = 10  # 1 kg = 10 단위
    has_capacity = any(v.max_load_kg > 0 for v in req.vehicles)
    vehicle_capacities: list[int] | None = None
    if has_capacity:
        vehicle_capacities = [
            int(v.max_load_kg * _UNIT) if v.max_load_kg > 0 else 10_000_000
            for v in req.vehicles
        ]

    _n_nodes = len(req.nodes)
    _n_veh = len(req.vehicles)
    _max_per = max(1, _math.ceil(_n_nodes / _n_veh) + 1)

    depot_return_idx: int | None = None
    vehicle_start_indices: list[int] = []

    if dispatch_mode == "depot_centered":
        depot_name = req.depot_name or "depot"
        all_geo = [{"name": depot_name, "lat": req.depot_lat, "lon": req.depot_lon}]
        all_geo += [{"name": n.name, "lat": n.lat, "lon": n.lon} for n in req.nodes]
        time_matrix, _dist_matrix = await gh_svc.build_time_matrix(
            all_geo, profile=req.profile
        )
        _INF = sum(max(row) for row in time_matrix)
        time_windows = _build_dispatch_time_windows(
            reference, req.nodes, prefix_unrestricted=1, inf=_INF
        )
        demands = None
        if has_capacity:
            demands = [0] + [int(n.cargo_weight_kg * _UNIT) for n in req.nodes]
        result = solve_vrptw(
            time_matrix,
            num_vehicles=_n_veh,
            vehicle_capacities=vehicle_capacities,
            demands=demands,
            time_windows=time_windows,
            time_limit_seconds=req.time_limit_seconds,
            max_nodes_per_vehicle=_max_per,
        )
    else:
        all_geo = [{"name": n.name, "lat": n.lat, "lon": n.lon} for n in req.nodes]
        for vehicle in req.vehicles:
            start_name = vehicle.start_name or vehicle.name
            all_geo.append(
                {
                    "name": start_name,
                    "lat": vehicle.start_lat,
                    "lon": vehicle.start_lon,
                }
            )
        has_return = any(v.end_policy == "return_to_depot" for v in req.vehicles)
        if has_return:
            if req.depot_lat is None or req.depot_lon is None:
                raise HTTPException(
                    status_code=400,
                    detail="return_to_depot 종료 정책에는 depot_lat·depot_lon(복귀 차고지)이 필요합니다.",
                )
            depot_return_idx = len(all_geo)
            all_geo.append(
                {
                    "name": req.depot_name or "depot",
                    "lat": req.depot_lat,
                    "lon": req.depot_lon,
                }
            )

        time_matrix, _dist_matrix = await gh_svc.build_time_matrix(
            all_geo, profile=req.profile
        )
        _INF = sum(max(row) for row in time_matrix)
        n_customers = _n_nodes
        vehicle_start_indices = list(range(n_customers, n_customers + _n_veh))
        starts = vehicle_start_indices
        meta_depot = starts[0]
        end_policies = [v.end_policy for v in req.vehicles]
        ends: list[int | None] | None = None
        if depot_return_idx is not None:
            ends = [
                depot_return_idx if policy == "return_to_depot" else None
                for policy in end_policies
            ]

        suffix_tw = _n_veh + (1 if depot_return_idx is not None else 0)
        time_windows = _build_dispatch_time_windows(
            reference, req.nodes, suffix_unrestricted=suffix_tw, inf=_INF
        )
        demands = None
        if has_capacity:
            demands = [int(n.cargo_weight_kg * _UNIT) for n in req.nodes]
            demands += [0] * extra_tw

        result = solve_vrptw_with_vehicle_end_policy(
            time_matrix,
            starts=starts,
            end_policies=end_policies,
            ends=ends,
            depot=meta_depot,
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

    routes_out: list[DispatchVehicleRoute] = []
    for v_idx, (vehicle, node_indices) in enumerate(
        zip(req.vehicles, vehicle_routes_idx)
    ):
        if not node_indices:
            continue

        if dispatch_mode == "depot_centered":
            depot_name = req.depot_name or "depot"
            ordered: list[RouteNode] = [
                RouteNode(
                    type="origin",
                    name=depot_name,
                    lat=req.depot_lat,
                    lon=req.depot_lon,
                    can_rest=False,
                )
            ]
            for ni in node_indices:
                nd = req.nodes[ni - 1]
                ordered.append(
                    RouteNode(
                        type="waypoint",
                        name=nd.name,
                        lat=nd.lat,
                        lon=nd.lon,
                        can_rest=False,
                    )
                )
            ordered.append(
                RouteNode(
                    type="destination",
                    name=depot_name,
                    lat=req.depot_lat,
                    lon=req.depot_lon,
                    can_rest=False,
                )
            )
            matrix_idx = [0] + node_indices + [0]
        else:
            start_idx = vehicle_start_indices[v_idx]
            start_geo = all_geo[start_idx]
            ordered = [
                RouteNode(
                    type="origin",
                    name=start_geo["name"],
                    lat=start_geo["lat"],
                    lon=start_geo["lon"],
                    can_rest=False,
                )
            ]
            for i, ni in enumerate(node_indices):
                nd = req.nodes[ni]
                is_last = i == len(node_indices) - 1
                if is_last and vehicle.end_policy == "open_end":
                    node_type = "destination"
                else:
                    node_type = "waypoint"
                ordered.append(
                    RouteNode(
                        type=node_type,
                        name=nd.name,
                        lat=nd.lat,
                        lon=nd.lon,
                        can_rest=False,
                    )
                )
            if vehicle.end_policy == "return_to_depot" and depot_return_idx is not None:
                ordered.append(
                    RouteNode(
                        type="destination",
                        name=req.depot_name or "depot",
                        lat=req.depot_lat,
                        lon=req.depot_lon,
                        can_rest=False,
                    )
                )
            matrix_idx = [start_idx] + node_indices
            if vehicle.end_policy == "return_to_depot" and depot_return_idx is not None:
                matrix_idx.append(depot_return_idx)

        geo_nodes = [{"lat": n.lat, "lon": n.lon} for n in ordered]
        try:
            polyline, route_time_sec, route_dist_m = await gh_svc.get_route_with_stats(
                geo_nodes, profile=req.profile
            )
        except Exception:
            polyline = []
            route_time_sec = sum(
                time_matrix[matrix_idx[i]][matrix_idx[i + 1]]
                for i in range(len(matrix_idx) - 1)
            )
            route_dist_m = 0

        segment_times = [
            time_matrix[matrix_idx[i]][matrix_idx[i + 1]]
            for i in range(len(matrix_idx) - 1)
        ]

        nearby = gh_svc.filter_rest_by_route(rest_candidates, polyline)
        final_route = await plan_rest_stops_from_polyline_async(
            ordered,
            polyline,
            route_time_sec,
            nearby,
            segment_times=segment_times,
            profile=req.profile,
        )

        if dispatch_mode == "depot_centered":
            total_load = round(
                sum(req.nodes[ni - 1].cargo_weight_kg for ni in node_indices), 1
            )
        else:
            total_load = round(
                sum(req.nodes[ni].cargo_weight_kg for ni in node_indices), 1
            )
        rest_count = sum(1 for n in final_route if n.type == "rest_stop")

        routes_out.append(
            DispatchVehicleRoute(
                vehicle_name=vehicle.name,
                route=[RouteNodeSchema(**n.to_dict()) for n in final_route],
                total_distance_km=round(route_dist_m / 1000, 1),
                estimated_duration_min=round(route_time_sec / 60, 1),
                total_load_kg=total_load,
                rest_stops_count=rest_count,
            )
        )

    if dispatch_mode == "depot_centered":
        unassigned_names = [req.nodes[i - 1].name for i in unserved_idx]
    else:
        unassigned_names = [req.nodes[i].name for i in unserved_idx]

    return DispatchResponse(routes=routes_out, unassigned_nodes=unassigned_names)
