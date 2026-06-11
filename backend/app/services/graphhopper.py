import asyncio
import logging
from dataclasses import dataclass
from math import atan2, cos, degrees, radians, sin, sqrt

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

GH_BASE = "http://localhost:8989"

_GH_UNAVAILABLE_DETAIL = (
    "경로 서버(GraphHopper)에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."
)
_GH_MATRIX_FAILURE_DETAIL = (
    "GraphHopper 경로 행렬 계산에 실패했습니다. 잠시 후 다시 시도해 주세요."
)

# 구간 (lat,lon) 쌍 캐시 — 휴게소 GH 우회 비용 반복 호출 완화
_route_cache: dict[tuple, tuple[int, int]] = {}
_ROUTE_CACHE_MAX = 4_000


async def _call_route(
    client: httpx.AsyncClient,
    origin: dict,
    dest: dict,
    profile: str,
) -> tuple[int, int]:
    """GraphHopper /route API 단일 호출 → (시간초, 거리m)."""
    key = (
        profile,
        round(origin["lat"], 4),
        round(origin["lon"], 4),
        round(dest["lat"], 4),
        round(dest["lon"], 4),
    )
    if key in _route_cache:
        return _route_cache[key]
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
        result = (int(path["time"] / 1000), int(path["distance"]))
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail=_GH_UNAVAILABLE_DETAIL) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code >= 500:
            raise HTTPException(
                status_code=503,
                detail="경로 서버(GraphHopper) 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
            ) from exc
        raise HTTPException(status_code=503, detail=_GH_MATRIX_FAILURE_DETAIL) from exc
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=_GH_MATRIX_FAILURE_DETAIL) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=_GH_MATRIX_FAILURE_DETAIL) from exc
    if len(_route_cache) < _ROUTE_CACHE_MAX:
        _route_cache[key] = result
    return result


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


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1r, lat2r = radians(lat1), radians(lat2)
    dlonr = radians(lon2 - lon1)
    x = sin(dlonr) * cos(lat2r)
    y = cos(lat1r) * sin(lat2r) - sin(lat1r) * cos(lat2r) * cos(dlonr)
    return (degrees(atan2(x, y)) + 360) % 360


@dataclass(frozen=True)
class _ProfileSegment:
    t_start: float
    t_end: float
    d_start: float
    d_end: float
    start_idx: int
    end_idx: int


@dataclass
class RouteTimeProfile:
    """GH instructions 기반 누적 시간·거리 프로파일."""

    polyline: list[list[float]]
    segments: list[_ProfileSegment]
    total_time_sec: float
    total_dist_m: float

    def dist_at_time(self, t_sec: float) -> float:
        t = max(0.0, min(t_sec, self.total_time_sec))
        for seg in self.segments:
            if t <= seg.t_end or seg is self.segments[-1]:
                dt = seg.t_end - seg.t_start
                if dt <= 0:
                    return seg.d_start
                frac = (t - seg.t_start) / dt
                return seg.d_start + frac * (seg.d_end - seg.d_start)
        return self.total_dist_m

    def time_at_dist(self, dist_m: float) -> float:
        d = max(0.0, min(dist_m, self.total_dist_m))
        for seg in self.segments:
            if d <= seg.d_end or seg is self.segments[-1]:
                dd = seg.d_end - seg.d_start
                if dd <= 0:
                    return seg.t_start
                frac = (d - seg.d_start) / dd
                return seg.t_start + frac * (seg.t_end - seg.t_start)
        return self.total_time_sec

    def point_at_time(self, t_sec: float) -> tuple[float, float, float]:
        t = max(0.0, min(t_sec, self.total_time_sec))
        for seg in self.segments:
            if t <= seg.t_end or seg is self.segments[-1]:
                dt = seg.t_end - seg.t_start
                frac = 0.0 if dt <= 0 else (t - seg.t_start) / dt
                return _point_along_polyline_indices(
                    self.polyline, seg.start_idx, seg.end_idx, max(0.0, min(1.0, frac)),
                )
        return _point_along_polyline_indices(
            self.polyline, 0, len(self.polyline) - 1, 1.0,
        )


