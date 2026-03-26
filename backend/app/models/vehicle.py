from typing import Optional

from sqlalchemy import Boolean, Float, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class Vehicle(TimestampMixin, Base):
    """화물차 차량 정보 — 높이/중량 제약 경로 최적화에 사용됩니다."""

    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    plate_number: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 예: 5톤카고, 15톤탑차
    height_m: Mapped[float] = mapped_column(Float, nullable=False)          # 높이 (m)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)         # 총중량 (kg)
    length_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 길이 (cm)
    width_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # 폭 (cm)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # relationships
    trips: Mapped[list["Trip"]] = relationship("Trip", back_populates="vehicle")  # noqa: F821
