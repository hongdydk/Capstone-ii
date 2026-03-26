from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbDep
from app.models.trip import Trip, TripStatus
from app.schemas.trip import TripCreate, TripResponse, TripStatusUpdate

router = APIRouter(prefix="/trips", tags=["trips"])


@router.get("/", response_model=list[TripResponse])
async def list_trips(db: DbDep) -> list[Trip]:
    result = await db.execute(select(Trip).order_by(Trip.id.desc()))
    return list(result.scalars())


@router.post("/", response_model=TripResponse, status_code=status.HTTP_201_CREATED)
async def create_trip(body: TripCreate, db: DbDep) -> Trip:
    trip = Trip(
        driver_id=body.driver_id,
        vehicle_id=body.vehicle_id,
        dest_name=body.dest_name,
        dest_lat=body.dest_lat,
        dest_lon=body.dest_lon,
        waypoints=[w.model_dump() for w in body.waypoints],
        vehicle_height_m=body.vehicle_height_m,
        vehicle_weight_kg=body.vehicle_weight_kg,
        vehicle_length_cm=body.vehicle_length_cm,
        vehicle_width_cm=body.vehicle_width_cm,
        departure_time=body.departure_time,
    )
    db.add(trip)
    await db.commit()
    await db.refresh(trip)
    return trip


@router.get("/{trip_id}", response_model=TripResponse)
async def get_trip(trip_id: int, db: DbDep) -> Trip:
    result = await db.execute(select(Trip).where(Trip.id == trip_id))
    trip = result.scalar_one_or_none()
    if not trip:
        raise HTTPException(status_code=404, detail="운행을 찾을 수 없습니다.")
    return trip


@router.patch("/{trip_id}/status", response_model=TripResponse)
async def update_status(
    trip_id: int, body: TripStatusUpdate, db: DbDep
) -> Trip:
    result = await db.execute(select(Trip).where(Trip.id == trip_id))
    trip = result.scalar_one_or_none()
    if not trip:
        raise HTTPException(status_code=404, detail="운행을 찾을 수 없습니다.")

    trip.status = body.status
    if body.status == TripStatus.IN_PROGRESS and trip.started_at is None:
        trip.started_at = datetime.now(UTC)
    elif body.status == TripStatus.COMPLETED:
        trip.completed_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(trip)
    return trip
