"""Dispatch API contract tests."""

from fastapi.routing import APIRoute

from app.api.optimize import router
from app.schemas.optimize import DispatchVehicleRoute, RouteNodeSchema


def _dump_exclude_none(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)
    return model.dict(exclude_none=True)


def test_dispatch_vehicle_route_polyline_is_optional_debug_field():
    route = DispatchVehicleRoute(
        vehicle_name="truck-1",
        route=[
            RouteNodeSchema(type="origin", name="depot", lat=37.0, lon=127.0),
            RouteNodeSchema(type="destination", name="depot", lat=37.0, lon=127.0),
        ],
        total_distance_km=0.0,
        estimated_duration_min=0.0,
        total_load_kg=0.0,
        rest_stops_count=0,
    )

    assert route.polyline is None
    assert "polyline" not in _dump_exclude_none(route)


def test_dispatch_response_omits_none_debug_fields():
    dispatch_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/dispatch"
    )

    assert dispatch_route.response_model_exclude_none is True
