from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.trip import Trip
from app.schemas.optimize import (
    OptimizeRequest,
    OptimizeResponse,
    ReplanRequest,
)
from app.services.route_pipeline import (
    build_cargo_pickup_deliveries,
    build_optimized_route_payload,
    next_route_version,
    run_basic_optimize,
    run_replan_with_rest,
    run_with_rest_optimize,
)

# 테스트·하위 호환 re-export
__all__ = [
    "router",
    "_build_cargo_pickup_deliveries",
    "_build_optimized_route_payload",
    "_next_route_version",
    "optimize",
    "optimize_basic",
    "optimize_with_rest",
    "replan",
]

_build_cargo_pickup_deliveries = build_cargo_pickup_deliveries
_build_optimized_route_payload = build_optimized_route_payload
_next_route_version = next_route_version

router = APIRouter()


async def _load_trip(trip_id: int, db: AsyncSession) -> Trip:
    trip = await db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


@router.post("/", response_model=OptimizeResponse)
async def optimize(req: OptimizeRequest, db: AsyncSession = Depends(get_db)):
    """단일 차량 경로 최적화. optimize_mode로 basic / with_rest 파이프라인에 위임."""
    trip = await _load_trip(req.trip_id, db)
    if req.optimize_mode == "basic":
        return await run_basic_optimize(trip, req, db)
    return await run_with_rest_optimize(trip, req, db)


@router.post("/basic", response_model=OptimizeResponse)
async def optimize_basic(req: OptimizeRequest, db: AsyncSession = Depends(get_db)):
    """단순 길찾기·내비 — 요청 순서 고정, 휴게 삽입 생략."""
    trip = await _load_trip(req.trip_id, db)
    return await run_basic_optimize(trip, req, db)


@router.post("/with-rest", response_model=OptimizeResponse)
async def optimize_with_rest(req: OptimizeRequest, db: AsyncSession = Depends(get_db)):
    """TSP + 법정 휴게 삽입 (프로젝트 핵심). optimize_mode 필드는 무시."""
    trip = await _load_trip(req.trip_id, db)
    return await run_with_rest_optimize(trip, req, db)


@router.post("/replan", response_model=OptimizeResponse)
async def replan(req: ReplanRequest, db: AsyncSession = Depends(get_db)):
    """운행 중 재경로 계산. with_rest 계열 (TSP + 휴게 삽입)."""
    trip = await _load_trip(req.trip_id, db)
    return await run_replan_with_rest(trip, req, db)
