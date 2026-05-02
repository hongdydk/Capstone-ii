from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.database import Base, engine
import app.models  # noqa: F401 — create_all이 모든 테이블을 인식하도록 등록
from app.api import optimize, vehicles, drivers, rest_stops, trips, location_logs, demo


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="RouteOn",
    description="화물차 법정 휴게 규정 자동 반영 경로 최적화 API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000",
                   "http://localhost:8001", "http://127.0.0.1:8001", "null"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(optimize.router,       prefix="/optimize",       tags=["경로 최적화"])
app.include_router(vehicles.router,       prefix="/vehicles",       tags=["차량"])
app.include_router(drivers.router,        prefix="/drivers",        tags=["운전자"])
app.include_router(rest_stops.router,     prefix="/rest-stops",     tags=["휴게소"])
app.include_router(trips.router,          prefix="/trips",          tags=["운행"])
app.include_router(location_logs.router,  prefix="/location-logs",  tags=["위치 로그"])
app.include_router(demo.router,           prefix="/demo",           tags=["데모"])

# frontend/ 정적 파일 서빙 — http://localhost:8000/map
import pathlib
_FRONTEND = pathlib.Path(__file__).parent.parent.parent / "frontend"
if _FRONTEND.exists():
    app.mount("/map", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")


@app.get("/health", tags=["헬스체크"])
async def health():
    return {"status": "ok"}
