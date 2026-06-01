# 변경 이력

## [2026-06-02] 일괄 배차 — 차량 출발·open_end (depot 선택)

- `POST /optimize/dispatch`: **depot** (`depot_name` / `depot_lat` / `depot_lon`) **선택**. 미지정 시 공통 기지 노드 없이 배차.
- `vehicles[]`: 차량별 **`start_lat` / `start_lon`** — 당일 출발·현재 위치 등 (depot 없이 요청 가능).
- `vehicles[]`: **`end_policy`** — `open_end`(기본, 지입·분산: 마지막 배송지 종료) / `return_to_depot`(기지 복귀). depot + `return_to_depot` = 기존 **직영 창고 왕복** 모델.
- **Breaking:** 없음 — 기존 클라이언트가 `depot_*`를 계속내면 하위 호환.
- 문서: [README.md](README.md) §8·§17.

## [2026-06-01] 캘린더 시간창 API

- `reference_departure_at`, 노드별 `earliest_at`/`latest_at`, `tw_open`/`tw_close`(+`service_date`) 추가 (`/optimize/`, `/optimize/replan`, `/optimize/dispatch`, `/demo/route`).
- `backend/app/services/time_windows.py`에서 Asia/Seoul 기준으로 OR-Tools용 `earliest_sec`/`latest_sec`로 변환; 기존 경과 초 필드는 deprecated·하위 호환 유지.
- `tests/test_time_windows.py` 변환·검증 단위 테스트 추가.

## [2026-05-13] VRPTW 다차량 배차 / cargo 상하차 스키마 개편

### 삭제
- `.github/copilot-instructions.md` — 작업용 임시 파일 제거
- `backend/tests/helpers.py` — 카카오 API 테스트 헬퍼 제거
- `backend/tests/test_kakao_local.py` — 카카오 로컬 테스트 제거
- `backend/tests/test_kakao_long.py` — 카카오 장거리 테스트 제거

---

### `backend/app/services/optimizer.py`
- **`solve_vrptw()` 신규 추가**
  - OR-Tools `RoutingModel`으로 다차량 VRPTW 최적화
  - **Time Dimension**: 노드별 시간창 `(earliest_sec, latest_sec)` 제약
  - **Capacity Dimension** (`AddDimensionWithVehicleCapacity`): 차량별 최대 적재량 제약
  - **Count Dimension**: 차량당 최대 방문 수 `ceil(배송지수 / 차량수) + 1` 제한 → 균등 배분 강제
  - `AddDisjunction`으로 미배정 노드 허용 (고비용 패널티 드롭)
  - `PATH_CHEAPEST_ARC` + `GUIDED_LOCAL_SEARCH` 탐색
  - 반환: `(vehicle_routes, unserved_nodes)` 또는 `None`

---

### `backend/app/api/optimize.py`
- **`optimize()` 엔드포인트 수정**
  - 상하차 매핑 방식 변경: `pickup_id` / `delivery_for` → `cargo_id` / `cargo_role` (`"pickup"` / `"delivery"`)
  - N:M 복합 상하차 지원: 동일 `cargo_id`를 가진 pickup·delivery 인덱스 전체 조합을 자동으로 `pickup_deliveries` 쌍으로 생성
  - `extra_stops`의 `stop_type`에 `"pickup"`, `"delivery"` 추가 처리
  - **목적지 자동 승격**: 목적지 미지정 시 마지막 delivery 경유지를 목적지로 자동 사용
- **`dispatch_multi()` 완전 구현** (기존 501 stub → 정상 동작)
  - 요청: `DispatchRequest` (depot 좌표, 차량 목록, 배송지 목록, 프로파일)
  - GraphHopper `build_time_matrix()`로 N×N 시간·거리 행렬 계산
  - `solve_vrptw()`로 차량별 방문 순서 결정
  - 차량별 `get_route_with_stats()`로 내부 확인용 폴리라인·거리·소요시간 산출
  - `plan_rest_stops_from_polyline()`으로 내부 GraphHopper 폴리라인 기반 휴게소 자동 삽입
  - 반환: `DispatchResponse` (차량별 `route[]` 순서·`lat`/`lon`, 미배정 노드 목록; `polyline`은 선택 디버그 필드)

---

### `backend/app/schemas/optimize.py`
- `ExtraStop`: `pickup_id` / `delivery_for` 필드 → `cargo_id: str | None` / `cargo_role: Literal["pickup","delivery"] | None` 교체
- **신규 스키마 추가**
  - `DispatchNodeInput`: 배송지 이름·좌표·시간창·화물 중량
  - `DispatchVehicleInput`: 차량 이름·최대 적재량
  - `DispatchRequest`: depot, 차량 목록, 배송지 목록, GraphHopper 프로파일, 탐색 제한 시간
  - `DispatchVehicleRoute`: 차량별 결과 (`route[]` 순서·`lat`/`lon`, 선택 디버그용 폴리라인, 거리, 소요시간, 화물 합계, 휴게소 수)
  - `DispatchResponse`: 전체 차량 경로 + 미배정 노드 목록

---

### `backend/app/api/demo.py`
- `DemoNode`의 `pickup_from_idx` 필드 제거
- 대체 필드 추가: `cargo_id: str | None`, `cargo_role: Literal["pickup","delivery"] | None`, `cargo_weight_kg: float | None`
- N:M 복합 상하차 쌍 자동 생성 (`cargo_id` 기준 매핑)

---

### `backend/app/models/vehicle.py`
- `max_load_kg: Mapped[float | None]` 컬럼 추가 (`Float` 타입)

### `backend/app/schemas/vehicle.py`
- `VehicleBase`, `VehiclePatch`에 `max_load_kg: float | None = None` 필드 추가

---

### `backend/app/services/graphhopper.py`
- `get_route_with_stats()`: `httpx.ConnectError` 발생 시 `HTTPException(503)` 으로 변환 (500 Internal Error 방지)
- `get_route_alternatives()`: 동일하게 503 변환 및 기타 예외 폴백 처리
- `build_time_matrix()`: 시간 행렬과 함께 거리 행렬도 반환하도록 변경 (`dist_matrix` 추가 반환값)
