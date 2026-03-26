"""VRP 엔진 데모 스크립트 — TMAP API 실제 도로 시간 기반

사용법:
    cd C:/CapstoneII
    .venv\\Scripts\\python.exe backend/demo_vrp.py

시나리오: 서울 출발 → [광주, 대구] 경유 → 부산 도착
TMAP_APP_KEY 가 backend/.env 에 설정되어 있으면 실제 도로 시간을 사용합니다.
키가 없거나 API 실패 시 Haversine(직선거리 80 km/h) 으로 fallback 합니다.
"""

import asyncio
import sys
from pathlib import Path

# ── 환경 변수 로드 (settings/tmap_service import 전에 반드시 먼저) ────────────
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env", override=True)

# 프로젝트 루트에서 실행 가능하도록 경로 설정
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.route_optimizer import (
    MAX_DRIVE_SEC,
    MIN_REST_SEC,
    build_matrices,
    haversine_m,
    haversine_sec,
    insert_rest_stops,
    solve_tsp,
)
from app.core.config import settings


# ── 테스트 데이터 ─────────────────────────────────────────────────────────────

ORIGIN = {"name": "서울(강남)", "lat": 37.4979, "lon": 127.0276, "type": "origin"}
WAYPOINTS = [
    {"name": "광주(상무)", "lat": 35.1543, "lon": 126.8527, "type": "waypoint"},
    {"name": "대구(동성로)", "lat": 35.8714, "lon": 128.6014, "type": "waypoint"},
]
DESTINATION = {"name": "부산(서면)", "lat": 35.1577, "lon": 129.0597, "type": "destination"}

REST_STOPS = [
    {"name": "천안논산휴게소", "lat": 36.5760, "lon": 127.1461},
    {"name": "청주휴게소",    "lat": 36.6424, "lon": 127.4875},
    {"name": "대전(비래)휴게소","lat": 36.3282, "lon": 127.4272},
    {"name": "칠원휴게소",    "lat": 35.2854, "lon": 128.4825},
    {"name": "구마휴게소",    "lat": 35.5748, "lon": 128.3980},
]


# 화물차 기본 제원 (예시: 5톤 일반 화물보 기준)
TRUCK = {
    "height": 4.0,        # m
    "weight": 25000,      # kg
    "length": 1600,       # cm (16m)
    "width":  250,        # cm (2.5m)
}


