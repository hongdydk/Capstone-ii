# RouteOn 운영·알고리즘 이슈 백로그

## 목적

Oracle Cloud + Docker 배포 환경에서 **운영 안정화**와 **알고리즘 정합**을 위해, 코드 분석에서 도출한 잠재 이슈를 팀장이 항목별로 검토·확정하기 위한 문서입니다. 각 항목의 **권장**은 제안일 뿐 확정이 아닙니다.

**배포 맥락:** FastAPI·PostgreSQL·GraphHopper는 컨테이너 네트워크로 연동합니다. `replan`·관제·기사 앱 계약은 [SCHEMA.md](SCHEMA.md) 및 [PLAN.md](PLAN.md) §3.6·§5.2를 따릅니다.

## 상태 범례

| 표기 | 의미 |
|------|------|
| `[ ]` 미결정 | 팀장 선택지 검토 전 |
| `[x]` 확정 | 선택지·구현 방향 확정 |
| `[~]` 진행 중 | 확정 후 구현·테스트 중 |
| `[x]` 구현완료 | 확정·코드·테스트 반영 완료 (`**상태:**` 줄에 `[x] 구현완료` 표기) |
| `[—]` 보류 | 수요·마일스톤에 따라 연기 |

## 우선순위 요약

| 티어 | ID | 제목 |
|------|-----|------|
| **P0** | H2 | polyline 실패 시 휴게 삽입 스킵 |
| **P0** | H3 | 6000–7200초 단일 구간 휴게 갭 |
| **P1** | M2 | replan 시간창 기준 |
| **P1** | M3 | `current_drive_sec` 이중 출처 |
| **P1** | M4 | `estimated_duration_min` 불일치 |
| **P1** | L2 | `GH_BASE` localhost 하드코딩 |
| **P2** | M1 | 차량 제원 GH 미반영 |
| **P2** | M5 | replan 목적지 중복 |
| **P2** | M6 | instructions 구간 분할 |
| **P2** | M7 | 전국 휴게소 폴백 |
| **P2** | M8 | cargo N:M 제약 |
| **P3** | L1 | GH 구간 캐시 |
| **P3** | L3 | N² 행렬 확장성 |
| **P3** | L4 | 휴게 후보 없음 |
| **P3** | L5 | `cargo_weight` 미사용 |
| **P3** | L6 | `route[]` cargo 메타 누락 |

---

## P0 — 배포 운영 즉시 리스크

### H2 · polyline 실패 시 휴게 삽입 스킵

| | |
|---|---|
| **ID** | H2 |
| **제목** | polyline 실패 시 휴게 삽입 스킵 |
| **우선순위** | P0 |

**문제**  
`optimize`·`replan`에서 `get_route_with_stats` 예외 시 `polyline=[]`로 폴백한다. `plan_rest_stops_from_polyline_async`는 polyline 없으면 조기 반환하거나 정밀 삽입을 건너뛰어 **법정 휴게가 누락**될 수 있다.

**배포 영향 (OCI/Docker)**  
GH 일시 장애·422 경로 오류 시 **휴게 없는 route[]**가 200으로 내려가 기사·관제가 법정 위반 경로를 그대로 사용할 수 있다.

**관련 파일/위치**  
`backend/app/api/optimize.py` — polyline 폴백, `plan_rest_stops_from_polyline_async` 호출  
`backend/app/services/rest_stop_inserter.py` — `plan_rest_stops_from_polyline_async`  
`backend/app/services/graphhopper.py` — `get_route_with_stats`

**선택지**  
- **A.** polyline 실패 시 **503/422** (휴게 필수 경로 거부)  
- **B.** 행렬 기반 coarse 휴게 삽입 폴백 + `warnings`  
- **C.** 현행(휴게 스킵, 200)

**권장 (확정 아님)**  
**A** 또는 **B** — 법정 휴게는 P0 제품 요구

