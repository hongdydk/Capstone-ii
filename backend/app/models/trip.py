import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class TripStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Trip(TimestampMixin, Base):
    """하나의 운행 건을 표현합니다.

    관리자가 경유지·목적지·차량 제원을 설정하여 생성합니다.
    기사가 출발 시 본인 현재 위치(origin)를 전달하면 최적 경로가 계산됩니다.
    """

    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), index=True, nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True, nullable=False)

    # 출발지 — 기사가 출발 시점에 전달 (관리자가 알 수 없는 경우가 많음)
    origin_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    origin_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    origin_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 목적지 — 관리자가 설정
    dest_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dest_lat: Mapped[float] = mapped_column(Float, nullable=False)
    dest_lon: Mapped[float] = mapped_column(Float, nullable=False)

    # 경유지 목록 — 관리자가 설정 (JSON 배열: [{"name", "lat", "lon"}, ...])
    waypoints: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # 차량 제원 — 관리자가 설정 (통행 제한 도로 자동 우회에 사용)
    vehicle_height_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vehicle_weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vehicle_length_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vehicle_width_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 출발 예정 시각 (ISO-8601) — 타임머신 예측 교통 API 사용 시 설정
    departure_time: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # 경로 / 상태
    optimized_route: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[TripStatus] = mapped_column(
        Enum(TripStatus, name="tripstatus"), default=TripStatus.SCHEDULED, nullable=False
    )

    # 운행 시간 누적 (초)
    total_driving_seconds: Mapped[int] = mapped_column(Integer, default=0)
    total_rest_seconds: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # 다수 차량 배차 묶음 소속 (VRP 확장용) — NULL = 단건 배차
    dispatch_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("dispatch_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # relationships
    driver: Mapped["Driver"] = relationship("Driver", back_populates="trips")               # noqa: F821
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="trips")            # noqa: F821
    location_logs: Mapped[list["LocationLog"]] = relationship("LocationLog", back_populates="trip")  # noqa: F821
    dispatch_group: Mapped[Optional["DispatchGroup"]] = relationship("DispatchGroup", back_populates="trips")  # noqa: F821
    dispatch_orders: Mapped[list["DispatchOrder"]] = relationship(  # noqa: F821
        "DispatchOrder", foreign_keys="DispatchOrder.assigned_trip_id", back_populates="assigned_trip"
    )
