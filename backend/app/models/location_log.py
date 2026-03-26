import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Enum, Float, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class DrivingState(str, enum.Enum):
    DRIVING      = "driving"
    RESTING      = "resting"
    TRAFFIC_STOP = "traffic_stop"
    UNKNOWN      = "unknown"


class LocationLog(TimestampMixin, Base):
    """운행 중 위치 로그 — GPS 좌표, 속도, 운전 상태를 시계열로 기록합니다."""

    __tablename__ = "location_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(
        ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    speed_kmh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    state: Mapped[DrivingState] = mapped_column(
        Enum(DrivingState, name="drivingstate"), default=DrivingState.UNKNOWN, nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    # relationships
    trip: Mapped["Trip"] = relationship("Trip", back_populates="location_logs")  # noqa: F821