**breaking**  
**N** (에러 코드 추가); **Y** 가능(B: 응답에 `warnings`·휴게 품질 필드)

**선행 의존**  
—

**결정 필요**  
polyline GH 실패 시 휴게 삽입 없이 200을 반환할 것인가?

**상태:** `[ ]` 미결정

---

### H3 · 6000–7200초 단일 구간 휴게 갭

| | |
|---|---|
| **ID** | H3 |
| **제목** | 6000–7200초 단일 구간 휴게 갭 |
| **우선순위** | P0 |

**문제**  
`REST_PLAN_SEC=6000`(선제), `MAX_DRIVE_SEC=7200`(법정 상한). `initial_drive_sec + route_time_sec ≤ 7200`이면 휴게 삽입을 생략하는 조기 반환이 있다. 누적이 이미 6000을 넘었는데 남은 단일 구간이 1200초 이하인 경우 등 **선제·법정 사이 갭**에서 휴게가 빠질 수 있다.

**배포 영향 (OCI/Docker)**  
장거리 단일 고속 구간(휴게소 없는 polyline 구간)에서 **실운행 시 2시간 연속 운전** 위험이 있다. 앱·`location_logs`의 `needs_replan`은 6000 기준이라 서버 삽입과 어긋날 수 있다.

**관련 파일/위치**  
`backend/app/services/rest_stop_inserter.py` — `REST_PLAN_SEC`, `MAX_DRIVE_SEC`, 조기 반환 로직  
`backend/app/api/optimize.py` — `initial_drive_sec` 전달

**선택지**  
- **A.** `initial_drive_sec ≥ REST_PLAN_SEC`이면 단일 구간이라도 **강제 삽입**  
- **B.** 구간을 가상 분할해 greedy 삽입  
- **C.** 현행(7200 이하 단일 구간 스킵) + 앱 replan에 의존

**권장 (확정 아님)**  
**A** — 법정 준수와 `location_logs` 트리거 정합

**breaking**  
**N** (동일 API, route[]에 휴게 노드 추가 가능)

**선행 의존**  
—

**결정 필요**  
6000(선제)과 7200(법정 상한) 사이 단일 구간에서 휴게 삽입 정책을 어떻게 할 것인가?

**상태:** `[ ]` 미결정

---

## P1 — replan·시간·관제 불일치

### M2 · replan 시간창 기준

| | |
|---|---|
| **ID** | M2 |
| **제목** | replan 시간창 기준 |
| **우선순위** | P1 |

**문제**  
replan은 `reference_departure_at`만 쓰고 `trip` 출발 시각은 `trip_departure_time=None`으로 넘긴다. 잔여 경유지 `earliest_sec`/`latest_sec`가 **최초 optimize 기준**인지 **현재 시각 기준**인지 모호하다.

**배포 영향 (OCI/Docker)**  
운행 중 replan 시 시간창 위반 422 또는 느슨한 창으로 **잘못된 순서**가 나올 수 있다.

**관련 파일/위치**  
`backend/app/api/optimize.py` — replan 핸들러, `reference_departure_at`  
`backend/app/schemas/optimize.py` — replan 요청 스키마

**선택지**  
- **A.** replan 시 `reference=now()` 고정  
- **B.** 요청 `reference_departure_at` + trip 출발 시각 병합 규칙 문서화  
- **C.** 잔여 구간 시간창 비활성(휴게만)

**권장 (확정 아님)**  
**B** — SCHEMA에 기준 시각 계약 명시

**breaking**  
**Y** 가능(시간창 해석 변경 시 422 패턴 변화)

**선행 의존**  
—

**결정 필요**  
replan의 시간창 기준시각은 `reference_departure_at`만 쓸 것인가, trip 출발 시각·경과 시간을 병합할 것인가?

**상태:** `[ ]` 미결정

---

### M3 · `current_drive_sec` 이중 출처

