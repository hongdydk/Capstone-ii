# RouteOn 백엔드 아키텍처

백엔드 최적화·경로 파이프라인의 **레이어·단계·상태·리팩터 로드맵**을 정의한다. API 계약·스키마 단일 출처는 [SCHEMA.md](SCHEMA.md), 제품 방향은 [PLAN.md](PLAN.md)를 따른다.

---

## 목차

1. [레이어·역할](#1-레이어역할)
2. [파이프라인 (Strategy)](#2-파이프라인-strategy)
3. [상태 전이 (Trip / route)](#3-상태-전이-trip--route)
4. [패턴](#4-패턴)
5. [GraphHopper 실패 정책](#5-graphhopper-실패-정책)
6. [리팩터링 로드맵](#6-리팩터링-로드맵)
7. [문서 읽는 순서](#7-문서-읽는-순서)

---

## 1. 레이어·역할

| 레이어 | 모듈 (코드) | 책임 |
|--------|-------------|------|
| **API** | `backend/app/api/optimize.py` | HTTP만 — Trip 로드, 요청 검증, 파이프라인 runner 위임. 비즈니스 로직 없음. |
| **Application pipeline** | `backend/app/services/route_pipeline.py` | use case — `run_basic_optimize`, `run_with_rest_optimize`, `run_replan_with_rest`; `run_with_rest_core`, `prepare_*_nodes`, 단계별 헬퍼. |
| **Domain / services** | `optimizer.py`, `rest_stop_inserter.py`, `time_windows.py` | TSP·제약 검증, 법정 휴게 삽입, 시간창 변환. DB·HTTP 비의존. |
| **Infrastructure** | `graphhopper.py` | GraphHopper RouteEngine **어댑터** — 행렬·geometry·polyline. (Phase 3에서 명시적 인터페이스 추출 예정) |

의존 방향: `API → pipeline → domain`, `pipeline → infrastructure`. domain은 infrastructure를 직접 호출하지 않는다 (pipeline이 조합).

---

## 2. 파이프라인 (Strategy)

`optimize_mode` (`basic` \| `with_rest`) 및 엔드포인트가 **Strategy**로 runner를 선택한다. `replan`은 with_rest 계열과 동일 단계에 replan 컨텍스트를 더한다.

### 2.1 basic

**진입:** `POST /optimize/` (`optimize_mode=basic`), `POST /optimize/basic`  
**Runner:** `run_basic_optimize`

| 순서 | 단계 함수 | 설명 | GH 호출 |
|------|-----------|------|---------|
| 1 | `resolve_reference_departure_at` | 출발 기준 시각 (시간창) | — |
| 2 | `prepare_optimize_nodes` | 출발·경유·목적 노드 구성 | — |
| 3 | `normalize_waypoints_time_windows` | 캘린더 시간창 → `earliest_sec`/`latest_sec` | — |
| 4 | `_build_ordered_nodes_fixed_order` | 요청 순서 고정 `RouteNode[]` | — |
| 5 | `fetch_route_stats_for_ordered_nodes` | 구간 시간·거리·polyline 1회 | `get_route_with_stats` **1회** |
| 6 | `apply_route_to_trip` (`event=optimize`) | `optimized_route`·출발지·`in_progress` persist | — |

- `build_time_matrix` **사용 안 함** (matrix ❌)

### 2.2 with_rest

**진입:** `POST /optimize/` (기본 `with_rest`), `POST /optimize/with-rest`  
**Runner:** `run_with_rest_optimize`

| 순서 | 단계 함수 | 설명 | GH 호출 |
|------|-----------|------|---------|
| 1 | `resolve_reference_departure_at` | 출발 기준 시각 | — |
| 2 | `prepare_optimize_nodes` | 노드·휴게 희망지 구성 | — |
| 3 | `normalize_waypoints_time_windows` | 시간창 정규화 | — |
| 4 | `load_rest_candidates` | DB·희망 휴게소 후보 | — |
| 5 | `run_with_rest_core` | matrix → TSP → geometry → rest → totals | matrix ✅, geometry ✅ |
| 6 | `apply_route_to_trip` (`event=optimize`) | persist | — |

### 2.3 replan

**진입:** `POST /optimize/replan`  
**Runner:** `run_replan_with_rest`

with_rest와 **동일 GH 단계**(matrix → TSP → geometry → rest). 노드 구성은 `prepare_replan_nodes`, matrix 이후는 `run_with_rest_core` 단일 호출(§6 Phase 2).

| 순서 | 단계 함수 | 설명 | GH 호출 |
|------|-----------|------|---------|
| 1 | `resolve_reference_departure_at` | 출발 기준 시각 (`trip_departure_time=None`) | — |
| 2 | `prepare_replan_nodes` | 현재·잔여 경유·목적 노드 구성 | — |
| 3 | `load_rest_candidates` | DB 휴게소 후보 | — |
| 4 | `run_with_rest_core` | matrix → TSP → geometry → rest → totals | matrix ✅, geometry ✅ |
| 5 | `apply_route_to_trip` (`event=replan`) | `optimized_route`·`route_version`만 갱신 | — |

| 항목 | replan |
|------|--------|
| `prepare_optimize_nodes` | **미사용** |
| `initial_drive_sec` | `req.current_drive_sec` → `run_with_rest_core(..., initial_drive_sec=…)` |
| `is_emergency` | `req.is_emergency` → `run_with_rest_core(..., is_emergency=…)` |
| persist | 출발지·status 유지 |

---

## 3. 상태 전이 (Trip / route)

### 3.1 Trip.status

코드·DB enum (`tripstatus`): `scheduled` → `in_progress` → `completed` \| `cancelled`

| 전이 | 트리거 (현재 코드) | 비고 |
|------|-------------------|------|
| `scheduled` → `in_progress` | `run_basic_optimize` / `run_with_rest_optimize` 성공 시 `apply_route_to_trip(event=optimize)` | 최초 optimize 성공 시 |
| `in_progress` → `in_progress` | `run_replan_with_rest` 성공 | status 변경 없음 |
| `in_progress` → `completed` | `[TBD]` — 운행 완료 API·관제/앱 확정 후 | PLAN §3.5 |
| `*` → `cancelled` | `[TBD]` — 배차 취소 플로우 | |

> PLAN.md에는 `assigned` 표기가 있으나 DB·모델은 `scheduled`를 사용한다. 스키마 통일은 팀장 확정 후 반영.

### 3.2 optimized_route + route_version (H4 확정)

**저장 위치:** `trips.optimized_route` (JSONB)

**성공 시 갱신:** `optimize`·`replan` 모두 `build_optimized_route_payload` → `apply_route_to_trip`

| 필드 | 의미 |
|------|------|
| `route` | `RouteNode` dict 배열 (방문 순서) |
| `estimated_duration_min` | 예상 소요(분) |
| `rest_stops_count` | 휴게소 노드 수 |
| `route_version` | 최초 `1`, replan·재optimize마다 `+1` (`next_route_version`) |

**Source of truth:** DB `trips.optimized_route` + `route_version`.  
- 기사 앱·관제는 optimize/replan **응답** `route[]`로 즉시 내비/지도 갱신.  
- 재접속·폴링 시 Trip 조회의 `optimized_route`와 `route_version`으로 동기화 — **클라이언트는 서버 version이 더 크면 로컬 캐시를 덮어쓴다** (권장).

### 3.3 needs_replan → replan

`POST /location-logs/` (`location_logs.py`):

- 서버가 `accumulated_drive_sec` 계산 (`REST_PLAN_SEC` = 6000).
- `needs_replan=true`이면 앱이 `POST /optimize/replan` 호출 (resting 상태면 억제).

**M3** (서버 주도 replan vs 앱 폴링): `[TBD]` — 현재는 **앱 트리거 권장** (응답 필드 계약 유지).

---

## 4. 패턴

과도한 추상화 없이 다음만 적용한다.

| 패턴 | 적용 |
|------|------|
| **Strategy** | `optimize_mode` / `run_*_optimize` runner 선택 (`optimize.py`) |
| **Adapter** | `graphhopper.py` — GraphHopper HTTP를 domain이 쓰기 쉬운 행렬·geometry API로 래핑. Phase 3: `GraphHopperRouteEngine` 프로토콜 |
| **단일 persist** | `apply_route_to_trip(trip, route, *, event: optimize \| replan)` — optimize/replan/basic/with_rest **공통** DB 반영 |

### 4.1 apply_route_to_trip (Phase 1 구현됨)

```text
apply_route_to_trip(trip, trip_id, final_route, total_sec, total_distance_km, db, *, event, origin_*?)
  → build_optimized_route_payload(...)
  → event==optimize: origin_*, status=in_progress
  → event==replan: optimized_route만 (version++)
  → db.commit()
  → OptimizeResponse
```

---

## 5. GraphHopper 실패 정책

확정 정책 (fail-fast, 503):

| ID | 조건 | 동작 | 코드 위치 |
|----|------|------|-----------|
| **H1** | `build_time_matrix` 실패 (연결·5xx·파싱) | HTTP **503**, 폴백 없음 | `graphhopper._call_route`, `build_time_matrix` |
| **H2-A** ✅ | with_rest / replan **geometry** (`get_route_with_stats` in `insert_rest_stops`·`fetch_route_stats_for_ordered_nodes`) 실패 | HTTP **503**, 휴게 없이 200 금지 | `graphhopper.get_route_with_stats` propagate |
| **basic** | `fetch_route_stats_for_ordered_nodes` route 실패 | HTTP **503** | `get_route_with_stats` propagate |

**H2-A**는 2026-06-12 구현 완료 — [CHANGELOG.md](CHANGELOG.md), BUGREPORT 백로그에서 **제거됨**(잔존 cross-ref는 H3 등 방어 분기 설명만).

클라이언트는 503 시 재시도·사용자 안내. 임의 좌표·Haversine 폴백은 사용하지 않는다.

---

## 6. 리팩터링 로드맵

### Phase 1 — 단일 persist 추출 ✅ 구현됨

**목표:** `apply_route_to_trip` + `build_optimized_route_payload`로 optimize/replan/basic/with_rest persist 통합.

**완료 조건:**

- [x] `apply_route_to_trip` 존재, `event=optimize|replan` 분기
- [x] `run_basic_optimize`, `run_with_rest_optimize`, `run_replan_with_rest`가 동일 함수 호출
- [x] `persist_replan` 제거(흡수)
- [x] `backend/tests/` 전체 통과

**영향 파일:** `route_pipeline.py`, (문서) 본 파일, `README.md`, `PLAN.md`, `CHANGELOG.md`  
**완료 커밋 참고:** `0ff3435` (`apply_route_to_trip` 단일 persist)

### Phase 2 — 파이프라인 단계 명시적 분리 ✅ 구현됨

**목표:** runner 내부 인라인·**copy-paste TSP 블록**을 제거하고, with_rest·replan이 **동일 core**만 parameter로 구분해 호출.

**금지:** `run_with_rest_optimize`와 `run_replan_with_rest` 각각에 matrix→TSP→geometry→rest 블록을 **복붙**하는 것.

#### `prepare_replan_nodes(req, reference)`

replan 전용 노드 준비. `prepare_optimize_nodes(trip, req)`와 **대칭**이나 Trip·`extra_stops` 대신 ReplanRequest 필드만 사용.

| 항목 | 내용 |
|------|------|
| **시그니처** | `prepare_replan_nodes(req: ReplanRequest, reference) -> PreparedReplanNodes` |
| **호출 주체** | `run_replan_with_rest` — runner가 먼저 `resolve_reference_departure_at(req.reference_departure_at, trip_departure_time=None)`으로 `reference` 생성 |
| **책임** | ① `remaining_waypoints`·`dest_*` 해석(미지정 시 마지막 경유지→목적지) ② `normalize_waypoints_time_windows(remaining_wps, reference)` ③ `nodes = [current] + remaining + [dest]` 구성 |
| **반환** | `PreparedReplanNodes`: `nodes`, `waypoints_raw`, `dest_name`, `dest_lat`, `dest_lon` — 이후 `run_with_rest_core` 입력 |
| **미포함** | GH 호출, TSP, 휴게 DB 조회, persist |

#### `run_with_rest_core(...)`

with_rest·replan **공통** matrix→TSP→geometry→rest→totals 오케스트레이션. runner는 노드 준비·휴게 후보 로드·persist만 담당.

| 항목 | 내용 |
|------|------|
| **시그니처** | `async run_with_rest_core(nodes, waypoints_raw, dest_name, dest_lat, dest_lon, rest_candidates, *, initial_drive_sec=0, is_emergency=False) -> WithRestCoreResult` |
| **입력** | `nodes`·`waypoints_raw`·`dest_*`는 `prepare_optimize_nodes` 또는 `prepare_replan_nodes` 반환값; `rest_candidates`는 runner가 `load_rest_candidates`로 조회 |
| **replan 파라미터** | with_rest: `initial_drive_sec=req.initial_drive_sec`, `is_emergency=False` — replan: `initial_drive_sec=req.current_drive_sec`, `is_emergency=req.is_emergency` |

**단계 순서** (`run_with_rest_core` 내부 — 순서 고정):

| # | 단계 | 함수·GH | 산출 |
|---|------|---------|------|
| 1 | matrix | `build_time_matrix(nodes)` | `time_matrix`, `dist_matrix` |
| 2 | tsp | `resolve_tsp_order(...)` | `tsp_order` |
| 3 | geometry prep | `build_ordered_nodes_and_matrices(...)` | `ordered_nodes`, `final_matrix`, `final_dist` |
| 4 | rest | `insert_rest_stops(..., initial_drive_sec, is_emergency)` | `final_route` (geometry=`get_route_with_stats` in rest) |
| 5 | totals | `compute_route_totals(...)` | `total_sec`, `total_distance_km` |

**runner 차이 (parameter만):**

| | `run_with_rest_optimize` | `run_replan_with_rest` |
|---|--------------------------|------------------------|
| 노드 준비 | `prepare_optimize_nodes(trip, req)` | `prepare_replan_nodes(req, reference)` |
| 휴게 후보 | `load_rest_candidates(db, preferred_rest)` | `load_rest_candidates(db)` |
| core | `run_with_rest_core(..., initial_drive_sec=req.initial_drive_sec)` | `run_with_rest_core(..., initial_drive_sec=req.current_drive_sec, is_emergency=req.is_emergency)` |
| persist | `apply_route_to_trip(..., event=optimize)` | `apply_route_to_trip(..., event=replan)` |

**완료 조건:**

- [x] `run_with_rest_optimize` / `run_replan_with_rest`가 동일 `run_with_rest_core(...)` 호출 (TSP 블록 **한 곳**)
- [x] replan 인라인 노드 빌드를 `prepare_replan_nodes`로 추출
- [x] 기존 테스트 통과, API 응답 필드 불변

**영향 파일:** `route_pipeline.py`, `backend/tests/test_route_pipeline*.py`  
**완료:** Phase 1(`0ff3435`) 직후 본 작업 커밋

### Phase 3 — GraphHopper adapter 인터페이스 (선택)

**목표:** `GraphHopperRouteEngine` 프로토콜(또는 ABC) + 기본 구현이 현 `graphhopper.py`; 테스트에서 mock 주입 용이.

**완료 조건:**

- [ ] `build_time_matrix`, `get_route_with_stats` 등이 인터페이스 뒤에 위임
- [ ] pipeline이 구현체 주입 가능 (기본값은 프로덕션 GH)
- [ ] matrix/polyline 테스트가 HTTP monkeypatch 대신 adapter mock 가능 (점진적)

**영향 파일:** `graphhopper.py` (또는 `route_engine.py` 신설), `route_pipeline.py`, `backend/tests/`

---

## 7. 문서 읽는 순서

구현·리뷰·디버그 시 아래 순서를 권장한다.

1. **[README.md](README.md)** — 실행·API 진입·문서 맵
2. **본 파일 ([ARCHITECTURE.md](ARCHITECTURE.md))** — 레이어·파이프라인·상태·리팩터 Phase (**구현 기준**)
3. **[SCHEMA.md](SCHEMA.md)** — 요청/응답·DB 계약 (**breaking 변경 단일 출처**)
4. **[PLAN.md](PLAN.md)** — 제품·기술 방향·TBD
5. **[BUGREPORT.md](BUGREPORT.md)** — 미결 이슈·결정용 (완료 H1/H2-A/H4 등은 CHANGELOG만)

코드 변경은 **§6 Phase 순** — Phase 1(`0ff3435`) → Phase 2(본 절) 완료 후 Phase 3(선택).

---

*최종 갱신: 2026-06-14 — Phase 1(`0ff3435`), Phase 2 `prepare_replan_nodes`·`run_with_rest_core` 구현 완료*
