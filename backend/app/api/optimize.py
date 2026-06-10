from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.trip import Trip, TripStatus
from app.models.rest_stop import RestStop
from app.schemas.optimize import (
    OptimizeRequest,
    OptimizeResponse,
    ReplanRequest,
    RouteNodeSchema,
)
from app.services import graphhopper as gh_svc
from app.services.optimizer import (
    solve_tsp,
    validate_tsp_constraints,
)
from app.services.rest_stop_inserter import RouteNode, plan_rest_stops_from_polyline_async
from app.services.time_windows import (
    TimeWindowValidationError,
    apply_resolved_windows_to_dict,
    copy_time_fields_to_dict,
    resolve_reference_departure_at,
)


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
