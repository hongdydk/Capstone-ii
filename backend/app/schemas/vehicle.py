from pydantic import BaseModel


class VehicleBase(BaseModel):
    plate_number: str
    vehicle_type: str
    height_m: float
    weight_kg: float
    length_cm: float | None = None
    width_cm: float | None = None
    max_load_kg: float | None = None  # 최대 적재 중량(kg)


class VehicleCreate(VehicleBase):
    pass


class VehiclePatch(BaseModel):
    vehicle_type: str | None = None
    height_m: float | None = None
    weight_kg: float | None = None
    length_cm: float | None = None
    width_cm: float | None = None
    max_load_kg: float | None = None
    is_active: bool | None = None


class VehicleRead(VehicleBase):
    id: int
    is_active: bool

    model_config = {"from_attributes": True}