| | |
|---|---|
| **ID** | M3 |
| **제목** | `current_drive_sec` 이중 출처 |
| **우선순위** | P1 |

**문제**  
replan 요청의 `current_drive_sec`(앱 전송)과 `location_logs` 기반 `_calc_accumulated_drive_sec`(서버 계산)이 **병행**한다. 값이 다르면 휴게 삽입·`needs_replan` 판단이 어긋난다.

**배포 영향 (OCI/Docker)**  
기사 앱·백엔드가 서로 다른 누적 시간으로 replan을 호출·판단할 수 있다.

**관련 파일/위치**  
`backend/app/api/optimize.py` — replan, `_calc_accumulated_drive_sec`  
`backend/app/schemas/optimize.py` — `current_drive_sec` 필드

**선택지**  
- **A.** 서버 계산값 **권위** (요청값은 힌트)  
- **B.** 앱 전송값 **권위**  
- **C.** 둘 중 큰 값·차이 시 409

**권장 (확정 아님)**  
**A** — `location_logs`가 있으면 서버 우선

**breaking**  
**Y** 가능(replan 입력 검증·응답 메타 추가)

**선행 의존**  
—

**결정 필요**  
replan의 운전시간 기준은 앱 `current_drive_sec` vs 서버 `accumulated_drive_sec` 중 어느 것을 권위로 할 것인가?

**상태:** `[ ]` 미결정

---

### M4 · `estimated_duration_min` 불일치

| | |
|---|---|
| **ID** | M4 |
| **제목** | `estimated_duration_min` 불일치 |
| **우선순위** | P1 |

**문제**  
응답 `estimated_duration_min`은 GH **행렬 구간 합**이며, 삽입된 휴게 **체류(15분×n)**·polyline 기반 구간 시간과 불일치할 수 있다. 관제 ETA·앱 안내와 괴리가 생긴다.

**배포 영향 (OCI/Docker)**  
Docker 운영에서 관제 모니터링 ETA가 기사 앱·실제 도착과 다르게 보인다.

**관련 파일/위치**  
`backend/app/api/optimize.py` — `estimated_duration_min` 계산  
`backend/app/schemas/optimize.py` — 응답 스키마

**선택지**  
- **A.** 휴게 체류 + polyline/route_time 반영한 **총 소요** 재계산  
- **B.** `driving_min` / `rest_min` 분리 필드  
- **C.** 현행 유지, 문서에 “행렬 합” 명시

**권장 (확정 아님)**  
**B** — breaking 최소화하며 관제·앱 각각 필요 필드 제공

**breaking**  
**Y** 가능(필드 의미·추가)

**선행 의존**  
H2, H3 (휴게 삽입 정책 확정 후)

**결정 필요**  
`estimated_duration_min`에 휴게 체류 시간을 포함할 것인가?

**상태:** `[ ]` 미결정

---

### L2 · `GH_BASE` localhost 하드코딩

| | |
|---|---|
| **ID** | L2 |
| **제목** | `GH_BASE` localhost 하드코딩 |
| **우선순위** | P1 |

**문제**  
`graphhopper.GH_BASE = "http://localhost:8989"` 고정. Docker Compose에서 서비스명(`graphhopper:8989`)·OCI 내부 DNS로 바꾸려면 **코드 수정 또는 환경 변수 미지원**이 필요하다.

**배포 영향 (OCI/Docker)**  
컨테이너 네트워크에서 GH 호스트명이 `localhost`가 아니면 **전면 503** 또는 H2(휴게 polyline) 연쇄 실패가 난다. 현재 배포가 동작 중이라면 우회(네트워크 모드·sidecar)에 의존했을 수 있다.

**관련 파일/위치**  
`backend/app/services/graphhopper.py` — `GH_BASE`  
`backend/.env.example` — GH 관련 환경 변수(미지원 시 추가 필요)

