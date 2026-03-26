"""경로 최적화 API

엔드포인트 구성:
  POST /optimize/         — 관리자: 단일 차량 경로 최적화 (차고지 출발)
  POST /optimize/replan   — 시스템/운전자: 운행 중 재경로 계산
  POST /optimize/dispatch — 관리자: 다수 차량 배차 (TODO: 향후 구현)
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update

from app.api.deps import DbDep
from app.models.rest_stop import RestStop
from app.models.trip import Trip
from app.models.vehicle import Vehicle
from app.schemas.optimize import (
    DispatchRequest,
    DispatchResponse,
    OptimizeRequest,
    OptimizeResponse,
    ReplanRequest,
)
from app.services.route_optimizer import optimize_route

router = APIRouter(prefix="/optimize", tags=["optimize"])


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────────

async def _load_rest_stops(db) -> list[dict]:
    """활성 휴게소 목록을 DB에서 로드합니다."""
    rs_result = await db.execute(select(RestStop).where(RestStop.is_active.is_(True)))
    return [
        {"lat": rs.latitude, "lon": rs.longitude, "name": rs.name}
        for rs in rs_result.scalars()
    ]


# ── 1. 관리자 경로 최적화 ─────────────────────────────────────────────────────

@router.post("/", response_model=OptimizeResponse)
async def run_optimization(body: OptimizeRequest, db: DbDep) -> dict:
    """기사 출발 — 단일 차량 경로 최적화.

    기사가 현재 위치(출발지)를 전달하면 trip에 저장된 경유지·목적지·차량 제원으로
    최적 동선을 계산하고 법정 휴게소를 삽입합니다.
    """
    t_result = await db.execute(select(Trip).where(Trip.id == body.trip_id))
    trip = t_result.scalar_one_or_none()
    if not trip:
        raise HTTPException(status_code=404, detail="운행을 찾을 수 없습니다.")

    rest_stops = await _load_rest_stops(db)

    # 출발지: 기사가 전달한 현재 위치
    origin = {"lat": body.origin_lat, "lon": body.origin_lon, "name": body.origin_name}

    # 목적지·경유지: trip에 저장된 관리자 설정값
    destination = {"lat": trip.dest_lat, "lon": trip.dest_lon, "name": trip.dest_name}
    waypoints = trip.waypoints or []

    # 차량 제원: 요청 override → trip 저장값 순으로 사용
    vehicle_height = body.vehicle_height_m or trip.vehicle_height_m
    vehicle_weight = body.vehicle_weight_kg or trip.vehicle_weight_kg
    vehicle_length = body.vehicle_length_cm or trip.vehicle_length_cm
    vehicle_width  = body.vehicle_width_cm  or trip.vehicle_width_cm

    route_nodes, dist_km, dur_min = await optimize_route(
        origin=origin,
        destination=destination,
        waypoints=waypoints,
        rest_stops=rest_stops,
        vehicle_height=vehicle_height,
        vehicle_weight=vehicle_weight,
        vehicle_length=vehicle_length,
        vehicle_width=vehicle_width,
        initial_drive_sec=body.initial_drive_sec,
        extra_stops=[s.model_dump() for s in body.extra_stops],
        departure_time=trip.departure_time,
    )

    route_json = [n.model_dump() for n in route_nodes]
    # 기사의 출발지와 최적 경로를 trip에 저장
    await db.execute(
        update(Trip).where(Trip.id == body.trip_id).values(
            optimized_route=route_json,
            origin_name=body.origin_name,
            origin_lat=body.origin_lat,
            origin_lon=body.origin_lon,
        )
    )
    await db.commit()

    return {
        "trip_id": body.trip_id,
        "route": route_nodes,
        "total_distance_km": dist_km,
        "estimated_duration_min": dur_min,
        "rest_stops_count": sum(1 for n in route_nodes if n.type == "rest_stop"),
    }


# ── 2. 시스템/운전자 재경로 ───────────────────────────────────────────────────

@router.post("/replan", response_model=OptimizeResponse)
async def replan_route(body: ReplanRequest, db: DbDep) -> dict:
    """운행 중 재경로 계산 — 시스템 자동 트리거 또는 운전자 직접 호출.

    정체·경로 이탈로 누적 운전시간이 한도에 근접했을 때 호출합니다.
    current_drive_sec 이 initial_drive_sec 으로 전달되어,
    다음 구간 진입 전에 즉시 휴게소 삽입이 필요하면 자동으로 처리됩니다.
    """
    t_result = await db.execute(select(Trip).where(Trip.id == body.trip_id))
    trip = t_result.scalar_one_or_none()
    if not trip:
        raise HTTPException(status_code=404, detail="운행을 찾을 수 없습니다.")

    rest_stops = await _load_rest_stops(db)
    origin = {
        "lat": body.current_lat,
        "lon": body.current_lon,
        "name": body.current_name,
    }
    destination = {"lat": body.dest_lat, "lon": body.dest_lon, "name": body.dest_name}

    route_nodes, dist_km, dur_min = await optimize_route(
        origin=origin,
        destination=destination,
        waypoints=body.remaining_waypoints,
        rest_stops=rest_stops,
        vehicle_height=body.vehicle_height_m,
        vehicle_weight=body.vehicle_weight_kg,
        vehicle_length=body.vehicle_length_cm,
        vehicle_width=body.vehicle_width_cm,
        initial_drive_sec=body.current_drive_sec,   # 누적 운전시간 이어받기
        extra_stops=[s.model_dump() for s in body.extra_stops],
    )

    route_json = [n.model_dump() for n in route_nodes]
    await db.execute(
        update(Trip).where(Trip.id == body.trip_id).values(optimized_route=route_json)
    )
    await db.commit()

    return {
        "trip_id": body.trip_id,
        "route": route_nodes,
        "total_distance_km": dist_km,
        "estimated_duration_min": dur_min,
        "rest_stops_count": sum(1 for n in route_nodes if n.type == "rest_stop"),
    }


# ── 3. 배차 (향후 구현) ───────────────────────────────────────────────────────

@router.post("/dispatch", response_model=DispatchResponse)
async def dispatch_vehicles(body: DispatchRequest, db: DbDep) -> dict:
    """관리자 다수 차량 배차 — OR-Tools CVRP 기반 경유지 분배.

    TODO: 향후 구현 예정.
    - 여러 차량에 경유지를 최적 분배
    - 차량별 적재 용량·운전 가능 시간 제약 반영
    - 각 차량의 개별 경로(optimize_route)를 병렬 계산
    """
    raise HTTPException(status_code=501, detail="배차 기능은 아직 구현되지 않았습니다.")
