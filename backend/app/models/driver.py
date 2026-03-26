from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class Driver(TimestampMixin, Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    license_number: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)

    # 소속 회사 (지입기사 전용) — admin 유저의 id를 참조
    # NULL = 일반 소속 기사, NOT NULL = 지입기사(위치 공유 대상 회사 지정)
    company_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, default=None, index=True
    )

    # relationships
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], back_populates="driver")  # noqa: F821
    trips: Mapped[list["Trip"]] = relationship("Trip", back_populates="driver")  # noqa: F821