**선택지**  
- **A.** `GH_BASE` **환경 변수** (`backend/.env`)  
- **B.** Docker Compose `extra_hosts`로 localhost 유지  
- **C.** 현행 하드코딩

**권장 (확정 아님)**  
**A** — [README.md](README.md) 로컬·OCI 공통

**breaking**  
**N** (기본값 localhost 유지 가능)

**선행 의존**  
—

**결정 필요**  
`GH_BASE`를 환경 변수로 외부화할 것인가?

**상태:** `[ ]` 미결정

---

## P2 — 정밀도·방어 코드

### M1 · 차량 제원 GH 미반영

| | |
|---|---|
| **ID** | M1 |
| **제목** | 차량 제원 GH 미반영 |
| **우선순위** | P2 |

**문제**  
Trip·요청에 `vehicle_height_m`·`weight_kg` 등이 있으나 GH 호출은 항상 `profile=truck`(정적 `truck_kr` custom model). 차량별 높이·중량 제한 경로가 반영되지 않는다.

**배포 영향 (OCI/Docker)**  
고중량·초대형 차량 운행 시 **실제 통행 불가 경로**가 optimize될 수 있다.

**관련 파일/위치**  
`backend/app/services/graphhopper.py` — `profile=truck`, custom model  
`Engine/` — GraphHopper 프로필·OSM 설정

**선택지**  
- **A.** GH custom model 동적 파라미터  
- **B.** 프로필 프리셋(소형/대형) 선택  
- **C.** MVP: 문서화만, 단일 truck 프로필

**권장 (확정 아님)**  
**C** → 2단계 **B**

**breaking**  
**N** (프로필 추가 시 요청 필드 optional)

**선행 의존**  
—

**결정 필요**  
차량 제원을 GH 경로 탐색에 반영할 범위와 시점은?

**상태:** `[ ]` 미결정

---

### M5 · replan 목적지 중복

| | |
|---|---|
| **ID** | M5 |
| **제목** | replan 목적지 중복 |
| **우선순위** | P2 |

**문제**  
replan에서 TSP `ordered_nodes` 조립 후 **목적지 노드를 한 번 더 append**한다. `final_matrix`·휴게 삽입 입력에 **중복 destination**이 들어갈 수 있다.

**배포 영향 (OCI/Docker)**  
replan route[] 끝에 목적지가 두 번 보이거나, 구간 시간·휴게 위치가 틀어질 수 있다.

**관련 파일/위치**  
`backend/app/api/optimize.py` — replan TSP 결과 조립

**선택지**  
- **A.** TSP 결과만 사용, 중복 append 제거  
- **B.** open-route(목적지 미고정) 모델로 재설계  
- **C.** 현행 + 클라이언트 dedupe

**권장 (확정 아님)**  
**A** — 버그 수정 성격

**breaking**  
**N** (응답 route[] 길이·순서 수정)

**선행 의존**  
—

**결정 필요**  
replan TSP 결과 조립 시 목적지 중복을 코드에서 제거할 것인가?

**상태:** `[ ]` 미결정

---

### M6 · instructions 구간 분할

| | |
|---|---|
| **ID** | M6 |
| **제목** | instructions 구간 분할 |
| **우선순위** | P2 |

**문제**  
다구간 경로에서 polyline을 `segment_times` 비율로 분할할 때 **구간별 GH instructions를 전달하지 않는다**. 턴-by-turn은 Haversine 스케일 폴백으로 휴게 위치가 덜 정밀해진다.

**배포 영향 (OCI/Docker)**  
`/demo/nav-route`·향후 운영 guidance 확장 시 **안내 품질 저하**가 발생한다.

**관련 파일/위치**  
`backend/app/services/rest_stop_inserter.py` — 다구간 분할  
`backend/app/api/demo.py` — `nav-route`  
`backend/app/services/graphhopper.py` — instructions 처리

