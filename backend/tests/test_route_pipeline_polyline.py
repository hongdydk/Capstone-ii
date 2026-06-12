"""with_rest·replan polyline GH fail-fast(H2-A) 단위 테스트."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.optimize import optimize_with_rest, replan
from app.models.trip import Trip, TripStatus
from app.schemas.optimize import OptimizeRequest, ReplanRequest
from app.services import route_pipeline as pipeline


_POLYLINE_FAILURE_DETAIL = "경로 서버(GraphHopper)에 연결할 수 없습니다."


def _make_trip(**kwargs) -> Trip:
    defaults = dict(
        id=1,
        driver_id=1,
        vehicle_id=1,
        status=TripStatus.scheduled,
        dest_name="목적지",
        dest_lat=37.6,
        dest_lon=127.1,
        waypoints=[{"name": "경유1", "lat": 37.55, "lon": 127.05}],
    )
    defaults.update(kwargs)
    return Trip(**defaults)


async def _raise_polyline_503(*_args, **_kwargs):
    raise HTTPException(status_code=503, detail=_POLYLINE_FAILURE_DETAIL)


def _patch_matrix(monkeypatch):
    matrix = [
        [0, 300, 600],
        [300, 0, 300],
        [600, 300, 0],
    ]

    async def _fake_build_time_matrix(nodes, profile="truck"):
        return matrix, matrix

    monkeypatch.setattr(pipeline.gh_svc, "build_time_matrix", _fake_build_time_matrix)


def _patch_db_rest_empty(db: AsyncMock):
    rest_result = MagicMock()
    rest_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=rest_result)


@pytest.mark.parametrize("handler", [optimize_with_rest, pipeline.run_with_rest_optimize])
def test_with_rest_propagates_polyline_503(handler, monkeypatch):
    trip = _make_trip()
    db = AsyncMock()
    db.get = AsyncMock(return_value=trip)
    _patch_matrix(monkeypatch)
    _patch_db_rest_empty(db)
    monkeypatch.setattr(pipeline.gh_svc, "get_route_with_stats", _raise_polyline_503)

    plan_rest_called = False

    async def _fake_plan_rest(*args, **kwargs):
        nonlocal plan_rest_called
        plan_rest_called = True
        return args[0]

    monkeypatch.setattr(
        pipeline, "plan_rest_stops_from_polyline_async", _fake_plan_rest,
    )

    if handler is optimize_with_rest:
        req = OptimizeRequest(
            trip_id=1,
            origin_name="출발",
            origin_lat=37.5,
            origin_lon=127.0,
        )
        with pytest.raises(HTTPException) as exc:
            asyncio.run(handler(req, db))
    else:
        req = OptimizeRequest(
            trip_id=1,
            origin_name="출발",
            origin_lat=37.5,
            origin_lon=127.0,
        )
        with pytest.raises(HTTPException) as exc:
            asyncio.run(handler(trip, req, db))

    assert exc.value.status_code == 503
    assert plan_rest_called is False
    db.commit.assert_not_awaited()


def test_replan_propagates_polyline_503(monkeypatch):
    trip = Trip(
        id=42,
        driver_id=1,
        vehicle_id=1,
        status=TripStatus.in_progress,
        optimized_route={"route_version": 1},
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=trip)
    _patch_matrix(monkeypatch)
    _patch_db_rest_empty(db)
    monkeypatch.setattr(pipeline.gh_svc, "get_route_with_stats", _raise_polyline_503)

    plan_rest_called = False

    async def _fake_plan_rest(*args, **kwargs):
        nonlocal plan_rest_called
        plan_rest_called = True
        return args[0]

    monkeypatch.setattr(
        pipeline, "plan_rest_stops_from_polyline_async", _fake_plan_rest,
    )

    req = ReplanRequest(
        trip_id=42,
        current_lat=37.5,
        current_lon=127.0,
        current_name="현재",
        current_drive_sec=0,
        remaining_waypoints=[],
        dest_name="목적지",
        dest_lat=37.6,
        dest_lon=127.1,
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(replan(req, db))

    assert exc.value.status_code == 503
    assert plan_rest_called is False
    db.commit.assert_not_awaited()


def test_basic_propagates_polyline_503(monkeypatch):
    trip = _make_trip()
    db = AsyncMock()
    db.get = AsyncMock(return_value=trip)
    monkeypatch.setattr(pipeline.gh_svc, "get_route_with_stats", _raise_polyline_503)

    req = OptimizeRequest(
        trip_id=1,
        origin_name="출발",
        origin_lat=37.5,
        origin_lon=127.0,
        optimize_mode="basic",
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(pipeline.run_basic_optimize(trip, req, db))

    assert exc.value.status_code == 503
    db.commit.assert_not_awaited()


def test_insert_rest_stops_propagates_polyline_503(monkeypatch):
    monkeypatch.setattr(pipeline.gh_svc, "get_route_with_stats", _raise_polyline_503)

    from app.services.rest_stop_inserter import RouteNode

    ordered = [
        RouteNode(type="origin", name="A", lat=37.5, lon=127.0),
        RouteNode(type="destination", name="B", lat=37.6, lon=127.1),
    ]
    matrix = [[0, 600], [600, 0]]

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            pipeline.insert_rest_stops(ordered, matrix, matrix, []),
        )

    assert exc.value.status_code == 503
