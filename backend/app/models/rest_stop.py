import enum

from sqlalchemy import Boolean, Enum, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class RestStopType(str, enum.Enum):
    HIGHWAY_REST = "highway_rest"    # 고속도로 휴게소
    DROWSY_SHELTER = "drowsy_shelter"  # 졸음쉼터
    DEPOT = "depot"                  # 차고지


class RestStop(TimestampMixin, Base):
    """휴식 판정에 사용되는 POI 목록 (휴게소, 졸음쉼터, 차고지)."""

    __tablename__ = "rest_stops"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[RestStopType] = mapped_column(
        Enum(RestStopType, name="reststoptype"), nullable=False
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 노선 방향: '상행' / '하행' / None(양방향 또는 미분류)
    direction: Mapped[str | None] = mapped_column(String(10), nullable=True, default=None)