**선택지**  
- **A.** 전체 경로 단일 GH 호출 + instructions 유지  
- **B.** 구간별 instructions 재매핑  
- **C.** 휴게 삽입 후 GH **재호출**(demo nav-route 방식)

**권장 (확정 아님)**  
**C** — demo 계약과 정합 (§3.6.3)

**breaking**  
**N** (내부 정밀도); 운영 API 확장 시 **Y**

**선행 의존**  
H2

**결정 필요**  
다구간 휴게 삽입 시 instructions를 구간 분할할 것인가, 휴게 후 GH 재호출할 것인가?

**상태:** `[ ]` 미결정

---

### M7 · 전국 휴게소 폴백

| | |
|---|---|
| **ID** | M7 |
| **제목** | 전국 휴게소 폴백 |
| **우선순위** | P2 |

**문제**  
`polyline`이 비어 있으면 `filter_rest_by_route`를 건너뛰고 **전국 active 휴게소 DB**를 후보로 쓴다(H2와 연동). 부적절한 원거리 휴게소 선택·성능 저하가 발생한다.

**배포 영향 (OCI/Docker)**  
GH geometry 실패 시 **엉뚱한 휴게소**가 route[]에 들어갈 수 있다.

**관련 파일/위치**  
`backend/app/api/optimize.py` — `filter_rest_by_route` 조건  
`backend/app/services/graphhopper.py` — `filter_rest_by_route`

**선택지**  
- **A.** polyline 없으면 휴게 후보 **빈 집합**(삽입 안 함)  
- **B.** 현재 위치·다음 경유지 bbox만  
- **C.** 현행 전국 폴백

**권장 (확정 아님)**  
**B** — H2 정책과 함께

**breaking**  
**N**

**선행 의존**  
H2

**결정 필요**  
polyline 없을 때 휴게 후보를 전국 DB로 폴백할 것인가?

**상태:** `[ ]` 미결정

---

### M8 · cargo N:M 제약

| | |
|---|---|
| **ID** | M8 |
| **제목** | cargo N:M 제약 |
| **우선순위** | P2 |

**문제**  
`_build_cargo_pickup_deliveries`는 cargo당 pickup 1·delivery 1 쌍을 가정한다. 테스트에 **1 pickup · N delivery** 케이스가 있으나 OR-Tools pickup-delivery는 **1:1** 제약. 복수 하차·복수 상차 계약이 불명확하다.

**배포 영향 (OCI/Docker)**  
관제에서 한 화물·복수 하차 콜 입력 시 **잘못된 순서 또는 422**가 발생할 수 있다.

**관련 파일/위치**  
`backend/app/api/optimize.py` — `_build_cargo_pickup_deliveries`  
`backend/tests/` — cargo 제약 테스트

**선택지**  
- **A.** 1:1만 공식 지원, N:M은 422  
- **B.** pickup 1 → deliveries N 순차 방문 제약 추가  
- **C.** VRP capacity·분할 배송 모델

**권장 (확정 아님)**  
**A** 단기 + SCHEMA에 명시; **B**는 수요 확인 후

**breaking**  
**Y** 가능(N:M 허용 시 요청·검증 변경)

**선행 의존**  
—

**결정 필요**  
cargo 1:N(한 상차·복수 하차)을 공식 API 계약으로 지원할 것인가?

**상태:** `[ ]` 미결정

---

## P3 — 문서·확장·low

### L1 · GH 구간 캐시

| | |
|---|---|
| **ID** | L1 |
| **제목** | GH 구간 캐시 |
| **우선순위** | P3 |

**문제**  
`_route_cache`는 최대 4000엔트리·LRU 아님. 장시간 프로세스에서 **메모리·스테일 ETA** 가능성이 있다.

**배포 영향 (OCI/Docker)**  
OCI 단일 컨테이너 장기 운영 시 메모리 증가(제한적). 교통 연동(§3.7) 시 캐시 무효화 정책이 필요하다.

