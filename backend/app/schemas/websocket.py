from typing import Literal

from pydantic import BaseModel

from app.models.location_log import DrivingState
from app.schemas.optimize import OptimizeResponse, ReplanRequest


class WSLocationUpdate(BaseModel):
    type: Literal["location_update"]
    trip_id: int
    latitude: float
    longitude: float
    speed_kmh: float | None = None
    state: DrivingState = DrivingState.unknown


class WSReplanRequest(BaseModel):
    type: Literal["replan"]
    payload: ReplanRequest


class WSAck(BaseModel):
    type: Literal["drive_status"] = "drive_status"
    trip_id: int
    accumulated_drive_sec: int
    needs_replan: bool


class WSRouteUpdated(BaseModel):
    type: Literal["route_updated"] = "route_updated"
    payload: OptimizeResponse


class WSError(BaseModel):
    type: Literal["error"] = "error"
    code: int
    message: str