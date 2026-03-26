import enum

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class UserRole(str, enum.Enum):
    ADMIN       = "admin"
    DRIVER      = "driver"
    CONTRACTOR  = "contractor"   # 지입기사 — 본인 Trip 직접 생성 가능, 소속 회사에 위치 공유


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="userrole"), default=UserRole.DRIVER, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # relationships
    driver: Mapped["Driver"] = relationship("Driver", back_populates="user", uselist=False)  # noqa: F821