**관련 파일/위치**  
`backend/app/services/graphhopper.py` — `_route_cache`, `_ROUTE_CACHE_MAX`

**선택지**  
- **A.** TTL·LRU  
- **B.** 프로세스 재시작 전제  
- **C.** 현행

**권장 (확정 아님)**  
**C** (캡스톤); 2단계 **A**

**breaking**  
**N**

**선행 의존**  
—

**결정 필요**  
GH 구간 캐시에 TTL을 도입할 것인가?

**상태:** `[ ]` 미결정

---

### L3 · N² 행렬 확장성

| | |
|---|---|
| **ID** | L3 |
| **제목** | N² 행렬 확장성 |
| **우선순위** | P3 |

**문제**  
`build_time_matrix`는 O(N²) GH 호출. 경유지 20+ 시 지연·GH 부하가 급증한다.

**배포 영향 (OCI/Docker)**  
Docker 단일 GH 인스턴스에서 **동시 optimize 타임아웃** 위험이 있다.

**관련 파일/위치**  
`backend/app/services/graphhopper.py` — `build_time_matrix`  
`backend/app/api/optimize.py` — 경유지 개수 검증(없으면 추가)

**선택지**  
- **A.** N 상한(예: 15)  
- **B.** Matrix API·청크 병렬  
- **C.** 현행

**권장 (확정 아님)**  
**A** 문서화 + 422

**breaking**  
**Y** 가능(상한 초과 422)

**선행 의존**  
—

**결정 필요**  
경유지 개수 상한을 API 계약으로 둘 것인가?

**상태:** `[ ]` 미결정

---

### L4 · 휴게 후보 없음

| | |
|---|---|
| **ID** | L4 |
| **제목** | 휴게 후보 없음 |
| **우선순위** | P3 |

**문제**  
구간 내 적합 휴게소가 없을 때 greedy 루프가 **삽입 없이 종료**한다. 법정 위반 가능 경로가 200으로 반환될 수 있다.

**배포 영향 (OCI/Docker)**  
휴게 DB 미커버 지역·고속도로 외 구간에서 **운행 불가 안내 없음**.

**관련 파일/위치**  
`backend/app/services/rest_stop_inserter.py` — greedy 삽입 루프

**선택지**  
- **A.** 후보 없으면 422 + 사유  
- **B.** 가장 가까운 전국 후보 1개 + `warnings`  
- **C.** 현행

**권장 (확정 아님)**  
**B** + `warnings`

**breaking**  
**N**

**선행 의존**  
M7, H3

**결정 필요**  
휴게 후보가 없을 때 422로 거부할 것인가, 경고와 함께 최선 후보를 넣을 것인가?

**상태:** `[ ]` 미결정

---

### L5 · `cargo_weight` 미사용

| | |
|---|---|
| **ID** | L5 |
| **제목** | `cargo_weight` 미사용 |
| **우선순위** | P3 |

**문제**  
`demo` 요청에 `cargo_weight_kg`가 있으나 optimize·TSP·GH에 **미전달**. 적재·프로필 제약과 무관하다.

**배포 영향 (OCI/Docker)**  
과적·프로필 오류는 운영에서 **사전 차단 불가**.

**관련 파일/위치**  
`backend/app/schemas/optimize.py` — `cargo_weight_kg`  
`backend/app/api/demo.py` — demo 요청

**선택지**  
- **A.** OR-Tools capacity·M1 연동  
- **B.** 필드 deprecated  
- **C.** 문서만 “미사용”

**권장 (확정 아님)**  
**C** → M1·M8 확정 후 **A**

**breaking**  
**N**

**선행 의존**  
M1, M8

**결정 필요**  
`cargo_weight_kg`를 최적화 제약에 반영할 계획이 있는가?

**상태:** `[ ]` 미결정

---

### L6 · `route[]` cargo 메타 누락

