"""배송 주문 건 모델 (dispatch_groups에 소속)

배차 묶음 내 개별 배송 주문입니다.
VRP 최적화 실행 후 assigned_trip_id / visit_order 가 채워집니다.
"""

import enum
from typing import Optional

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class DispatchOrderStatus(str, enum.Enum):
    PENDING   = "pending"    # 배정 대기
    ASSIGNED  = "assigned"   # 기사에게 배정 완료
    DELIVERED = "delivered"  # 배송 완료
    CANCELLED = "cancelled"  # 취소


class DispatchOrder(TimestampMixin, Base):
    """배차 묶음 내 개별 배송 주문.

    상차지(pickup)는 선택적입니다. 하차지(dest)는 필수.
    VRP 최적화 결과는 assigned_trip_id + visit_order 에 저장됩니다.
    """

    __tablename__ = "dispatch_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("dispatch_groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # 상차지 (선택) — NULL이면 trip.origin 에서 바로 하차지로 출발
    pickup_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    pickup_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pickup_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 하차지 (필수)
    dest_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dest_lat: Mapped[float] = mapped_column(Float, nullable=False)
    dest_lon: Mapped[float] = mapped_column(Float, nullable=False)

    # 화물 정보 (경로 제약 계산에 활용 예정)
    cargo_desc: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    cargo_weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 배송지 마스터 참조 (반복 거래처) — NULL이면 dest_* 직접 입력
    delivery_point_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("delivery_points.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # VRP 최적화 결과 — 미배정 시 NULL
    assigned_trip_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("trips.id", ondelete="SET NULL"), nullable=True, index=True
    )
    visit_order: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # 해당 trip 내 방문 순서 (1-based)

    status: Mapped[DispatchOrderStatus] = mapped_column(
        Enum(DispatchOrderStatus, name="dispatchorderstatus"),
        default=DispatchOrderStatus.PENDING,
        nullable=False,
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── 이번 건 시간 제약 (VRPTW) ───────────────────────────────────────────
    # delivery_point 기본값보다 우선 적용됨. NULL이면 delivery_point 기본값 사용.
    deadline: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # 절대 마감 시각 ISO-8601 (예: "2026-03-26T17:00:00+09:00")
    # VRP에서 이 시각을 넘기면 해당 주문은 미배송 페널티 부여

    tw_open:  Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # 도착 가능 시작 시각 ISO-8601 (예: "2026-03-26T09:00:00+09:00")
    # NULL이면 delivery_point.tw_open 적용

    tw_close: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # 도착 마감 시각 ISO-8601 (예: "2026-03-26T17:00:00+09:00")
    # NULL이면 delivery_point.tw_close 적용

    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 배송 우선순위 (0=보통, 1=높음, 2=긴급)
    # VRP 최적화 시 높은 우선순위 주문은 먼저 배정되도록 가중치 부여

    # relationships
    group: Mapped["DispatchGroup"] = relationship(  # noqa: F821
        "DispatchGroup", back_populates="orders"
    )
    assigned_trip: Mapped[Optional["Trip"]] = relationship(  # noqa: F821
        "Trip", foreign_keys=[assigned_trip_id], back_populates="dispatch_orders"
    )
    delivery_point: Mapped[Optional["DeliveryPoint"]] = relationship(  # noqa: F821
        "DeliveryPoint", back_populates="dispatch_orders"
    )
