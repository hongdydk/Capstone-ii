"""TMAP API 연동 서비스

주요 기능:
- 두 좌표 사이의 화물차 경로 요청 (소요 시간, 거리, 화물차 통행 제한 반영)
- POI 검색 (휴게소, 졸음쉼터 등)

보안: APP_KEY 는 환경 변수로 관리하며 클라이언트에 노출하지 않습니다.
"""

import logging
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_BASE = settings.TMAP_BASE_URL
_HEADERS = {
    "appKey": settings.TMAP_APP_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# ── 인메모리 캐시 ────────────────────────────────────────────────────────────
# 동일 좌표·차량 제원 조합은 TTL 이내에 API 재호출 없이 캐시를 반환합니다.
# trafficInfo="Y" 를 사용하므로 교통 정보가 변할 수 있어 TTL을 10분으로 제한합니다.
# key: (start_lat, start_lon, end_lat, end_lon, height, weight, length, width)
# value: (result_dict, cached_timestamp)
_route_cache: dict[tuple, tuple[dict[str, Any], float]] = {}
_CACHE_TTL = 600  # 10분 (초)


async def get_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    vehicle_height: float | None = None,
    vehicle_weight: float | None = None,
    vehicle_length: float | None = None,
    vehicle_width: float | None = None,
) -> dict[str, Any]:
    """TMAP 화물차 경로 API를 호출하여 소요 시간(분)과 거리(km)를 반환합니다.
    화물차 통행 제한(중량·높이·길이 제한 도로)을 자동 우회합니다.

    Args:
        vehicle_height: 차량 높이 (m). 예: 4.0
        vehicle_weight: 차량 총 중량 (kg). 예: 25000
        vehicle_length: 차량 길이 (cm). 예: 1600
        vehicle_width:  차량 폭 (cm). 예: 250

    Returns::

        {"duration_min": float, "distance_km": float, "polyline": [...]}
    """
    # ── 캐시 조회 ──────────────────────────────────────────────────────────────
    cache_key = (
        round(start_lat, 5), round(start_lon, 5),
        round(end_lat, 5),   round(end_lon, 5),
        vehicle_height, vehicle_weight, vehicle_length, vehicle_width,
    )
    cached = _route_cache.get(cache_key)
    if cached is not None:
        result, ts = cached
        if time.time() - ts < _CACHE_TTL:
            return result

    payload: dict[str, Any] = {
        "startX": str(start_lon),
        "startY": str(start_lat),
        "endX": str(end_lon),
        "endY": str(end_lat),
        "reqCoordType": "WGS84GEO",
        "resCoordType": "WGS84GEO",
        "searchOption": "17",   # 화물차 최적 경로
        "trafficInfo": "Y",
        "truckType": "1",       # 1: 화물차
    }
    # 차량 제원 — 미입력 시 TMAP 기본값 사용
    if vehicle_height is not None:
        payload["truckHeight"] = int(vehicle_height * 100)      # m → cm
    if vehicle_weight is not None:
        payload["truckWeight"] = int(vehicle_weight)            # kg
        payload["truckTotalWeight"] = int(vehicle_weight)       # kg
    if vehicle_length is not None:
        payload["truckLength"] = int(vehicle_length)            # cm
    if vehicle_width is not None:
        payload["truckWidth"] = int(vehicle_width)              # cm

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_BASE}/tmap/truck/routes",
            headers=_HEADERS,
            json=payload,
        )
        resp.raise_for_status()

    data = resp.json()

    try:
        props = data["features"][0]["properties"]
        duration_min = props["totalTime"] / 60
        distance_km = props["totalDistance"] / 1000
        polyline = []
        for feat in data["features"]:
            if feat["geometry"]["type"] == "LineString":
                polyline.extend(feat["geometry"]["coordinates"])
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("TMAP 화물차 경로 응답 파싱 실패: %s", exc)
        duration_min = 0.0
        distance_km = 0.0
        polyline = []

    # ── 캐시 저장 후 반환 ────────────────────────────────────────────────────────
    result = {"duration_min": duration_min, "distance_km": distance_km, "polyline": polyline}
    _route_cache[cache_key] = (result, time.time())
    return result


async def search_poi(keyword: str, count: int = 10) -> list[dict[str, Any]]:
    """TMAP POI 검색 — 키워드로 휴게소/졸음쉼터를 검색합니다.

    Returns::

        [{"name": str, "lat": float, "lon": float, "address": str}, ...]
    """
    params = {
        "version": "1",
        "searchKeyword": keyword,
        "count": count,
        "resCoordType": "WGS84GEO",
        "reqCoordType": "WGS84GEO",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_BASE}/tmap/pois",
            headers=_HEADERS,
            params=params,
        )
        resp.raise_for_status()

    pois = []
    for item in resp.json().get("searchPoiInfo", {}).get("pois", {}).get("poi", []):
        try:
            pois.append(
                {
                    "name": item["name"],
                    "lat": float(item["noorLat"]),
                    "lon": float(item["noorLon"]),
                    "address": item.get("upperAddrName", "") + " " + item.get("middleAddrName", ""),
                }
            )
        except (KeyError, ValueError):
            continue
    return pois
