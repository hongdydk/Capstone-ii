from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import AsyncSessionLocal
from app.schemas.location_log import LocationLogCreate
from app.schemas.optimize import ReplanRequest
from app.schemas.websocket import WSAck, WSError, WSLocationUpdate, WSReplanRequest, WSRouteUpdated
from app.api.optimize import replan
from app.services.realtime import create_location_log_and_status

router = APIRouter()


@router.websocket("/trips/{trip_id}")
async def trip_socket(websocket: WebSocket, trip_id: int):
    await websocket.accept()

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")

            async with AsyncSessionLocal() as db:
                try:
                    if msg_type == "location_update":
                        payload = WSLocationUpdate(**message)
                        if payload.trip_id != trip_id:
                            await websocket.send_json(WSError(code=400, message="trip_id mismatch").model_dump())
                            continue
                        status = await create_location_log_and_status(
                            LocationLogCreate(
                                trip_id=payload.trip_id,
                                latitude=payload.latitude,
                                longitude=payload.longitude,
                                speed_kmh=payload.speed_kmh,
                                state=payload.state,
                            ),
                            db,
                        )
                        await websocket.send_json(
                            WSAck(
                                trip_id=trip_id,
                                accumulated_drive_sec=status["accumulated_drive_sec"],
                                needs_replan=status["needs_replan"],
                            ).model_dump()
                        )
                    elif msg_type == "replan":
                        payload = WSReplanRequest(**message)
                        if payload.payload.trip_id != trip_id:
                            await websocket.send_json(WSError(code=400, message="trip_id mismatch").model_dump())
                            continue
                        route = await replan(payload.payload, db)
                        await websocket.send_json(WSRouteUpdated(payload=route).model_dump())
                    else:
                        await websocket.send_json(WSError(code=400, message="unknown message type").model_dump())
                except Exception as exc:
                    code = getattr(exc, "status_code", 500)
                    detail = getattr(exc, "detail", str(exc))
                    await websocket.send_json(WSError(code=code, message=detail).model_dump())
    except WebSocketDisconnect:
        return