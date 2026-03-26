"""교차 금지선 / 진입 금지 구역

VRP 경로 최적화 시 특정 구역을 통과하지 못하도록 제약하는 공간 정보.

zone_type:
  - "no_cross"     : 교차 금지선 — 차량 경로가 이 선을 넘지 못함 (예: 민감 구역 경계)
  - "no_entry"     : 진입 금지 구역 — 폴리곤 내부로 경로가 들어가지 못함
  - "time_restrict": 시간대 제한 구역 — restrict_start_hour ~ restrict_end_hour 사이 진입 금지

geometry_json 형식 (GeoJSON):
  - no_cross : LineString   {"type": "LineString", "coordinates": [[lon,lat], ...]}
  - no_entry : Polygon      {"type": "Polygon",    "coordinates": [[[lon,lat], ...]]}
"""

import enum
from typing import Optional

from sqlalchemy import Boolean, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class ZoneType(str, enum.Enum):
    NO_CROSS      = "no_cross"       # 교차 금지선
    NO_ENTRY      = "no_entry"       # 진입 금지 구역
    TIME_RESTRICT = "time_restrict"  # 시간대 제한 구역


class RestrictedZone(TimestampMixin, Base):
    """교차 금지선 / 진입 금지 구역."""

    __tablename__ = "restricted_zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)   # 예: "한강 이남 진입 금지"
    zone_type: Mapped[ZoneType] = mapped_column(
        Enum(ZoneType, name="zonetype"), nullable=False
    )

    # GeoJSON 형태로 저장 (PostGIS 미사용 시 JSONB 대신 Text로 저장)
    # 예: {"type": "Polygon", "coordinates": [[[126.9, 37.5], ...]]}
    geometry_json: Mapped[str] = mapped_column(Text, nullable=False)

    # 시간대 제한 (zone_type = time_restrict 일 때만 사용, 0~23시)
    restrict_start_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    restrict_end_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
