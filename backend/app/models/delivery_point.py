"""배송지(거래처) 마스터

반복적으로 배송하는 거래처 / 하차지를 등록해두는 마스터 테이블.
dispatch_orders 작성 시 delivery_point_id 로 참조하면 좌표 및 시간창을 자동으로 가져올 수 있습니다.

배송지 유형(delivery_type):
  recurring  : 반복 거래처 — 영구 마스터. 자동완성·통계 등에 계속 활용.
  one_time   : 단발 거래처 — 이번 배차에만 사용. 배차 완료 후 is_active=False 처리 가능.
  (미등록)   : dispatch_orders.delivery_point_id=NULL + dest_* 직접 입력. 완전 즉흥 배송.

시간창(Time Window) 우선순위:
  dispatch_orders.tw_open / tw_close  >  delivery_points.tw_open / tw_close  >  제약 없음
"""

import enum
from typing import Optional

from sqlalchemy import Boolean, Enum, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class DeliveryType(str, enum.Enum):
    RECURRING = "recurring"   # 반복 거래처 (영구 마스터)
    ONE_TIME  = "one_time"    # 단발 거래처 (배차 완료 후 정리 가능)


class DeliveryPoint(TimestampMixin, Base):
    """배송처(거래처) 마스터."""

    __tablename__ = "delivery_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)       # 거래처명
    address: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    # 연락처 정보
    contact_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # 반복/단발 구분
    delivery_type: Mapped[DeliveryType] = mapped_column(
        Enum(DeliveryType, name="deliverytype"),
        default=DeliveryType.RECURRING,
        nullable=False,
    )

    # ── 기본 시간창 (VRPTW) ─────────────────────────────────────────────────
    # 이 거래처에 반복 적용되는 기본 도착 가능 시간대
    tw_open:  Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    # 형식: "HH:MM" (예: "09:00") — NULL이면 제한 없음
    tw_close: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    # 형식: "HH:MM" (예: "17:00") — NULL이면 제한 없음

    # 서비스 소요 시간 (분) — 도착 후 하차 완료까지 걸리는 시간
    # VRP 시간 계산 시 이 시간만큼 다음 이동 출발이 지연됨
    service_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 배송 불가 시간대 (블랙아웃) — JSON 배열로 저장
    # 예: [{"type": "weekday", "days": [5, 6]},
    #       {"type": "time_range", "start": "12:00", "end": "13:00"}]
    # type: weekday = 요일 제한 (0=월 ~ 6=일)
    # type: time_range = 시간대 제한
    blackout_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 배송 특이사항 메모 (예: "지하 주차장 진입 불가")
    delivery_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # relationships
    dispatch_orders: Mapped[list["DispatchOrder"]] = relationship(  # noqa: F821
        "DispatchOrder", back_populates="delivery_point"
    )
