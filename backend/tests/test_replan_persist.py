"""replan 성공 시 optimized_route DB 갱신(H4) 테스트."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.optimize import (
    _build_optimized_route_payload,
    _next_route_version,
    replan,
)
from app.services import route_pipeline as pipeline
from app.models.trip import Trip, TripStatus
from app.schemas.optimize import ReplanRequest


def test_next_route_version_starts_at_one():
    assert _next_route_version(None) == 1
    assert _next_route_version({}) == 1


def test_next_route_version_increments():
    assert _next_route_version({"route_version": 2}) == 3


def test_build_optimized_route_payload_includes_route_version():
    payload = _build_optimized_route_payload(
        [{"type": "origin", "name": "A", "lat": 1.0, "lon": 2.0}],
        total_sec=3600,
        rest_count=0,
        existing={"route_version": 1},
    )
    assert payload["route_version"] == 2
    assert payload["estimated_duration_min"] == 60.0
    assert payload["rest_stops_count"] == 0


def test_replan_persists_optimized_route_to_db(monkeypatch):
    trip = Trip(
        id=42,
        driver_id=1,
        vehicle_id=1,
        status=TripStatus.in_progress,
        optimized_route={
            "route": [{"type": "origin", "name": "old", "lat": 0.0, "lon": 0.0}],
            "route_version": 1,
            "estimated_duration_min": 10.0,
            "rest_stops_count": 0,
        },
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=trip)

    matrix = [
        [0, 600, 1200],
        [600, 0, 600],
        [1200, 600, 0],
    ]

    async def _fake_build_time_matrix(nodes, profile="truck"):
        return matrix, matrix

    async def _fake_get_route_with_stats(*args, **kwargs):
        return [[37.5, 127.0], [37.6, 127.1]], 1200, 10_000, None

    async def _fake_plan_rest(nodes, *args, **kwargs):
        return nodes

    rest_result = MagicMock()
    rest_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=rest_result)

    monkeypatch.setattr(pipeline.gh_svc, "build_time_matrix", _fake_build_time_matrix)
    monkeypatch.setattr(pipeline.gh_svc, "get_route_with_stats", _fake_get_route_with_stats)
    monkeypatch.setattr(pipeline.gh_svc, "filter_rest_by_route", lambda c, p: c)
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

    resp = asyncio.run(replan(req, db))

    assert resp.trip_id == 42
    assert trip.optimized_route is not None
    assert trip.optimized_route["route_version"] == 2
    assert len(trip.optimized_route["route"]) >= 2
    db.commit.assert_awaited_once()
