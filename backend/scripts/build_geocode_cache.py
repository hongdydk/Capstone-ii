"""물류단지·물류창고 전체 주소를 지오코딩하여 캐시 파일에 저장합니다.

실행:
    cd C:/CapstoneII
    .venv\\Scripts\\python.exe backend/scripts/build_geocode_cache.py

TMAP 지오코딩 API만 사용합니다 (경로 API 호출 없음).
이미 캐시에 있는 주소는 건너뜁니다 → 중단 후 재실행해도 안전합니다.
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv
load_dotenv(ROOT / "backend" / ".env", override=True)

import xlrd
from app.services.tmap_service import (
    geocode_address,
    _geocode_cache,
    _GEOCODE_CACHE_PATH,
    _save_geocode_cache,
)

XLS_DEPOT = ROOT / "자료" / "물류단지정보_260325.xls"
XLS_WH    = ROOT / "자료" / "물류창고정보_260325.xls"


def _load_addresses() -> list[tuple[str, str]]:
    """(label, address) 목록 반환."""
    addrs = []

    # 물류단지 (28곳)
    wb = xlrd.open_workbook(str(XLS_DEPOT))
    ws = wb.sheet_by_index(0)
    for r in range(1, ws.nrows):
        name   = str(ws.cell_value(r, 0)).strip()
        addr   = str(ws.cell_value(r, 2)).strip()
        status = str(ws.cell_value(r, 14)).strip()
        if name and addr and "운영" in status:
            addrs.append((f"[단지] {name}", addr))

    # 물류창고 (최대 5825곳)
    wb2 = xlrd.open_workbook(str(XLS_WH))
    ws2 = wb2.sheet_by_index(0)
    for r in range(1, ws2.nrows):
        name = str(ws2.cell_value(r, 0)).strip()
        addr = str(ws2.cell_value(r, 2)).strip()
        if name and addr:
            addrs.append((f"[창고] {name}", addr))

    return addrs


async def run(batch_size: int = 5) -> None:
    all_addrs = _load_addresses()
    total     = len(all_addrs)

    # 이미 캐시에 있는 것 제외
    todo = [(label, addr) for label, addr in all_addrs if addr not in _geocode_cache]
    skip = total - len(todo)

    print(f"전체 주소: {total}개")
    print(f"캐시 히트: {skip}개 (건너뜀)")
    print(f"신규 호출: {len(todo)}개")
    print(f"캐시 파일: {_GEOCODE_CACHE_PATH}")
    print()

    if not todo:
        print("모두 캐시에 있습니다. 완료.")
        return

    sem     = asyncio.Semaphore(batch_size)
    success = 0
    fail    = 0

    async def _one(idx: int, label: str, addr: str) -> None:
        nonlocal success, fail
        async with sem:
            result = await geocode_address(addr)
            if result:
                success += 1
            else:
                fail += 1
            done = success + fail
            if done % 50 == 0 or done == len(todo):
                pct = done / len(todo) * 100
                print(f"  [{done:>4}/{len(todo)}] {pct:5.1f}%  성공={success}  실패={fail}")

    tasks = [_one(i, label, addr) for i, (label, addr) in enumerate(todo)]
    await asyncio.gather(*tasks)

    _save_geocode_cache()
    print()
    print(f"완료: 성공 {success}개 / 실패 {fail}개")
    print(f"총 캐시 항목: {len(_geocode_cache)}개  →  {_GEOCODE_CACHE_PATH}")


if __name__ == "__main__":
    asyncio.run(run())
