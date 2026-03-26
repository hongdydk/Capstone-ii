"""다수 차량 배차 묶음 모델

배차 지시 1건에 여러 기사/차량을 묶어서 관리합니다.
VRP(Vehicle Routing Problem) 최적화 구현 시 이 테이블을 기준으로 배분 결과를 저장합니다.

미래 구현 예정:
  - dispatch_groups 생성 → dispatch_orders 등록 → VRP 최적화 실행
  - 최적화 결과: 각 order가 trip(기사)에 배정되고 방문 순서 확정
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy import String
from .base import Base, TimestampMixin


class DispatchGroupStatus(str, enum.Enum):
    DRAFT       = "draft"        # 작성 중
    DISPATCHED  = "dispatched"   # 배차 확정 (기사에게 전달됨)
    IN_PROGRESS = "in_progress"  # 운행 중
    COMPLETED   = "completed"    # 전체 완료
    CANCELLED   = "cancelled"    # 취소


class DispatchGroup(TimestampMixin, Base):
    """배차 묶음 — 관리자가 한 번에 여러 기사/차량을 배차하는 단위."""

    __tablename__ = "dispatch_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )  # 배차를 생성한 관리자

    # 출발 거점 센터 — NULL 이면 기사 현재 위치에서 출발
    center_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("centers.id", ondelete="SET NULL"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)  # 예: "2026-03-26 부산행 3대"
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)  # 출발 예정 일시
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)         # 관리자 메모

    status: Mapped[DispatchGroupStatus] = mapped_column(
        Enum(DispatchGroupStatus, name="dispatchgroupstatus"),
        default=DispatchGroupStatus.DRAFT,
        nullable=False,
    )

    # relationships
    orders: Mapped[list["DispatchOrder"]] = relationship(  # noqa: F821
        "DispatchOrder", back_populates="group"
    )
    trips: Mapped[list["Trip"]] = relationship(  # noqa: F821
        "Trip", back_populates="dispatch_group"
    )
    center: Mapped[Optional["Center"]] = relationship(  # noqa: F821
        "Center", back_populates="dispatch_groups"
    )
