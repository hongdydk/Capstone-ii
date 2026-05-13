import asyncio
from math import atan2, cos, radians, sin, sqrt

import httpx
from fastapi import HTTPException

GH_BASE = "http://localhost:8989"

# 경로 탐색 실패 시 대체값 — 사실상 해당 경로를 TSP에서 제외
_UNREACHABLE_SEC = 10_800_000


async def _call_route(
    client: httpx.AsyncClient,
    origin: dict,
    dest: dict,
    profile: str,
) -> tuple[int, int]:
    """GraphHopper /route API 단일 호출 → (시간초, 거리m)."""
    try:
        resp = await client.get(
            f"{GH_BASE}/route",
            params=[
                ("profile", profile),
                ("point", f"{origin['lat']},{origin['lon']}"),
                ("point", f"{dest['lat']},{dest['lon']}"),
                ("points_encoded", "false"),
                ("type", "json"),
            ],
            timeout=30.0,
        )
        resp.raise_for_status()
        path = resp.json()["paths"][0]
        return int(path["time"] / 1000), int(path["distance"])
    except Exception:
        return _UNREACHABLE_SEC, 0


async def build_time_matrix(
    nodes: list[dict],
    profile: str = "truck",
) -> tuple[list[list[int]], list[list[int]]]:
    """N²-N 병렬 호출로 NxN 시간(초)·거리(m) 행렬을 반환합니다."""
    n = len(nodes)
    pairs = [(i, j) for i in range(n) for j in range(n) if i != j]

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[
            _call_route(client, nodes[i], nodes[j], profile)
            for i, j in pairs
        ])

    time_matrix = [[0] * n for _ in range(n)]
    dist_matrix = [[0] * n for _ in range(n)]
    for (i, j), (t, d) in zip(pairs, results):
        time_matrix[i][j] = t
        dist_matrix[i][j] = d

    return time_matrix, dist_matrix


async def get_route_geometry(
    nodes: list[dict],
    profile: str = "truck",
) -> list[list[float]]:
    """노드 순서대로 경유하는 경로의 Leaflet용 [[lat, lon], ...] 좌표를 반환합니다."""
    geo, _, _ = await get_route_with_stats(nodes, profile=profile)
    return geo


async def get_route_with_stats(
    nodes: list[dict],
    profile: str = "truck",
) -> tuple[list[list[float]], int, int]:
    """노드 순서대로 경유하는 경로의 폴리라인·시간(초)·거리(m)를 반환합니다.

    Returns:
        (polyline [[lat,lon],...], time_sec, dist_m)
    """
    params = [("profile", profile), ("points_encoded", "false"), ("type", "json")]
    for node in nodes:
        params.append(("point", f"{node['lat']},{node['lon']}"))

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(f"{GH_BASE}/route", params=params)
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="경로 서버(GraphHopper)에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    if resp.status_code == 400:
        msg = resp.json().get("message", "경로를 찾을 수 없습니다.")
        raise HTTPException(status_code=422, detail=f"GraphHopper: {msg}")
    resp.raise_for_status()

    path = resp.json()["paths"][0]
    polyline = [[c[1], c[0]] for c in path["points"]["coordinates"]]
    time_sec = int(path["time"] / 1000)
    dist_m = int(path["distance"])
    return polyline, time_sec, dist_m


async def find_best_rest_stop(prev, nxt, candidates: list[dict], profile: str = "truck") -> dict | None:
    """GH 실제 도로 시간 기반 최적 휴게소 선택.

    1. Haversine으로 1차 필터 (방향 일치 top-8, 방향 무관 top-4 → 최대 12개)
    2. 12개 후보에 대해 GH 병렬 호출 → (prev→rest) + (rest→nxt) 실제 시간 최소 선택
    """
    from app.services.rest_stop_inserter import (
        _bearing, _angle_diff, _direction_bearing, _haversine_m,
    )

    if not candidates:
        return None

    travel_brg = _bearing(prev.lat, prev.lon, nxt.lat, nxt.lon)

    def _direction_ok(c: dict) -> bool:
        db = _direction_bearing(c.get("direction"))
        return db is None or _angle_diff(travel_brg, db) < 90

    def _is_truck(c: dict) -> bool:
        return c.get("type") == "truck_rest"

    def _haversine_cost(c: dict) -> float:
        return (
            _haversine_m(prev.lat, prev.lon, c["latitude"], c["longitude"])
            + _haversine_m(c["latitude"], c["longitude"], nxt.lat, nxt.lon)
        )

    # 1차: Haversine 우회거리 기준 정렬 후 상위만 추출 (우선순위 고려)
    active = [c for c in candidates if c.get("is_active", True)]
    aligned    = sorted([c for c in active if _direction_ok(c)],    key=_haversine_cost)
    misaligned = sorted([c for c in active if not _direction_ok(c)], key=_haversine_cost)

    # 타입 우선순위 정렬 (truck > highway > drowsy)
    def _type_rank(c: dict) -> int:
        t = c.get("type", "")
        return 0 if t == "truck_rest" else (1 if t == "highway_rest" else 2)

    pool_a = sorted(aligned[:10],    key=_type_rank)[:8]
    pool_m = sorted(misaligned[:6],  key=_type_rank)[:4]
    shortlist = pool_a + pool_m
    if not shortlist:
        return None

    # 2차: GH 병렬 호출로 실제 우회 시간 계산
    async with httpx.AsyncClient(timeout=30.0) as client:
        prev_dict = {"lat": prev.lat, "lon": prev.lon}
        nxt_dict  = {"lat": nxt.lat,  "lon": nxt.lon}

        tasks = [
            asyncio.gather(
                _call_route(client, prev_dict, {"lat": c["latitude"], "lon": c["longitude"]}, profile),
                _call_route(client, {"lat": c["latitude"], "lon": c["longitude"]}, nxt_dict,  profile),
            )
            for c in shortlist
        ]
        results = await asyncio.gather(*tasks)

    best: dict | None = None
    best_cost = float("inf")

    def _type_penalty(c: dict) -> float:
        """truck_rest 최우선 선택을 위한 비용 패널티.
        drowsy_shelter가 도로 시간이 짧아도 truck_rest에 밀리도록 40% 가중."""
        t = c.get("type", "")
        if t == "truck_rest":
            return 1.0
        if t == "highway_rest":
            return 1.15
        return 1.40  # drowsy_shelter

    for c, ((t1, _), (t2, _)) in zip(shortlist, results):
        cost = (t1 + t2) * _type_penalty(c)
        if cost < best_cost:
            best_cost, best = cost, c
    return best


