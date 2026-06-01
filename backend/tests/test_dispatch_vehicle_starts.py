"""POST /optimize/dispatch — 분산 출발(vehicle_starts) 모드 테스트."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.optimize import dispatch_multi
from app.schemas.optimize import DispatchRequest


def _uniform_matrix(n: int, off: int = 100) -> list[list[int]]:
    return [[0 if i == j else off for j in range(n)] for i in range(n)]


async def _fake_build_time_matrix(all_geo, profile="truck"):
    n = len(all_geo)
    m = _uniform_matrix(n)
    return m, m


async def _fake_get_route_with_stats(geo_nodes, profile="truck"):
    polyline = [[g["lat"], g["lon"]] for g in geo_nodes]
    return polyline, len(geo_nodes) * 100, len(geo_nodes) * 1000


async def _fake_plan_rest(ordered, polyline, route_time_sec, nearby, **kwargs):
    return ordered


class _FakeScalars:
    def all(self):
        return []


class _FakeResult:
    def scalars(self):
        return _FakeScalars()


class _FakeSession:
    async def execute(self, query):
        return _FakeResult()


@pytest.fixture
def gh_patches():
    with (
        patch(
            "app.api.optimize.gh_svc.build_time_matrix",
            new=AsyncMock(side_effect=_fake_build_time_matrix),
        ),
        patch(
            "app.api.optimize.gh_svc.get_route_with_stats",
            new=AsyncMock(side_effect=_fake_get_route_with_stats),
        ),
        patch(
            "app.api.optimize.plan_rest_stops_from_polyline_async",
            new=AsyncMock(side_effect=_fake_plan_rest),
        ),
        patch("app.api.optimize.gh_svc.filter_rest_by_route", return_value=[]),
    ):
        yield


def _vehicle_starts_payload():
    """3 vehicles, 5 stops, no depot."""
    return {
        "vehicles": [
            {
                "name": "truck-A",
                "start_name": "기사A",
                "start_lat": 37.50,
                "start_lon": 127.00,
                "end_policy": "open_end",
            },
            {
                "name": "truck-B",
                "start_lat": 37.55,
                "start_lon": 127.05,
                "end_policy": "open_end",
            },
            {
                "name": "truck-C",
                "start_lat": 37.60,
                "start_lon": 127.10,
                "end_policy": "open_end",
            },
        ],
        "nodes": [
            {"name": f"stop-{i}", "lat": 37.51 + i * 0.01, "lon": 127.01 + i * 0.01}
            for i in range(5)
        ],
        "time_limit_seconds": 5,
    }


class TestDispatchVehicleStarts:
    def test_missing_depot_and_partial_starts_returns_400(self, gh_patches):
        payload = _vehicle_starts_payload()
        payload["vehicles"][2].pop("start_lat")
        payload["vehicles"][2].pop("start_lon")
        req = DispatchRequest.model_validate(payload)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(dispatch_multi(req, db=_FakeSession()))
        assert exc_info.value.status_code == 400

    def test_vehicle_starts_open_end_origin_and_no_depot_dest(self, gh_patches):
        req = DispatchRequest.model_validate(_vehicle_starts_payload())
        resp = asyncio.run(dispatch_multi(req, db=_FakeSession()))
        assert len(resp.routes) >= 1

        vehicle_starts = [(37.50, 127.00), (37.55, 127.05), (37.60, 127.10)]
        for vr in resp.routes:
            route = vr.route
            assert route[0].type == "origin"
            assert any(
                route[0].lat == pytest.approx(lat) and route[0].lon == pytest.approx(lon)
                for lat, lon in vehicle_starts
            )

            dest_nodes = [n for n in route if n.type == "destination"]
            assert len(dest_nodes) == 1
            assert dest_nodes[0].name != "depot"
            assert all(n.name != "depot" for n in route)
            assert route[-1].type == "destination"
            assert route[-1].name == dest_nodes[0].name

    def test_depot_centered_legacy_unchanged(self, gh_patches):
        req = DispatchRequest.model_validate(
            {
                "depot_name": "warehouse",
                "depot_lat": 37.0,
                "depot_lon": 127.0,
                "vehicles": [{"name": "truck-1"}, {"name": "truck-2"}],
                "nodes": [
                    {"name": "a", "lat": 37.1, "lon": 127.1},
                    {"name": "b", "lat": 37.2, "lon": 127.2},
                ],
                "time_limit_seconds": 5,
            }
        )
        resp = asyncio.run(dispatch_multi(req, db=_FakeSession()))
        route = resp.routes[0].route
        assert route[0].type == "origin"
        assert route[0].name == "warehouse"
        assert route[-1].type == "destination"
        assert route[-1].name == "warehouse"