def _point_along_polyline_indices(
    polyline: list[list[float]],
    start_idx: int,
    end_idx: int,
    frac: float,
) -> tuple[float, float, float]:
    i0 = max(0, min(start_idx, len(polyline) - 1))
    i1 = max(0, min(end_idx, len(polyline) - 1))
    if i0 > i1:
        i0, i1 = i1, i0
    if i0 == i1 or frac <= 0.0:
        if i0 + 1 < len(polyline):
            brg = _bearing(polyline[i0][0], polyline[i0][1], polyline[i0 + 1][0], polyline[i0 + 1][1])
        elif i0 > 0:
            brg = _bearing(polyline[i0 - 1][0], polyline[i0 - 1][1], polyline[i0][0], polyline[i0][1])
        else:
            brg = 0.0
        return polyline[i0][0], polyline[i0][1], brg
    if frac >= 1.0:
        if i1 > 0:
            brg = _bearing(polyline[i1 - 1][0], polyline[i1 - 1][1], polyline[i1][0], polyline[i1][1])
        elif i1 + 1 < len(polyline):
            brg = _bearing(polyline[i1][0], polyline[i1][1], polyline[i1 + 1][0], polyline[i1 + 1][1])
        else:
            brg = 0.0
        return polyline[i1][0], polyline[i1][1], brg

    sub = polyline[i0 : i1 + 1]
    seg_dists = [
        _haversine_m(sub[i][0], sub[i][1], sub[i + 1][0], sub[i + 1][1])
        for i in range(len(sub) - 1)
    ]
    total_m = sum(seg_dists)
    if total_m <= 0:
        lat = sub[0][0] + frac * (sub[-1][0] - sub[0][0])
        lon = sub[0][1] + frac * (sub[-1][1] - sub[0][1])
        brg = _bearing(sub[0][0], sub[0][1], sub[-1][0], sub[-1][1])
        return lat, lon, brg

    target = frac * total_m
    cum = 0.0
    for i, d in enumerate(seg_dists):
        if cum + d >= target:
            ratio = (target - cum) / d if d > 0 else 0.0
            lat = sub[i][0] + ratio * (sub[i + 1][0] - sub[i][0])
            lon = sub[i][1] + ratio * (sub[i + 1][1] - sub[i][1])
            brg = _bearing(sub[i][0], sub[i][1], sub[i + 1][0], sub[i + 1][1])
            return lat, lon, brg
        cum += d
    brg = _bearing(sub[-2][0], sub[-2][1], sub[-1][0], sub[-1][1])
    return sub[-1][0], sub[-1][1], brg


