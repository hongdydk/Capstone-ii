"""OD truck statistics helpers (영업용화물 운행기록계 표 22–26).

Ton bins (demo / pseudonymization, not legal DTG classification):
  - small:  tons < 3.5
  - medium: 3.5 <= tons < 8
  - large:  tons >= 8
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Literal

TonClass = Literal["small", "medium", "large"]

ROOT = Path(__file__).resolve().parents[1]
STATS_DIR = ROOT / "data" / "source" / "od_truck_stats"

SMALL_MAX_TON = 3.5
MEDIUM_MAX_TON = 8.0
ROAD_FACTOR = 1.3
TASK_KM_DAILY_SHARE = 0.4
TASK_HASH_SPREAD = 0.10

# Short region keys used in JSON tables
REGION_PREFIXES: list[tuple[str, str]] = [
    ("서울", "서울"),
    ("부산", "부산"),
    ("대구", "대구"),
    ("인천", "인천"),
    ("광주", "광주"),
    ("대전", "대전"),
    ("울산", "울산"),
    ("세종", "세종"),
    ("경기", "경기"),
    ("강원", "강원"),
    ("충청북도", "충북"),
    ("충북", "충북"),
    ("충청남도", "충남"),
    ("충남", "충남"),
    ("전라북도", "전북"),
    ("전북특별자치도", "전북"),
    ("전북", "전북"),
    ("전라남도", "전남"),
    ("전남", "전남"),
    ("경상북도", "경북"),
    ("경북", "경북"),
    ("경상남도", "경남"),
    ("경남", "경남"),
    ("제주", "제주"),
]

# Approximate province centroids (deg) for pseudonymized straight-line legs
REGION_CENTROIDS: dict[str, tuple[float, float]] = {
    "서울": (37.5665, 126.9780),
    "부산": (35.1796, 129.0756),
    "대구": (35.8714, 128.6014),
    "인천": (37.4563, 126.7052),
    "광주": (35.1595, 126.8526),
    "대전": (36.3504, 127.3845),
    "울산": (35.5384, 129.3114),
    "세종": (36.4800, 127.2890),
    "경기": (37.4138, 127.5183),
    "강원": (37.8228, 128.1555),
    "충북": (36.8000, 127.7000),
    "충남": (36.5184, 126.8000),
    "전북": (35.7175, 127.1530),
    "전남": (34.8679, 126.9910),
    "경북": (36.4919, 128.8889),
    "경남": (35.4606, 128.2132),
    "제주": (33.4890, 126.4983),
}

_cached_table26: dict | None = None
_cached_table24: dict | None = None


def _load(name: str) -> dict:
    path = STATS_DIR / name
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _get_table26() -> dict:
    global _cached_table26
    if _cached_table26 is None:
        _cached_table26 = _load("table26_daily_distance_km.json")
    return _cached_table26


def _get_table24() -> dict:
    global _cached_table24
    if _cached_table24 is None:
        _cached_table24 = _load("table24_daily_trips.json")
    return _cached_table24


def ton_to_class(tons: float) -> TonClass:
    if tons < SMALL_MAX_TON:
        return "small"
    if tons < MEDIUM_MAX_TON:
        return "medium"
    return "large"


def address_to_region(addr: str) -> str:
    """Map Korean address to short region key (서울, 경기, …)."""
    text = (addr or "").strip()
    if not text:
        return "전국"
    for prefix, key in REGION_PREFIXES:
        if text.startswith(prefix):
            return key
    return "전국"


def _lookup(table: dict, region: str, ton_class: TonClass) -> float:
    regions = table.get("regions", {})
    row = regions.get(region) or table.get("national", {})
    return float(row.get(ton_class, row.get("total", 0.0)))


def lookup_daily_km(region: str, ton_class: TonClass) -> float:
    return _lookup(_get_table26(), region, ton_class)


def lookup_daily_trips(region: str, ton_class: TonClass) -> float:
    return _lookup(_get_table24(), region, ton_class)


def task_variation_factor(task_id: int) -> float:
    """Deterministic ±10% from task_id (stable across regenerations)."""
    digest = hashlib.sha256(f"routeon-task-{task_id}".encode()).hexdigest()
    slot = int(digest[:8], 16) / 0xFFFFFFFF
    return 1.0 + (slot * 2.0 - 1.0) * TASK_HASH_SPREAD


def address_to_fake_latlon(addr: str) -> tuple[float, float]:
    """Stable pseudo-coordinates from region centroid + address hash jitter."""
    region = address_to_region(addr)
    base_lat, base_lon = REGION_CENTROIDS.get(region, (36.5, 127.5))
    h = hashlib.sha256(addr.encode("utf-8")).hexdigest()
    dlat = (int(h[0:8], 16) / 0xFFFFFFFF - 0.5) * 0.45
    dlon = (int(h[8:16], 16) / 0xFFFFFFFF - 0.5) * 0.55
    return base_lat + dlat, base_lon + dlon


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def leg_haversine_km(addr_a: str, addr_b: str) -> float:
    lat1, lon1 = address_to_fake_latlon(addr_a)
    lat2, lon2 = address_to_fake_latlon(addr_b)
    return haversine_km(lat1, lon1, lat2, lon2)


def estimate_task_distance_km(
    task_id: int,
    region: str,
    ton_class: TonClass,
    route_addresses: list[str],
) -> tuple[float, float, list[float]]:
    """
    Returns (estimated_task_distance_km, haversine_sum_km, per_leg_haversine_km[]).

    Caps road-ish distance at od_daily_km * TASK_KM_DAILY_SHARE with hash variation.
    """
    legs: list[float] = []
    addrs = route_addresses
    for i in range(len(addrs) - 1):
        legs.append(round(leg_haversine_km(addrs[i], addrs[i + 1]), 2))

    haversine_sum = round(sum(legs), 2)
    road_estimate = haversine_sum * ROAD_FACTOR
    benchmark = lookup_daily_km(region, ton_class) * task_variation_factor(task_id)
    cap = benchmark * TASK_KM_DAILY_SHARE
    estimated = round(min(road_estimate, cap) if road_estimate > 0 else cap * 0.5, 1)
    return estimated, haversine_sum, legs
