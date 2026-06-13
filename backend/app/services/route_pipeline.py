"""경로 최적화 파이프라인 — basic / with_rest / replan 공통 헬퍼."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rest_stop import RestStop
from app.models.trip import Trip, TripStatus
from app.schemas.optimize import (
    OptimizeRequest,
    OptimizeResponse,
    ReplanRequest,
    RouteNodeSchema,
)
from app.services import graphhopper as gh_svc
from app.services.optimizer import solve_tsp, validate_tsp_constraints
from app.services.rest_stop_inserter import RouteNode, plan_rest_stops_from_polyline_async
from app.services.time_windows import (
    TimeWindowValidationError,
    apply_resolved_windows_to_dict,
    copy_time_fields_to_dict,
    resolve_reference_departure_at,
)

_INF = 10_000_000


def http_422_from_time_window(exc: TimeWindowValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def normalize_waypoints_time_windows(
    waypoints: list[dict],
    reference,
    *,
    extra_labels: dict[int, str] | None = None,
) -> None:
    """경유지 dict 목록의 캘린더 시간창을 earliest_sec/latest_sec로 일괄 변환."""
    for i, wp in enumerate(waypoints):
        label = (extra_labels or {}).get(i) or wp.get("name", f"경유지 {i + 1}")
        apply_resolved_windows_to_dict(wp, reference, label=label)


def build_cargo_pickup_deliveries(
    waypoints: list[dict],
    *,
    start_index: int = 1,
) -> list[tuple[int, int]]:
    """경유지 dict 목록에서 cargo_id 기준 pickup→delivery OR-Tools 쌍을 생성합니다."""
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


def next_route_version(existing: dict | None) -> int:
    """optimized_route JSONB 내 route_version — 최초 1, replan마다 +1."""
    if existing and isinstance(existing.get("route_version"), int):
        return existing["route_version"] + 1
    return 1


def build_optimized_route_payload(
    route_dicts: list[dict],
    total_sec: int,
    rest_count: int,
    existing: dict | None,
) -> dict:
    return {
        "route": route_dicts,
        "estimated_duration_min": round(total_sec / 60, 1),
        "rest_stops_count": rest_count,
        "route_version": next_route_version(existing),
    }


@dataclass
class PreparedOptimizeNodes:
    nodes: list[dict]
    waypoints_raw: list[dict]
    dest_name: str
    dest_lat: float
    dest_lon: float
    preferred_rest: list[dict]


def prepare_optimize_nodes(trip: Trip, req: OptimizeRequest) -> PreparedOptimizeNodes:
    """출발지·경유지·목적지 노드 목록과 휴게 희망지를 구성합니다."""
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

    if dest_name is None:
        delivery_wps = [wp for wp in waypoints_raw if wp.get("cargo_role") == "delivery"]
        endpoint_wp = (
            delivery_wps[-1]
            if delivery_wps
            else (waypoints_raw[-1] if waypoints_raw else None)
        )
        if endpoint_wp is None:
            raise HTTPException(
                status_code=400, detail="목적지 또는 경유지를 최소 1개 지정해 주세요."
            )
        waypoints_raw = [wp for wp in waypoints_raw if wp is not endpoint_wp]
        dest_name = endpoint_wp["name"]
        dest_lat = endpoint_wp["lat"]
        dest_lon = endpoint_wp["lon"]

    nodes: list[dict] = [
        {"name": req.origin_name, "lat": req.origin_lat, "lon": req.origin_lon}
    ]
    nodes += waypoints_raw
    nodes.append({"name": dest_name, "lat": dest_lat, "lon": dest_lon})

    return PreparedOptimizeNodes(
        nodes=nodes,
        waypoints_raw=waypoints_raw,
        dest_name=dest_name,
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        preferred_rest=preferred_rest,
    )


def resolve_tsp_order(
    nodes: list[dict],
    waypoints_raw: list[dict],
    time_matrix: list[list[int]],
    *,
    use_tsp: bool,
) -> list[int]:
    """방문 순서 인덱스. basic은 요청 순서 고정, with_rest는 OR-Tools TSP."""
    if not use_tsp:
        return list(range(len(nodes) - 1))

    time_windows: list[tuple[int, int]] | None = None
    tw_list: list[tuple[int, int]] = [(0, 0)]
    has_any_tw = False
    for wp in waypoints_raw:
        e = wp.get("earliest_sec")
        l = wp.get("latest_sec")
        if e is not None or l is not None:
            has_any_tw = True
        tw_list.append((e or 0, l or _INF))
    tw_list.append((0, _INF))

    if has_any_tw:
        time_windows = tw_list

    pairs = build_cargo_pickup_deliveries(waypoints_raw, start_index=1)
    pickup_deliveries: list[tuple[int, int]] | None = pairs or None

    node_names = [n["name"] for n in nodes]
    violation = validate_tsp_constraints(
        time_matrix, time_windows, pickup_deliveries, node_names,
    )
    if violation:
        code, msg = violation
        raise HTTPException(status_code=code, detail=msg)

    tsp_order = solve_tsp(
        time_matrix, time_windows=time_windows, pickup_deliveries=pickup_deliveries,
    )
    if tsp_order is None:
        raise HTTPException(
            status_code=422,
            detail="경로 계산 실패: 복합 제약 충돌로 가능한 경로가 없습니다. 시간창 범위나 경유지 순서를 조정해 주세요.",
        )
    return tsp_order


def _build_ordered_nodes_fixed_order(nodes: list[dict]) -> list[RouteNode]:
    """출발→경유(요청 순)→목적 순서의 RouteNode 목록 (basic 파이프라인)."""
    last = len(nodes) - 1
    return [
        RouteNode(
            type="origin" if idx == 0 else (
                "destination" if idx == last else "waypoint"
            ),
            name=n["name"],
            lat=n["lat"],
            lon=n["lon"],
        )
        for idx, n in enumerate(nodes)
    ]


async def fetch_route_stats_for_ordered_nodes(
    ordered_nodes: list[RouteNode],
) -> tuple[int, int, list[list[float]]]:
    """GH route 1회로 시간(초)·거리(m)·polyline을 반환합니다 (실패 시 propagate)."""
    geo_nodes = [{"lat": n.lat, "lon": n.lon} for n in ordered_nodes]
    polyline, route_time_sec, route_dist_m = await gh_svc.get_route_with_stats(
        geo_nodes, profile="truck",
    )
    return route_time_sec, route_dist_m, polyline


def build_ordered_nodes_and_matrices(
    nodes: list[dict],
    tsp_order: list[int],
    dest_name: str,
    dest_lat: float,
    dest_lon: float,
    time_matrix: list[list[int]],
    dist_matrix: list[list[int]],
) -> tuple[list[RouteNode], list[list[int]], list[list[int]]]:
    """TSP 순서 기준 ordered_nodes와 재배열된 time/dist 행렬을 반환합니다."""
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

    dest_idx = len(nodes) - 1
    k = len(tsp_order)
    n_ordered = len(ordered_nodes)

    final_matrix = [[0] * n_ordered for _ in range(n_ordered)]
    final_dist = [[0] * n_ordered for _ in range(n_ordered)]
    for i in range(k):
        for j in range(k):
            final_matrix[i][j] = time_matrix[tsp_order[i]][tsp_order[j]]
            final_dist[i][j] = dist_matrix[tsp_order[i]][tsp_order[j]]
        final_matrix[i][k] = time_matrix[tsp_order[i]][dest_idx]
        final_dist[i][k] = dist_matrix[tsp_order[i]][dest_idx]

    return ordered_nodes, final_matrix, final_dist


async def load_rest_candidates(
    db: AsyncSession,
    preferred_rest: list[dict] | None = None,
) -> list[dict]:
    """DB 휴게소 + 희망 휴게소 후보 목록."""
    rest_result = await db.execute(
        select(RestStop).where(
            RestStop.is_active == True,  # noqa: E712
            RestStop.type != "depot",
        )
    )
    rest_stops_db = rest_result.scalars().all()
    return (preferred_rest or []) + [
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


async def insert_rest_stops(
    ordered_nodes: list[RouteNode],
    final_matrix: list[list[int]],
    final_dist: list[list[int]],
    rest_candidates: list[dict],
    *,
    initial_drive_sec: int = 0,
    is_emergency: bool = False,
) -> list[RouteNode]:
    """폴리라인 기반 법정 휴게소 삽입 (geometry 실패 시 propagate)."""
    geo_nodes = [{"lat": n.lat, "lon": n.lon} for n in ordered_nodes]
    polyline, route_time_sec, route_dist_m, instructions = (
        await gh_svc.get_route_with_stats(
            geo_nodes, profile="truck", with_instructions=True,
        )
    )

    nearby = (
        gh_svc.filter_rest_by_route(rest_candidates, polyline)
        if polyline
        else rest_candidates
    )
    segment_times = [
        final_matrix[i][i + 1] for i in range(len(ordered_nodes) - 1)
    ]
    return await plan_rest_stops_from_polyline_async(
        ordered_nodes,
        polyline,
        route_time_sec,
        nearby,
        initial_drive_sec=initial_drive_sec,
        is_emergency=is_emergency,
        segment_times=segment_times,
        route_dist_m=route_dist_m if polyline else None,
        instructions=instructions,
        profile="truck",
    )


def compute_route_totals(
    ordered_nodes: list[RouteNode],
    final_matrix: list[list[int]],
    final_dist: list[list[int]],
) -> tuple[int, float]:
    total_sec = sum(
        final_matrix[i][i + 1] for i in range(len(ordered_nodes) - 1)
    )
    total_distance_km = round(
        sum(final_dist[i][i + 1] for i in range(len(ordered_nodes) - 1)) / 1000, 1
    )
    return total_sec, total_distance_km


def build_optimize_response(
    trip_id: int,
    final_route: list[RouteNode],
    total_sec: int,
    total_distance_km: float,
) -> OptimizeResponse:
    rest_count = sum(1 for n in final_route if n.type == "rest_stop")
    return OptimizeResponse(
        trip_id=trip_id,
        route=[RouteNodeSchema(**n.to_dict()) for n in final_route],
        total_distance_km=total_distance_km,
        estimated_duration_min=round(total_sec / 60, 1),
        rest_stops_count=rest_count,
    )


async def apply_route_to_trip(
    trip: Trip,
    trip_id: int,
    final_route: list[RouteNode],
    total_sec: int,
    total_distance_km: float,
    db: AsyncSession,
    *,
    event: Literal["optimize", "replan"],
    origin_name: str | None = None,
    origin_lat: float | None = None,
    origin_lon: float | None = None,
) -> OptimizeResponse:
    """경로 계산 결과를 Trip에 반영하고 DB에 커밋합니다 (optimize/replan 공통 persist)."""
    rest_count = sum(1 for n in final_route if n.type == "rest_stop")
    route_dicts = [n.to_dict() for n in final_route]
    trip.optimized_route = build_optimized_route_payload(
        route_dicts, total_sec, rest_count, trip.optimized_route,
    )
    if event == "optimize":
        trip.origin_name = origin_name
        trip.origin_lat = origin_lat
        trip.origin_lon = origin_lon
        trip.status = TripStatus.in_progress
    await db.commit()
    return build_optimize_response(trip_id, final_route, total_sec, total_distance_km)


async def run_basic_optimize(
    trip: Trip,
    req: OptimizeRequest,
    db: AsyncSession,
) -> OptimizeResponse:
    """요청 순서 고정·휴게 삽입 생략 파이프라인."""
    try:
        reference = resolve_reference_departure_at(
            req.reference_departure_at,
            trip_departure_time=trip.departure_time,
        )
    except TimeWindowValidationError as exc:
        raise http_422_from_time_window(exc) from exc

    prepared = prepare_optimize_nodes(trip, req)
    try:
        normalize_waypoints_time_windows(prepared.waypoints_raw, reference)
    except TimeWindowValidationError as exc:
        raise http_422_from_time_window(exc) from exc

    ordered_nodes = _build_ordered_nodes_fixed_order(prepared.nodes)
    total_sec, route_dist_m, _polyline = await fetch_route_stats_for_ordered_nodes(
        ordered_nodes,
    )
    total_distance_km = round(route_dist_m / 1000, 1)
    final_route = ordered_nodes

    return await apply_route_to_trip(
        trip,
        trip.id,
        final_route,
        total_sec,
        total_distance_km,
        db,
        event="optimize",
        origin_name=req.origin_name,
        origin_lat=req.origin_lat,
        origin_lon=req.origin_lon,
    )


async def run_with_rest_optimize(
    trip: Trip,
    req: OptimizeRequest,
    db: AsyncSession,
) -> OptimizeResponse:
    """TSP + 법정 휴게 삽입 파이프라인."""
    try:
        reference = resolve_reference_departure_at(
            req.reference_departure_at,
            trip_departure_time=trip.departure_time,
        )
    except TimeWindowValidationError as exc:
        raise http_422_from_time_window(exc) from exc

    prepared = prepare_optimize_nodes(trip, req)
    try:
        normalize_waypoints_time_windows(prepared.waypoints_raw, reference)
    except TimeWindowValidationError as exc:
        raise http_422_from_time_window(exc) from exc

    # TSP 전용 — N² GH 행렬 (basic 파이프라인은 사용하지 않음)
    time_matrix, dist_matrix = await gh_svc.build_time_matrix(
        prepared.nodes, profile="truck",
    )
    tsp_order = resolve_tsp_order(
        prepared.nodes, prepared.waypoints_raw, time_matrix, use_tsp=True,
    )
    ordered_nodes, final_matrix, final_dist = build_ordered_nodes_and_matrices(
        prepared.nodes,
        tsp_order,
        prepared.dest_name,
        prepared.dest_lat,
        prepared.dest_lon,
        time_matrix,
        dist_matrix,
    )

    rest_candidates = await load_rest_candidates(db, prepared.preferred_rest)
    final_route = await insert_rest_stops(
        ordered_nodes,
        final_matrix,
        final_dist,
        rest_candidates,
        initial_drive_sec=req.initial_drive_sec,
    )
    total_sec, total_distance_km = compute_route_totals(
        ordered_nodes, final_matrix, final_dist,
    )

    return await apply_route_to_trip(
        trip,
        trip.id,
        final_route,
        total_sec,
        total_distance_km,
        db,
        event="optimize",
        origin_name=req.origin_name,
        origin_lat=req.origin_lat,
        origin_lon=req.origin_lon,
    )


async def run_replan_with_rest(
    trip: Trip,
    req: ReplanRequest,
    db: AsyncSession,
) -> OptimizeResponse:
    """운행 중 재경로 — with_rest 계열 (TSP + 휴게 삽입)."""
    try:
        reference = resolve_reference_departure_at(
            req.reference_departure_at,
            trip_departure_time=None,
        )
    except TimeWindowValidationError as exc:
        raise http_422_from_time_window(exc) from exc

    remaining_wps = list(req.remaining_waypoints)
    dest_name = req.dest_name
    dest_lat = req.dest_lat
    dest_lon = req.dest_lon
    if dest_name is None or dest_lat is None or dest_lon is None:
        if not remaining_wps:
            raise HTTPException(
                status_code=400,
                detail="dest 또는 remaining_waypoints를 1개 이상 지정해 주세요.",
            )
        last_wp = remaining_wps.pop()
        dest_name = last_wp.get("name", "목적지")
        dest_lat = float(last_wp["lat"])
        dest_lon = float(last_wp["lon"])

    try:
        normalize_waypoints_time_windows(remaining_wps, reference)
    except TimeWindowValidationError as exc:
        raise http_422_from_time_window(exc) from exc

    nodes: list[dict] = [
        {"name": req.current_name, "lat": req.current_lat, "lon": req.current_lon}
    ]
    nodes += remaining_wps
    nodes.append({"name": dest_name, "lat": dest_lat, "lon": dest_lon})

    # TSP 전용 — N² GH 행렬 (basic 파이프라인은 사용하지 않음)
    time_matrix, dist_matrix = await gh_svc.build_time_matrix(nodes, profile="truck")

    pickup_deliveries: list[tuple[int, int]] | None = None
    pairs = build_cargo_pickup_deliveries(remaining_wps, start_index=1)
    if pairs:
        pickup_deliveries = pairs

    time_windows: list[tuple[int, int]] | None = None
    if any(
        wp.get("earliest_sec") is not None or wp.get("latest_sec") is not None
        for wp in remaining_wps
    ):
        time_windows = [(0, 0)]
        for wp in remaining_wps:
            e, l = wp.get("earliest_sec"), wp.get("latest_sec")
            time_windows.append((e or 0, l or _INF))
        time_windows.append((0, _INF))

    node_names = [n["name"] for n in nodes]
    violation = validate_tsp_constraints(
        time_matrix, time_windows, pickup_deliveries, node_names,
    )
    if violation:
        code, msg = violation
        raise HTTPException(status_code=code, detail=msg)

    tsp_order = solve_tsp(
        time_matrix, time_windows=time_windows, pickup_deliveries=pickup_deliveries,
    )
    if tsp_order is None:
        raise HTTPException(
            status_code=422,
            detail="경로 계산 실패: 복합 제약 충돌로 가능한 경로가 없습니다.",
        )

    ordered_nodes, final_matrix, final_dist = build_ordered_nodes_and_matrices(
        nodes,
        tsp_order,
        dest_name,
        dest_lat,
        dest_lon,
        time_matrix,
        dist_matrix,
    )

    rest_candidates = await load_rest_candidates(db)
    final_route = await insert_rest_stops(
        ordered_nodes,
        final_matrix,
        final_dist,
        rest_candidates,
        initial_drive_sec=req.current_drive_sec,
        is_emergency=req.is_emergency,
    )
    total_sec, total_distance_km = compute_route_totals(
        ordered_nodes, final_matrix, final_dist,
    )

    return await apply_route_to_trip(
        trip,
        req.trip_id,
        final_route,
        total_sec,
        total_distance_km,
        db,
        event="replan",
    )
