"""Kakao 좌표 변환(지오코딩) 유틸리티.

라우팅·시간 행렬 API는 GraphHopper로 대체됨. 이 모듈은 주소/키워드 → 좌표 변환만 담당합니다.
"""
from __future__ import annotations

import httpx

from app.core.config import settings

_KAKAO_LOCAL_KEYWORD = "https://dapi.kakao.com/v2/local/search/keyword.json"
_KAKAO_LOCAL_ADDRESS = "https://dapi.kakao.com/v2/local/search/address.json"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"KakaoAK {settings.KAKAO_API_KEY}"}


async def search_keyword(query: str, *, size: int = 8) -> list[dict]:
    """Kakao 로컬 키워드 검색 → 좌표 목록.

    Returns:
        [{"name", "address", "lat", "lon"}, ...]
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            _KAKAO_LOCAL_KEYWORD,
            params={"query": query, "size": size},
            headers=_auth_headers(),
        )
    resp.raise_for_status()
    docs = resp.json().get("documents", [])
    results: list[dict] = []
    for d in docs:
        if not d.get("x") or not d.get("y"):
            continue
        results.append({
            "name": d.get("place_name", ""),
            "address": d.get("road_address_name") or d.get("address_name", ""),
            "lat": float(d["y"]),
            "lon": float(d["x"]),
        })
    return results


async def geocode_address(address: str) -> tuple[float, float] | None:
    """Kakao 주소 검색 API로 (lat, lon) 반환. 실패 시 None."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            _KAKAO_LOCAL_ADDRESS,
            params={"query": address},
            headers=_auth_headers(),
        )
    if resp.status_code != 200:
        return None
    docs = resp.json().get("documents", [])
    if not docs:
        return None
    doc = docs[0]
    if not doc.get("x") or not doc.get("y"):
        return None
    return float(doc["y"]), float(doc["x"])
