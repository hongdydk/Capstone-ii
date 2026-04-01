import asyncio
from datetime import datetime
from typing import Literal

import httpx

from app.core.config import settings

KAKAO_BASE = "https://apis-navi.kakaomobility.com/v1"

# 경로 탐색 실패 시 대체값 — 사실상 해당 경로를 TSP에서 제외
_UNREACHABLE_SEC = 10_800_000

# 다중 목적지 API 탐색 반경 (최대 10,000m) — 지역 배송 모드에서 사용
_LOCAL_RADIUS_M = 10_000


async def _get_route_time_future(
    client: httpx.AsyncClient,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    *,
    departure_time: str,
) -> int:
    """미래 운행 정보 길찾기 API로 두 지점 간 소요 시간(초)을 반환합니다."""
    headers = {
        "Authorization": f"KakaoAK {settings.KAKAO_API_KEY}",
        "Content-Type": "application/json",
    }
    # departure_time 형식: ISO-8601 → YYYYMMDDHHMM (12자리, API 스펙)
    try:
        dt = datetime.fromisoformat(departure_time)
        dt_str = dt.strftime("%Y%m%d%H%M")
    except ValueError:
        dt_str = departure_time[:12]  # 이미 올바른 포맷이면 앞 12자리만 사용

    resp = await client.get(
        f"{KAKAO_BASE}/future/directions",
        params={
            "origin": f"{origin_lon},{origin_lat}",
            "destination": f"{dest_lon},{dest_lat}",
            "departure_time": dt_str,
            "summary": "true",
        },
        headers=headers,
    )
    resp.raise_for_status()
    return int(resp.json()["routes"][0]["summary"]["duration"])


async def _get_route_time_realtime(
    client: httpx.AsyncClient,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
) -> int:
    """자동차 길찾기 API로 두 지점 간 실시간 소요 시간(초)을 반환합니다."""
    headers = {
        "Authorization": f"KakaoAK {settings.KAKAO_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = await client.get(
        f"{KAKAO_BASE}/directions",
        params={
            "origin": f"{origin_lon},{origin_lat}",
            "destination": f"{dest_lon},{dest_lat}",
            "summary": "true",
        },
        headers=headers,
    )
    resp.raise_for_status()
    return int(resp.json()["routes"][0]["summary"]["duration"])


async def _get_row_times_multi_dest(
    client: httpx.AsyncClient,
    origin: dict,
    destinations: list[dict],
    dest_indices: list[int],
) -> list[tuple[int, int]]:
    """다중 목적지 길찾기 API로 출발지 → 여러 목적지 소요 시간(초)을 일괄 조회합니다.
    반환값: [(dest_index, duration_sec), ...]
    """
    headers = {
        "Authorization": f"KakaoAK {settings.KAKAO_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "origin": {"x": str(origin["lon"]), "y": str(origin["lat"])},
        "destinations": [
            {"x": str(d["lon"]), "y": str(d["lat"]), "key": str(idx)}
            for idx, d in zip(dest_indices, destinations)
        ],
        "radius": _LOCAL_RADIUS_M,
        "priority": "TIME",
    }
    resp = await client.post(
        f"{KAKAO_BASE}/destinations/directions",
        json=body,
        headers=headers,
    )
    resp.raise_for_status()

    results: list[tuple[int, int]] = []
    for route in resp.json()["routes"]:
        j = int(route["key"])
        if route.get("result_code", -1) == 0:
            results.append((j, int(route["summary"]["duration"])))
        else:
            results.append((j, _UNREACHABLE_SEC))
    return results


async def build_time_matrix(
    nodes: list[dict],
    *,
    route_mode: Literal["local", "long_distance"] = "long_distance",
    departure_time: str | None = None,
    # Kakao는 차량 제원 파라미터를 지원하지 않으므로 서명 호환용으로만 유지
    height_m: float | None = None,
    weight_kg: float | None = None,
    length_cm: float | None = None,
    width_cm: float | None = None,
) -> list[list[int]]:
    """N개 노드 리스트로 N×N 시간 행렬(초)을 계산합니다.

    route_mode:
      - "local"         : 지역 배송 — 다중 목적지 API (N회 호출, 반경 10km 이내)
      - "long_distance" : 장거리 화물 — 자동차 길찾기 API 개별 호출 (N²-N회)

    departure_time 있으면 두 모드 모두 미래 운행 정보 API로 전환 (다중 목적지 API가 미지원)
    """
    n = len(nodes)
    matrix: list[list[int]] = [[0] * n for _ in range(n)]

    async with httpx.AsyncClient(timeout=15.0) as client:
        if departure_time:
            # 미래 교통 반영 — 두 모드 공통으로 개별 호출 (N²-N 회)
            # 다중 목적지 API는 departure_time 미지원
            async def fetch_future(i: int, j: int) -> tuple[int, int, int]:
                secs = await _get_route_time_future(
                    client,
                    nodes[i]["lat"], nodes[i]["lon"],
                    nodes[j]["lat"], nodes[j]["lon"],
                    departure_time=departure_time,
                )
                return i, j, secs

            tasks = [fetch_future(i, j) for i in range(n) for j in range(n) if i != j]
            for i, j, val in await asyncio.gather(*tasks):
                matrix[i][j] = val

        elif route_mode == "local":
            # 지역 배송 — 다중 목적지 API로 행(row) 단위 일괄 조회 (N회 호출)
            # 반경 10km 이내 노드에 한해 적용
            async def fetch_row(i: int) -> tuple[int, list[tuple[int, int]]]:
                dest_indices = [j for j in range(n) if j != i]
                dest_nodes = [nodes[j] for j in dest_indices]
                row_results = await _get_row_times_multi_dest(
                    client, nodes[i], dest_nodes, dest_indices
                )
                return i, row_results

            rows = await asyncio.gather(*[fetch_row(i) for i in range(n)])
            for i, row_results in rows:
                for j, val in row_results:
                    matrix[i][j] = val

        else:
            # 장거리 화물 — 자동차 길찾기 API 개별 호출 (N²-N 회, 거리 제한 없음)
            async def fetch_long(i: int, j: int) -> tuple[int, int, int]:
                secs = await _get_route_time_realtime(
                    client,
                    nodes[i]["lat"], nodes[i]["lon"],
                    nodes[j]["lat"], nodes[j]["lon"],
                )
                return i, j, secs

            tasks = [fetch_long(i, j) for i in range(n) for j in range(n) if i != j]
            for i, j, val in await asyncio.gather(*tasks):
                matrix[i][j] = val

    return matrix