async def get_travel_time(
    origin: dict, dest: dict, profile: str = "truck"
) -> int:
    """두 지점 간 실제 도로 이동시간(초)을 GH API로 반환합니다."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        t, _ = await _call_route(client, origin, dest, profile)
    return t


def filter_rest_by_route(
    rest_candidates: list[dict],
    polyline: list[list[float]],
    max_km: float = 15.0,
    stride: int = 15,
) -> list[dict]:
    """폴리라인 샘플 점으로부터 max_km 이내 휴게소만 반환합니다.

    근처 후보가 없으면 전체 반환(폴백).
    """
    if not polyline or not rest_candidates:
        return rest_candidates

    sampled = polyline[::stride]
    if sampled[-1] != polyline[-1]:
        sampled = sampled + [polyline[-1]]

    R = 6_371.0

    def _near(clat: float, clon: float) -> bool:
        clatR = radians(clat)
        for p in sampled:
            dlat = radians(p[0]) - clatR
            dlon = radians(p[1]) - radians(clon)
            a = sin(dlat / 2) ** 2 + cos(clatR) * cos(radians(p[0])) * sin(dlon / 2) ** 2
            if 2 * R * atan2(sqrt(a), sqrt(1 - a)) <= max_km:
                return True
        return False

    filtered = [c for c in rest_candidates if _near(c["latitude"], c["longitude"])]
    return filtered if filtered else rest_candidates


async def get_route_alternatives(
    nodes: list[dict],
    profile: str = "truck",
    max_paths: int = 3,
) -> list[dict]:
    """대안 경로 목록을 반환합니다.

    - 2노드: GH alternative_route (ch.disable=true) → 최대 max_paths개
    - N노드: TSP 순서 고정이므로 단일 경로만 반환

    Returns: [{"polyline": [[lat,lon],...], "time_sec": int, "dist_m": int}]
    """
    if len(nodes) == 2:
        params = [
            ("profile", profile),
            ("point", f"{nodes[0]['lat']},{nodes[0]['lon']}"),
            ("point", f"{nodes[1]['lat']},{nodes[1]['lon']}"),
            ("algorithm", "alternative_route"),
            ("alternative_route.max_paths", str(max_paths)),
            ("alternative_route.max_weight_factor", "1.4"),
            ("alternative_route.max_share_factor", "0.7"),
            ("ch.disable", "true"),
            ("points_encoded", "false"),
            ("type", "json"),
        ]
    else:
        params = [("profile", profile), ("points_encoded", "false"), ("type", "json")]
        for n in nodes:
            params.append(("point", f"{n['lat']},{n['lon']}"))

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(f"{GH_BASE}/route", params=params)
            resp.raise_for_status()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="경로 서버(GraphHopper)에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    except Exception:
        polyline = await get_route_geometry(nodes, profile)
        return [{"polyline": polyline, "time_sec": 0, "dist_m": 0}]

    paths = resp.json()["paths"]
    results = [
        {
            "polyline": [[c[1], c[0]] for c in path["points"]["coordinates"]],
            "time_sec": int(path["time"] / 1000),
            "dist_m": int(path["distance"]),
        }
        for path in paths
    ]
    # 최적 경로 대비 1.4배 초과하는 대안은 제거 (GH가 비정상 경로를 반환하는 경우 방어)
    if results:
        best_time = results[0]["time_sec"] or 1
        results = [r for r in results if r["time_sec"] <= best_time * 1.45]
    return results if results else [{"polyline": await get_route_geometry(nodes, profile), "time_sec": 0, "dist_m": 0}]
