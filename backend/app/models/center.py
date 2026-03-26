"""물류 센터 / 거점 정보

출발 거점(창고, 차고지, 본사 등)을 관리합니다.
dispatch_groups.center_id 로 참조되어 VRP 최적화 시 출발점으로 사용됩니다.
rest_stops의 depot 타입과 달리, 운영 정보(담당자, 연락처, 운영 시간)까지 포함합니다.
"""

from typing import Optional

from sqlalchemy import Boolean, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class Center(TimestampMixin, Base):
    """물류 센터 / 출발 거점."""

    __tablename__ = "centers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)       # 예: "인천 물류센터"
    address: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    # 운영 정보
    manager_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    manager_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # relationships
    dispatch_groups: Mapped[list["DispatchGroup"]] = relationship(  # noqa: F821
        "DispatchGroup", back_populates="center"
    )
