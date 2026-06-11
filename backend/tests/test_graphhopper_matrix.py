"""GraphHopper N×N 행렬 fail-fast(H1) 단위 테스트."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException

from app.services import graphhopper as gh


@pytest.fixture(autouse=True)
def _clear_route_cache():
    gh._route_cache.clear()
    yield
    gh._route_cache.clear()


def _origin_dest():
    return (
        {"lat": 37.5, "lon": 127.0},
        {"lat": 37.6, "lon": 127.1},
    )


def _ok_response(time_ms: int = 60_000, distance_m: int = 5_000):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"paths": [{"time": time_ms, "distance": distance_m}]}
    return resp


def test_call_route_raises_503_on_connect_error():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    origin, dest = _origin_dest()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(gh._call_route(client, origin, dest, "truck"))

    assert exc.value.status_code == 503
    assert len(gh._route_cache) == 0


def test_call_route_raises_503_on_http_5xx():
    client = AsyncMock()
    request = httpx.Request("GET", "http://localhost:8989/route")
    response = httpx.Response(503, request=request)
    client.get = AsyncMock(return_value=response)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(gh._call_route(client, *_origin_dest(), "truck"))

    assert exc.value.status_code == 503
    assert len(gh._route_cache) == 0


def test_call_route_raises_503_on_http_4xx():
    client = AsyncMock()
    request = httpx.Request("GET", "http://localhost:8989/route")
    response = httpx.Response(400, request=request)
    client.get = AsyncMock(return_value=response)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(gh._call_route(client, *_origin_dest(), "truck"))

    assert exc.value.status_code == 503
    assert len(gh._route_cache) == 0


def test_call_route_caches_success_only():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_ok_response())

    origin, dest = _origin_dest()
    t1, d1 = asyncio.run(gh._call_route(client, origin, dest, "truck"))
    t2, d2 = asyncio.run(gh._call_route(client, origin, dest, "truck"))

    assert (t1, d1) == (60, 5_000)
    assert (t2, d2) == (t1, d1)
    assert client.get.await_count == 1
    assert len(gh._route_cache) == 1


async def _raise_503(*_args, **_kwargs):
    raise HTTPException(status_code=503, detail=gh._GH_MATRIX_FAILURE_DETAIL)


def test_build_time_matrix_propagates_503(monkeypatch):
    monkeypatch.setattr(gh, "_call_route", _raise_503)

    nodes = [
        {"lat": 37.5, "lon": 127.0},
        {"lat": 37.6, "lon": 127.1},
    ]

    with pytest.raises(HTTPException) as exc:
        asyncio.run(gh.build_time_matrix(nodes, profile="truck"))

    assert exc.value.status_code == 503
