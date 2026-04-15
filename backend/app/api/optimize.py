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
)
from app.services import kakao as kakao_svc
from app.services.optimizer import solve_tsp
from app.services.rest_stop_inserter import RouteNode, insert_rest_stops

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

    extra_stops = req.extra_stops or []
    new_dest = None
    preferred_rest: list[dict] = []

    for es in extra_stops:
        if es.stop_type == "waypoint":
            waypoints_raw.append({"name": es.name, "lat": es.lat, "lon": es.lon})
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

    # 노드 순서: [출발지, ...경유지, 목적지]
    nodes: list[dict] = [
        {"name": req.origin_name, "lat": req.origin_lat, "lon": req.origin_lon}
    ]
    nodes += waypoints_raw
    nodes.append({"name": dest_name, "lat": dest_lat, "lon": dest_lon})

    veh = _resolve_vehicle_params(trip, req)

    # ------------------------------------------------------------------
    # 2. Kakao NxN 시간·거리 행렬 계산
    # ------------------------------------------------------------------
    resolved_mode = (
        kakao_svc.auto_detect_route_mode(nodes)
        if req.route_mode == "auto"
        else req.route_mode
    )
    time_matrix, dist_matrix = await kakao_svc.build_time_matrix(
        nodes,
        route_mode=resolved_mode,
        departure_time=trip.departure_time,
        **veh,
    )

    # ------------------------------------------------------------------
    # 3. OR-Tools TSP 경유지 순서 최적화
    # ------------------------------------------------------------------
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
        picker=kakao_svc.find_best_rest_stop,
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

    veh = {
        "height_m": req.vehicle_height_m or trip.vehicle_height_m,
        "weight_kg": req.vehicle_weight_kg or trip.vehicle_weight_kg,
        "length_cm": req.vehicle_length_cm or trip.vehicle_length_cm,
        "width_cm": req.vehicle_width_cm or trip.vehicle_width_cm,
    }

    resolved_mode = (
        kakao_svc.auto_detect_route_mode(nodes)
        if req.route_mode == "auto"
        else req.route_mode
    )
    time_matrix, dist_matrix = await kakao_svc.build_time_matrix(nodes, route_mode=resolved_mode, **veh)
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

    final_route = await insert_rest_stops(
        ordered_nodes, final_matrix, rest_stops_db,
        initial_drive_sec=req.current_drive_sec,
        is_emergency=req.is_emergency,
        picker=kakao_svc.find_best_rest_stop,
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


@router.post("/dispatch", status_code=501)
async def dispatch_multi():
    """다수 차량 배차 최적화 (VRP) — 구현 예정."""
    raise HTTPException(status_code=501, detail="Not implemented")