def fmt_time(seconds: int) -> str:
    h, m = divmod(seconds // 60, 60)
    return f"{h}시간 {m:02d}분" if h else f"{m}분"


async def run_demo() -> None:
    all_nodes = [ORIGIN, *WAYPOINTS, DESTINATION]
    n = len(all_nodes)

    using_tmap = bool(settings.TMAP_APP_KEY)

    print("=" * 60)
    print("  루트온 VRP 엔진 데모")
    print("=" * 60)
    print(f"출발: {ORIGIN['name']}")
    for w in WAYPOINTS:
        print(f"  경유: {w['name']}")
    print(f"도착: {DESTINATION['name']}")
    print(f"후보 휴게소: {len(REST_STOPS)}개")
    print(f"시간 행렬: {'TMAP 화물차 경로 API' if using_tmap else 'Haversine 추정 (80 km/h)'}")
    if using_tmap:
        print(f"화물차 제원: 높이 {TRUCK['height']}m / 중량 {TRUCK['weight']//1000}톤 / 길이 {TRUCK['length']}cm / 폭 {TRUCK['width']}cm")
    print()

    # ── 1. 시간 행렬 구성 ─────────────────────────────────────────────────────
    if using_tmap:
        print("[1] TMAP 화물차 경로 API로 시간 행렬 구성 중... (n×n = %d회 호출)" % (n * (n - 1)))
        matrix, _ = await build_matrices(
            all_nodes,
            vehicle_height=TRUCK["height"],
            vehicle_weight=TRUCK["weight"],
            vehicle_length=TRUCK["length"],
            vehicle_width=TRUCK["width"],
        )
        label = "TMAP화물"
    else:
        print("[1] Haversine 시간 행렬 구성 (TMAP 키 없음)")
        matrix = [[0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i != j:
                    matrix[i][j] = haversine_sec(
                        all_nodes[i]["lat"], all_nodes[i]["lon"],
                        all_nodes[j]["lat"], all_nodes[j]["lon"],
                    )
        label = "Hav"

    header = f"  {'':8s}" + "".join(f"{nd['name'][:4]:>9}" for nd in all_nodes)
    print(f"\n  [{label}] 소요 시간 행렬:")
    print(header)
    for i, row in enumerate(matrix):
        cells = "".join(f"{fmt_time(v):>9}" for v in row)
        print(f"  {all_nodes[i]['name'][:6]:<8}{cells}")
    print()

    # ── TMAP vs Haversine 비교 (키 있을 때만) ──────────────────────────────────
    if using_tmap:
        print("  [TMAP vs Haversine 비교]")
        print(f"  {'구간':<28} {'TMAP':>8} {'Haversine':>10} {'차이':>7}")
        print("  " + "-" * 57)
        for i in range(n):
            for j in range(n):
                if i >= j:
                    continue
                tmap_t = matrix[i][j]
                hav_t  = haversine_sec(
                    all_nodes[i]["lat"], all_nodes[i]["lon"],
                    all_nodes[j]["lat"], all_nodes[j]["lon"],
                )
                diff = tmap_t - hav_t
                sign = "+" if diff >= 0 else ""
                label_str = f"{all_nodes[i]['name'][:5]} → {all_nodes[j]['name'][:5]}"
                print(f"  {label_str:<28} {fmt_time(tmap_t):>8} {fmt_time(hav_t):>10} {sign}{fmt_time(abs(diff)):>7}")
        print()

    # ── 2. TSP 최적화 ─────────────────────────────────────────────────────────
    print("[2] OR-Tools TSP 최적화")
    order = solve_tsp(matrix, start=0, end=n - 1)
    ordered = [all_nodes[i] for i in order]
    print("  방문 순서:", " → ".join(nd["name"] for nd in ordered))

    total_no_rest = sum(matrix[order[i]][order[i + 1]] for i in range(len(order) - 1))
    print(f"  순수 이동 시간: {fmt_time(total_no_rest)}")
    print()

    # ── 3. 법정 휴게 삽입 ─────────────────────────────────────────────────────
    print("[3] 2시간 초과 구간에 법정 휴게 삽입")
    print(f"  (법정 기준: 연속 {fmt_time(MAX_DRIVE_SEC)} → {fmt_time(MIN_REST_SEC)} 이상 휴식)")
    final = insert_rest_stops(ordered, matrix, order, REST_STOPS)

    print("\n  최종 경로:")
    cumul_sec = 0
    for i, node in enumerate(final):
        tag = ""
        if node.get("type") == "rest_stop":
            tag = f"  ← 휴게 {node.get('min_rest_minutes', 15)}분 필수"
            cumul_sec += MIN_REST_SEC
        elif i > 0:
            prev = final[i - 1]
            seg = haversine_sec(prev["lat"], prev["lon"], node["lat"], node["lon"])
            dist = haversine_m(prev["lat"], prev["lon"], node["lat"], node["lon"]) / 1000
            cumul_sec += seg
            tag = f"  (+{fmt_time(seg)}, {dist:.0f} km)"
        print(f"  {i+1:2d}. [{node.get('type','?'):12s}] {node['name']:<20}{tag}")

    rest_count = sum(1 for nd in final if nd.get("type") == "rest_stop")
    print()
    print(f"  삽입된 휴게소: {rest_count}개")
    print(f"  총 예상 소요: {fmt_time(cumul_sec)} (이동 + 의무 휴게)")
    print()

    # ── 4. 검증 ───────────────────────────────────────────────────────────────
    print("[4] 검증")
    wp_order = [nd["name"] for nd in final if nd.get("type") == "waypoint"]

    # 두 순서의 총 이동 시간 비교 (행렬 기준)
    gwangju_node = WAYPOINTS[0]
    daegu_node   = WAYPOINTS[1]
    r1 = (matrix[0][1] + matrix[1][2] + matrix[2][3])  # 서울→광주→대구→부산
    r2 = (matrix[0][2] + matrix[2][1] + matrix[1][3])  # 서울→대구→광주→부산
    optimal_label = f"{'→'.join(wp_order)}"

    print(f"  서울→광주→대구→부산 순서: {fmt_time(r1)}")
    print(f"  서울→대구→광주→부산 순서: {fmt_time(r2)}")
    tsp_total = sum(matrix[order[i]][order[i + 1]] for i in range(len(order) - 1))
    print(f"  TSP 선택: {optimal_label}  ({fmt_time(tsp_total)})")

    ok_order = tsp_total <= max(r1, r2)
    ok_rest  = rest_count > 0
    print()
    print(f"  {'✓' if ok_order else '✗'} 경유지 순서 최적화")
    print(f"  {'✓' if ok_rest  else '✗'} 법정 휴게 규정 반영 ({rest_count}개 삽입)")


if __name__ == "__main__":
    asyncio.run(run_demo())