| | |
|---|---|
| **ID** | L6 |
| **제목** | `route[]` cargo 메타 누락 |
| **우선순위** | P3 |

**문제**  
요청·`remaining_waypoints`의 `cargo_id`/`cargo_role`이 **응답 `route[]`에 없음**. 앱·관제가 요청과 매칭해야 라벨·검증 가능(§3.6.1·3.6.2).

**배포 영향 (OCI/Docker)**  
기사 앱 자체 내비에서 **상·하차 라벨**·순서 검증 UX가 어렵다.

**관련 파일/위치**  
`backend/app/schemas/optimize.py` — `RouteNode`  
`backend/app/api/optimize.py` — route[] 조립

**선택지**  
- **A.** `RouteNode`에 optional `cargo_id`/`cargo_role` 추가  
- **B.** 클라이언트가 요청 캐시로 매칭  
- **C.** Trip guidance 별도 API

**권장 (확정 아님)**  
**A** — §3.6.3 A 후보와 동시

**breaking**  
**N** (additive)

**선행 의존**  
—

**결정 필요**  
optimize/replan 응답 `route[]`에 `cargo_id`/`cargo_role`을 포함할 것인가?

**상태:** `[ ]` 미결정

---

## 권장 결정 순서

P0부터 순차 확정하는 것을 권장합니다. 선행 의존이 있는 항목은 아래 순서 내에서 먼저 결정하세요.

1. **H3** — 6000–7200초 휴게 갭 (법정 준수, L4 선행)
2. **H2** — polyline 실패 시 휴게 정책 (M4·M6·M7 선행)
3. **L2** — `GH_BASE` 환경 변수 (OCI 네트워크 안정)
4. **M3** — `current_drive_sec` 권위
5. **M2** — replan 시간창 기준
6. **M4** — `estimated_duration_min` 의미 (H2·H3 이후)
7. **M5** — replan 목적지 중복
8. **M1** · **M8** — 차량 제원·cargo N:M (L5 선행)
9. **M6** · **M7** — instructions·휴게 후보 폴백 (H2 이후)
10. **L1** · **L3** · **L4** · **L5** · **L6** — 확장·문서·additive 필드

확정·구현완료 항목은 본 문서에서 제거하고, 구현·API 계약은 [SCHEMA.md](SCHEMA.md)·[CHANGELOG.md](CHANGELOG.md)에 반영합니다. 미결 항목은 `**상태:**` 줄을 갱신합니다.

---

## 문서 동기화

- **구현·결정 반영 시** 해당 항목 `**상태:**` 줄을 갱신하고, 소스·테스트와 **같은 커밋 1회**에 포함한다.
- **구현완료** 항목은 BUGREPORT에서 제거하고 이력은 [CHANGELOG.md](CHANGELOG.md)「요약」·「최근 주요 변경」·커밋 이력에만 남긴다. BUGREPORT-only 2번째 커밋은 하지 않는다.
- 경로→이슈 힌트: `graphhopper.py`→H2(polyline)·L2, `rest_stop_inserter`→H2/H3, `replan`·`route_pipeline`→M2/M5, `config.py`(`GH_BASE`)→L2.
- (선택) `git config core.hooksPath .githooks` 후 pre-commit이 staged 백엔드 변경 대비 `BUGREPORT.md` 누락을 **경고**한다 — [`.githooks/README`](.githooks/README).

---

## 참고 — `POST /optimize/` 2모드 (2026-06-11)

`optimize_mode`: `basic`(휴게 삽입 생략·요청 순서 고정) \| `with_rest`(기본, TSP+휴게). 전용 엔드포인트 `POST /optimize/basic`, `POST /optimize/with-rest`(요청 `optimize_mode` 무시). `replan`은 with_rest 계열. 상세는 [PLAN.md](PLAN.md) §3.4.1–3.4.2·[SCHEMA.md](SCHEMA.md).