def build_route_time_profile(
    polyline: list[list[float]],
    instructions: list[dict] | None,
    total_time_sec: int,
    total_dist_m: int,
) -> RouteTimeProfile | None:
    """GH instructions → 누적 시간·거리 프로파일. instructions 없으면 None."""
    if not instructions or len(polyline) < 2:
        return None

    segments: list[_ProfileSegment] = []
    cum_t = 0.0
    cum_d = 0.0
    for ins in instructions:
        t_sec = float(ins.get("time", 0)) / 1000.0
        d_m = float(ins.get("distance", 0))
        interval = ins.get("interval") or [0, 0]
        start_idx = max(0, min(int(interval[0]), len(polyline) - 1))
        end_idx = max(0, min(int(interval[1]), len(polyline) - 1))
        segments.append(_ProfileSegment(
            t_start=cum_t,
            t_end=cum_t + t_sec,
            d_start=cum_d,
            d_end=cum_d + d_m,
            start_idx=start_idx,
            end_idx=end_idx,
        ))
        cum_t += t_sec
        cum_d += d_m

    if not segments:
        return None

    profile = RouteTimeProfile(
        polyline=polyline,
        segments=segments,
        total_time_sec=float(total_time_sec),
        total_dist_m=float(total_dist_m),
    )

    inst_t = segments[-1].t_end
    if inst_t > 0 and total_time_sec > 0 and abs(inst_t - total_time_sec) > max(1.0, total_time_sec * 0.02):
        scale = total_time_sec / inst_t
        scaled: list[_ProfileSegment] = []
        for seg in segments:
            scaled.append(_ProfileSegment(
                t_start=seg.t_start * scale,
                t_end=seg.t_end * scale,
                d_start=seg.d_start,
                d_end=seg.d_end,
                start_idx=seg.start_idx,
                end_idx=seg.end_idx,
            ))
        profile.segments = scaled
        profile.total_time_sec = float(total_time_sec)

    inst_d = segments[-1].d_end
    if inst_d > 0 and total_dist_m > 0 and abs(inst_d - total_dist_m) > max(1.0, total_dist_m * 0.02):
        scale_d = total_dist_m / inst_d
        rescaled: list[_ProfileSegment] = []
        for seg in profile.segments:
            rescaled.append(_ProfileSegment(
                t_start=seg.t_start,
                t_end=seg.t_end,
                d_start=seg.d_start * scale_d,
                d_end=seg.d_end * scale_d,
                start_idx=seg.start_idx,
                end_idx=seg.end_idx,
            ))
        profile.segments = rescaled
        profile.total_dist_m = float(total_dist_m)

    return profile


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
    *,
    with_instructions: bool = False,
) -> tuple[list[list[float]], int, int] | tuple[list[list[float]], int, int, list[dict]]:
    """노드 순서대로 경유하는 경로의 폴리라인·시간(초)·거리(m)를 반환합니다.

    with_instructions=True 이면 GH instructions 목록을 4번째 값으로 반환합니다.

    Returns:
        (polyline [[lat,lon],...], time_sec, dist_m[, instructions])
    """
    params = [("profile", profile), ("points_encoded", "false"), ("type", "json")]
    if with_instructions:
        params.append(("instructions", "true"))
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
    if with_instructions:
        return polyline, time_sec, dist_m, list(path.get("instructions") or [])
    return polyline, time_sec, dist_m


async def find_best_rest_stop(
    prev,
    nxt,
    candidates: list[dict],
    profile: str = "truck",
    *,
    shortlist: list[dict] | None = None,
) -> dict | None:
    """GH 실제 도로 시간 기반 최적 휴게소 선택.

    shortlist 가 주어지면 폴리라인 1차 선별 결과에 대해서만 GH 호출합니다.
    없으면 방향·타입 우선순위로 후보를 축소한 뒤 GH 2차 호출합니다.
    """
    from app.services.rest_stop_inserter import (
        _bearing, _angle_diff, _direction_bearing, _name_bearing,
    )

    if not candidates and not shortlist:
        return None

    travel_brg = _bearing(prev.lat, prev.lon, nxt.lat, nxt.lon)

    def _direction_ok(c: dict) -> bool:
        db = _direction_bearing(c.get("direction"))
        if db is None:
            db = _name_bearing(c.get("name", ""))
        return db is None or _angle_diff(travel_brg, db) < 90

    if shortlist is not None:
        shortlist = [c for c in shortlist if c.get("is_active", True)]
    else:
        active = [c for c in candidates if c.get("is_active", True)]
        aligned = [c for c in active if _direction_ok(c)]
        misaligned = [c for c in active if not _direction_ok(c)]

        def _type_rank(c: dict) -> int:
            t = c.get("type", "")
            return 0 if t == "truck_rest" else (1 if t == "highway_rest" else 2)

        pool_a = sorted(aligned, key=_type_rank)[:8]
        pool_m = sorted(misaligned, key=_type_rank)[:4]
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
