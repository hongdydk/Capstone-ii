"""TMAP API 연동 서비스

주요 기능:
- 두 좌표 사이의 화물차 경로 요청 (소요 시간, 거리, 화물차 통행 제한 반영)
- POI 검색 (휴게소, 졸음쉼터 등)

보안: APP_KEY 는 환경 변수로 관리하며 클라이언트에 노출하지 않습니다.
"""

import json
import logging
from pathlib import Path
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


# ── 지오코딩 영구 캐시 ───────────────────────────────────────────────────────
# 주소 → 좌표 변환 결과를 JSON 파일에 저장합니다.
# 단지·창고 주소는 변하지 않으므로 최초 1회 호출 후 재사용합니다.

_GEOCODE_CACHE_PATH = Path(__file__).resolve().parents[2] / "geocode_cache.json"
_geocode_cache: dict[str, tuple[float, float]] = {}


def _load_geocode_cache() -> None:
    global _geocode_cache
    if _GEOCODE_CACHE_PATH.exists():
        try:
            data = json.loads(_GEOCODE_CACHE_PATH.read_text(encoding="utf-8"))
            _geocode_cache = {k: (float(v[0]), float(v[1])) for k, v in data.items()}
        except Exception:
            _geocode_cache = {}


def _save_geocode_cache() -> None:
    try:
        _GEOCODE_CACHE_PATH.write_text(
            json.dumps(_geocode_cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


_load_geocode_cache()  # 모듈 임포트 시 자동 로드


async def geocode_address(address: str) -> tuple[float, float] | None:
    """주소 → (lat, lon) 변환. 결과를 JSON 파일에 영구 캐싱합니다.

    캐시에 있으면 API 호출 없이 즉시 반환합니다.
    새 주소는 API 호출 후 캐시 파일에 저장합니다.
    """
    if address in _geocode_cache:
        return _geocode_cache[address]

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_BASE}/tmap/geo/fullAddrGeo",
                params={"version": "1", "fullAddr": address,
                        "appKey": settings.TMAP_APP_KEY},
            )
            resp.raise_for_status()
            coords = resp.json().get("coordinateInfo", {}).get("coordinate", [])
            if coords:
                lat = float(coords[0].get("newLat") or coords[0].get("lat") or 0)
                lon = float(coords[0].get("newLon") or coords[0].get("lon") or 0)
                if lat and lon:
                    _geocode_cache[address] = (lat, lon)
                    _save_geocode_cache()
                    return (lat, lon)
    except Exception:
        pass
    return None


# ── 경로 쌍 시간 캐시 (TTL) ─────────────────────────────────────────────────
# TODO: 운영 대상 회사/규모 결정 후 TTL 정책 구현
#
# 고려 사항:
#   - trafficInfo:"Y" 사용 중 → 실시간 교통 반영 → TTL 1시간 권장
#   - 같은 depot 출발 기사들이 많을수록 depot→창고 구간 중복 절약 효과 큼
#   - 단일 서버: in-memory dict (아래 구조)
#   - 멀티 프로세스/서버: Redis (TTL 내장)
#
# 구조 예시 (미구현):
#   _route_cache: dict[tuple, tuple] = {}
#   # key  : (start_lat, start_lon, end_lat, end_lon)
#   # value: (result_dict, expires_timestamp)


async def get_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    vehicle_height: float | None = None,
    vehicle_weight: float | None = None,
    vehicle_length: float | None = None,
    vehicle_width: float | None = None,
    departure_time: str | None = None,
) -> dict[str, Any]:
    """TMAP 화물차 경로 API를 호출하여 소요 시간(분)과 거리(km)를 반환합니다.
    화물차 통행 제한(중량·높이·길이 제한 도로)을 자동 우회합니다.

    Args:
        vehicle_height:  차량 높이 (m). 예: 4.0
        vehicle_weight:  차량 총 중량 (kg). 예: 25000
        vehicle_length:  차량 길이 (cm). 예: 1600
        vehicle_width:   차량 폭 (cm). 예: 250
        departure_time:  출발 예정 시각 (ISO-8601). 예: "2026-03-26T08:00:00+0900"
                         값이 있으면 /tmap/routes/prediction (타임머신 + 화물차)을 사용합니다.
                         None이면 /tmap/truck/routes (실시간 교통)을 사용합니다.

    Returns::

        {"duration_min": float, "distance_km": float, "polyline": [...]}
    """
    if departure_time is not None:
        # ── 타임머신 길안내: 출발 예정 시각 기준 예측 교통 ───────────────────
        # predictionType="arrival": predictionTime에 출발 시각을 넣으면 도착 시각을 예측
        routes_info: dict[str, Any] = {
            "departure": {
                "name": "출발지",
                "lon": str(start_lon),
                "lat": str(start_lat),
            },
            "destination": {
                "name": "도착지",
                "lon": str(end_lon),
                "lat": str(end_lat),
            },
            "predictionType": "arrival",
            "predictionTime": departure_time,
            "searchOption": "17",   # 화물차 최적 경로
        }
        # 차량 제원 — truckType 설정 시 제원 전체 필수
        if vehicle_height is not None or vehicle_weight is not None or vehicle_length is not None or vehicle_width is not None:
            routes_info["truckType"] = 1
            routes_info["truckHeight"] = int(vehicle_height * 100) if vehicle_height is not None else 400
            routes_info["truckWeight"] = int(vehicle_weight) if vehicle_weight is not None else 25000
            routes_info["truckTotalWeight"] = int(vehicle_weight) if vehicle_weight is not None else 30000
            routes_info["truckLength"] = int(vehicle_length) if vehicle_length is not None else 880
            routes_info["truckWidth"] = int(vehicle_width) if vehicle_width is not None else 250

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_BASE}/tmap/routes/prediction",
                headers=_HEADERS,
                params={"version": "1", "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO"},
                json={"routesInfo": routes_info},
            )
            resp.raise_for_status()
    else:
        # ── 실시간 교통 길안내: 현재 교통 기준 ───────────────────────────────
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

    return {"duration_min": duration_min, "distance_km": distance_km, "polyline": polyline}


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
