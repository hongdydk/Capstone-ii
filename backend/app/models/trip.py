import enum

from sqlalchemy import Enum as SAEnum, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy import DateTime

from app.core.database import Base


class TripStatus(str, enum.Enum):
    scheduled = "scheduled"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drivers.id"), nullable=False
    )
    vehicle_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vehicles.id"), nullable=False
    )
    origin_name: Mapped[str | None] = mapped_column(String(200))
    origin_lat: Mapped[float | None] = mapped_column(Float)
    origin_lon: Mapped[float | None] = mapped_column(Float)
    dest_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    dest_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    dest_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    waypoints: Mapped[dict | None] = mapped_column(JSONB)
    # 차량 제원 오버라이드 (trip 생성 시 기사/관리자 직접 입력)
    vehicle_height_m: Mapped[float | None] = mapped_column(Float)
    vehicle_weight_kg: Mapped[float | None] = mapped_column(Float)
    vehicle_length_cm: Mapped[float | None] = mapped_column(Float)
    vehicle_width_cm: Mapped[float | None] = mapped_column(Float)
    # ISO-8601 문자열. 있으면 Kakao Future Directions API 사용
    departure_time: Mapped[str | None] = mapped_column(String(50))
    # 계산된 최적 경로 노드 목록 (RouteNode JSON 배열)
    optimized_route: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[TripStatus] = mapped_column(
        SAEnum(TripStatus, name="tripstatus"),
        nullable=False,
        default=TripStatus.scheduled,
    )
    total_driving_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_rest_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dispatch_group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("dispatch_groups.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
