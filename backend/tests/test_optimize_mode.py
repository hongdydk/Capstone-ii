"""POST /optimize/ · /optimize/basic · /optimize/with-rest 파이프라인 테스트."""

import asyncio

import os

from pathlib import Path

from unittest.mock import AsyncMock, MagicMock, patch



import pytest



os.environ.setdefault(

    "DATABASE_URL",

    "postgresql+asyncpg://routeon:routeon@localhost:5432/routeon",

)

_env_patch = patch("app.core.config._ENV_FILE", Path("/nonexistent/.env"))

_env_patch.start()



from app.api import optimize as optimize_api  # noqa: E402

from app.api.optimize import (  # noqa: E402

    optimize,

    optimize_basic,

    optimize_with_rest,

)

from app.models.trip import Trip, TripStatus  # noqa: E402

from app.schemas.optimize import OptimizeRequest  # noqa: E402

from app.services import route_pipeline as pipeline  # noqa: E402

from app.services.rest_stop_inserter import RouteNode  # noqa: E402





def _make_trip(**kwargs) -> Trip:

    defaults = dict(

        id=1,

        driver_id=1,

        vehicle_id=1,

        status=TripStatus.scheduled,

        dest_name="목적지",

        dest_lat=37.6,

        dest_lon=127.1,

        waypoints=[

            {"name": "경유1", "lat": 37.55, "lon": 127.05},

            {"name": "경유2", "lat": 37.57, "lon": 127.07},

        ],

    )

    defaults.update(kwargs)

    return Trip(**defaults)





def _patch_gh(monkeypatch, matrix=None):

    if matrix is None:

        matrix = [

            [0, 300, 600, 900],

            [300, 0, 300, 600],

            [600, 300, 0, 300],

            [900, 600, 300, 0],

        ]



    async def _fake_build_time_matrix(nodes, profile="truck"):

        return matrix, matrix



    monkeypatch.setattr(pipeline.gh_svc, "build_time_matrix", _fake_build_time_matrix)





def test_optimize_request_default_mode_is_with_rest():

    req = OptimizeRequest(

        trip_id=1,

        origin_name="출발",

        origin_lat=37.5,

        origin_lon=127.0,

    )

    assert req.optimize_mode == "with_rest"





@pytest.mark.parametrize("handler", [optimize, optimize_basic])

def test_basic_skips_rest_insertion(handler, monkeypatch):

    trip = _make_trip()

    db = AsyncMock()

    db.get = AsyncMock(return_value=trip)

    _patch_gh(monkeypatch)



    plan_rest_called = False



    async def _fake_plan_rest(*args, **kwargs):

        nonlocal plan_rest_called

        plan_rest_called = True

        return args[0]



    monkeypatch.setattr(

        pipeline, "plan_rest_stops_from_polyline_async", _fake_plan_rest,

    )



    req = OptimizeRequest(

        trip_id=1,

        origin_name="출발",

        origin_lat=37.5,

        origin_lon=127.0,

        optimize_mode="basic" if handler is optimize else "with_rest",

    )

    resp = asyncio.run(handler(req, db))



    assert plan_rest_called is False

    assert resp.rest_stops_count == 0

    assert all(n.type != "rest_stop" for n in resp.route)

    waypoint_names = [n.name for n in resp.route if n.type == "waypoint"]

    assert waypoint_names == ["경유1", "경유2"]





@pytest.mark.parametrize("handler", [optimize, optimize_with_rest])

def test_with_rest_calls_rest_insertion(handler, monkeypatch):

    trip = _make_trip()

    db = AsyncMock()

    db.get = AsyncMock(return_value=trip)

    _patch_gh(monkeypatch)



    async def _fake_get_route_with_stats(*args, **kwargs):

        return [[37.5, 127.0], [37.6, 127.1]], 900, 5000, None



    rest_result = MagicMock()

    rest_result.scalars.return_value.all.return_value = []

    db.execute = AsyncMock(return_value=rest_result)



    plan_rest_called = False



    async def _fake_plan_rest(nodes, *args, **kwargs):

        nonlocal plan_rest_called

        plan_rest_called = True

        rest = RouteNode(

            type="rest_stop",

            name="테스트휴게소",

            lat=37.55,

            lon=127.05,

            min_rest_minutes=30,

        )

        return [nodes[0], rest] + nodes[1:]



    monkeypatch.setattr(pipeline.gh_svc, "get_route_with_stats", _fake_get_route_with_stats)

    monkeypatch.setattr(pipeline.gh_svc, "filter_rest_by_route", lambda c, p: c)

    monkeypatch.setattr(

        pipeline, "plan_rest_stops_from_polyline_async", _fake_plan_rest,

    )



    req = OptimizeRequest(

        trip_id=1,

        origin_name="출발",

        origin_lat=37.5,

        origin_lon=127.0,

        optimize_mode="basic" if handler is optimize_with_rest else "with_rest",

    )

    resp = asyncio.run(handler(req, db))



    assert plan_rest_called is True

    assert resp.rest_stops_count == 1

    assert any(n.type == "rest_stop" for n in resp.route)





def test_optimize_root_delegates_basic_mode(monkeypatch):

    trip = _make_trip()

    db = AsyncMock()

    db.get = AsyncMock(return_value=trip)



    basic_called = False

    with_rest_called = False



    async def _fake_basic(t, r, d):

        nonlocal basic_called

        basic_called = True

        from app.schemas.optimize import OptimizeResponse, RouteNodeSchema

        return OptimizeResponse(

            trip_id=1,

            route=[RouteNodeSchema(type="origin", name="출발", lat=37.5, lon=127.0)],

            total_distance_km=1.0,

            estimated_duration_min=1.0,

            rest_stops_count=0,

        )



    async def _fake_with_rest(t, r, d):

        nonlocal with_rest_called

        with_rest_called = True

        raise AssertionError("with_rest should not be called")



    monkeypatch.setattr(optimize_api, "run_basic_optimize", _fake_basic)

    monkeypatch.setattr(optimize_api, "run_with_rest_optimize", _fake_with_rest)



    req = OptimizeRequest(

        trip_id=1,

        origin_name="출발",

        origin_lat=37.5,

        origin_lon=127.0,

        optimize_mode="basic",

    )

    asyncio.run(optimize(req, db))

    assert basic_called is True

    assert with_rest_called is False


