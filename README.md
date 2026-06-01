# RouteOn (루트온)

화물차 운행 경로를 최적화하면서 **법정 휴게 규정을 자동 반영**하는 물류 관제 시스템입니다.

## 0. 팀 역할 분담

이 저장소의 **핵심 개발 범위는 경로 최적화 알고리즘**입니다. 관제 웹·기사 앱은 **각각 다른 담당**이 개발하며, 여기서는 API 계약과 알고리즘 구현을 유지합니다.

| 영역 | 담당 | 이 repo 경로 | 기술·연동 |
|------|------|--------------|-----------|
| **알고리즘** | 본 프로젝트 (핵심) | `backend/app/services/`, `backend/app/api/optimize.py`, `demo.py`, `Engine/`, `backend/tests/` | GraphHopper, OR-Tools TSP/VRP, 법정 휴게 삽입, Kakao Mobility(백엔드) |
| **관제 웹** | 별도 담당 | `frontend_Test/` (연동·참고용) | Kakao **지도 API** — 노드 입력·경로 표시·관제 |
| **기사 앱** | 별도 담당 | *(별도 앱 저장소)* | Kakao **내비 SDK** — `route` 기반 주행, 위치 로그·replan |

### 알고리즘 ↔ 클라이언트 API 계약 (웹·앱 팀 공유)

| 항목 | 설명 |
|------|------|
| 방문 순서·휴게소 | **백엔드만** 계산. 웹·앱은 `POST /optimize/`·`/demo/route`·`/optimize/replan` 응답 `route`를 표시·내비 연동 |
| 응답 경로 계약 | 웹·앱의 핵심 계약은 `route[]`의 **순서**와 각 노드의 `lat`/`lon`입니다. `polyline`은 `/optimize/dispatch` 등에서 있을 수 있는 선택 디버그 필드이며 실서비스 표시·내비 계약이 아닙니다. |
| 노드 목록 | 관제 → 기사 앱 전달 (상·하차·경유 좌표·`cargo_id` 등) |
| 출발·도착 | **기사 앱**이 `/optimize/`·`/replan` 요청 시 `origin_*`·`dest_*` (또는 replan 시 `current_*`·`dest_*`) 전달 |
| 다중 상·하차 | `cargo_id` + `cargo_role`: `pickup` / `delivery` — `/optimize/`, `/demo/route`, **`/optimize/replan`의 `remaining_waypoints` 동일** |
| 재탐색 | `POST /location-logs/` 응답 `needs_replan` → 앱이 `/optimize/replan` 호출 (`current_drive_sec` 포함) |

상세 API는 [§8 API 요약](#8-api-요약), 스키마는 `/docs`(Swagger)를 기준으로 합니다.

## 1. 시스템 구성

```
┌──────────────────────────────────┐      ┌─────────────────────┐
│         관제 웹 (Web)            │      │   기사 앱 (Mobile)   │
│  - 관리자 전용 · 입력·관제        │      │  - 운전기사/용차 공용 │
│  - 지도: Kakao 지도 API           │      │  - 주행: Kakao 내비 SDK│
│  - 상·하차·경유 노드 목록 입력    │      │  - 노드 목록 수신     │
│  - 엔진 결과 경로 조회·모니터링  │      │  - 출발지·도착지 선택 │
│  - 운행 중 추가 노드 지시 가능    │      │  - 엔진 결과 경로 표시│
│                                  │      │  - 재탐색·위치 로그   │
└────────┬─────────────────────────┘      └──────────┬──────────┘
         │                                           │
         └──────────────┬─────────────────────────────┘
                        ▼
         ┌──────────────────────────────┐
         │      FastAPI 백엔드 (8000)    │
         │  - 경로 최적화 API            │
         │  - 방문 순서·휴게소 (엔진)    │
         │  - 운행·차량·기사 CRUD        │
         └──────────────┬───────────────┘
                        │
           ┌────────────┴────────────┐
           ▼                         ▼
┌──────────────────┐     ┌───────────────────────┐
│  GraphHopper     │     │  Kakao Mobility API   │
│  엔진 (8989)     │     │  · 실시간 교통 반영    │
│  (정적 OSM)      │     │  · 미래 시간대 예측    │
│                  │     │    (departure_time)   │
│                  │     └───────────────────────┘
│  역할:           │
│  · 화물차 전용   │
│    도로 그래프   │
│    (높이/중량/   │
│    차폭 제한     │
│    반영)         │
│  · 두 지점 간    │
│    실제 경로     │
│    거리·시간     │
│    계산          │
│  · 한국 전체     │
│    OSM 기반      │
└──────────────────┘
```

### 클라이언트 역할 (웹 · 앱)

| | 관제 웹 | 기사 앱 |
|---|---|---|
| **지도/주행** | [Kakao 지도 API](https://apis.map.kakao.com/) — 노드 입력·방문 순서 **표시** | [Kakao 내비 SDK](https://developers.kakao.com/docs/latest/ko/kakaonavi/common) — 턴바이턴 **실주행 내비** |
| **관제 웹이 하는 일** | 상·하차·경유 **노드 목록** 입력, 배차·지시, 기사에게 내려간 경로 **조회·모니터링** | — |
| **기사 앱이 하는 일** | — | 관제에서 받은 **노드 목록** + 기사가 고른 **출발지·도착지**로 최적화 요청 |
| **방문 순서** | 백엔드 엔진이 계산 → 웹·앱 **동일 경로** 표시 | 동일 |

> **「기사가 경로를 선택」** = 경유 **순서**를 고르는 것이 아니라 **출발지·도착지**를 정하는 것입니다. 출발·도착이 바뀌면 전체 경로가 달라지며, 상·하차·경유지의 **방문 순서와 휴게소 위치는 항상 백엔드 엔진**이 계산합니다.

### 엔진(GraphHopper)이 하는 일

TSP 행렬을 구성하려면 N개 노드에 대해 **N²-N번의 구간 거리·시간**이 필요합니다. 이를 Kakao API로 채우면 경유지가 늘수록 호출 수가 폭발적으로 증가해 API 비용과 QPS 제한(10 req/s)이 병목이 됩니다.

GraphHopper는 한국 전체 OSM 도로 데이터를 클라우드 서버에 빌드해두고, 두 지점 간 경로를 **API 호출 없이** 직접 계산합니다. 클라우드 컴퓨팅 비용이 API 호출 비용보다 저렴하므로, TSP 행렬 계산은 GraphHopper로 처리하고 **Kakao Mobility API(백엔드)** 는 실시간 교통이 반드시 필요한 재탐색·ETA 조회에만 사용합니다. (지도 표시·차량 내비는 각각 **Kakao 지도 API · Kakao 내비 SDK** — 위 표 참고)

| | GraphHopper | Kakao Mobility (백엔드) | Kakao 지도 API (웹) | Kakao 내비 SDK (앱) |
|---|---|---|---|---|
| TSP 행렬·휴게 삽입 | ✅ | △ 재탐색·ETA | — | — |
| 실시간 교통 | ❌ 정적 OSM | ✅ | — | ✅ (주행 시) |
| 미래 시간대 예측 | ❌ | ✅ (`departure_time`) | — | — |
| 지도·경로 표시 | — | — | ✅ 관제 웹 | — |
| 턴바이턴 내비 | — | — | — | ✅ 기사 앱 |

**경유지별 TSP 호출 수 (Kakao로 행렬을 채울 경우):**

| 경유지 수 | 노드 수 | TSP 호출 수 |
|---|---|---|
| 3개 | 5 | 20번 |
| 5개 | 7 | 42번 |
| 10개 | 12 | 132번 |

Oracle Cloud A1 Flex Always Free (4 OCPU · 24 GB RAM) 컴퓨팅 비용: **월 $0**.  
하루 배차 100건 × 경유지 5개 기준 → 월 약 126,000건 소비, Kakao 무료 한도(300,000건)를 금방 소진합니다.

## 2. 최적화 파이프라인

```
노드 입력 (출발·경유·도착)
        ↓
GraphHopper N²-N 쌍 호출 → 시간/거리 행렬
        ↓
OR-Tools TSP → 최적 방문 순서 (출발·도착 고정)
        ↓
법정 휴게소 삽입 (내부 GraphHopper 폴리라인 기반 균등 배분)
  · 전체 경로 시간 ÷ MAX_DRIVE_SEC → 필요 휴게소 수 선계산
  · 내부 폴리라인 위 균등 시간 지점 추출 → 폴리라인 투영 상위 K개 후보
  · GraphHopper (구간 prev→휴게→next) 실제 우회 시간 최소 선택 (캐시·병렬)
  · 방향·타입 우선순위(truck > highway > drowsy), GH 실패 시 Haversine 폴백
  · 경유지 존재 시 구간별 독립 평가, 경유지에서 누적 운전시간 리셋
        ↓
optimized_route JSONB 저장 → 응답
```

## 3. 법정 상수 (변경 금지)

`backend/app/services/rest_stop_inserter.py` 기준:

```python
REST_PLAN_SEC        = 6_000   # 1시간 40분 — 선제적 휴게 삽입 임계값
MAX_DRIVE_SEC        = 7_200   # 2시간 — 법정 최대 연속 운전
MIN_REST_MIN         = 15      # 법정 최소 휴식 시간(분)
EMERGENCY_EXTEND_SEC = 3_600   # 긴급 예외: 최대 3시간 연속 운전
EMERGENCY_REST_MIN   = 30      # 긴급 예외 시 최소 휴식(분)
```

## 4. 디렉토리 구조

```
Capstone-ii/
├─ README.md
├─ SCHEMA.md
├─ DEPLOY.md              ← Oracle Cloud 배포 가이드
├─ .gitignore
├─ data/                  ← 데모 태스크 원본·생성 CSV/XLSX (README.md 참고)
│  ├─ source/
│  └─ generated/
├─ scripts/               ← generate_fake_logistics_data.py, fill_task_xlsx.py
├─ 자료/                  ← 백엔드 시드용 휴게소·졸음쉼터 등 (seeds/)
│  ├─ 한국도로공사_졸음쉼터_20260225.csv
│  └─ 휴게소정보_260325.xls
├─ Engine/                ← GraphHopper (git 제외: jar, osm, graph-cache)
│  ├─ config.yml
│  ├─ truck_kr.json       ← 화물차 커스텀 모델
│  └─ patch_osm.py        ← 화물차 제한 OSM 패치 스크립트
├─ backend/
│  ├─ requirements.txt
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ api/
│  │  │  ├─ optimize.py
│  │  │  ├─ demo.py       ← DB trip 없는 데모 경로 최적화
│  │  │  ├─ trips.py
│  │  │  ├─ drivers.py
│  │  │  ├─ vehicles.py
│  │  │  ├─ rest_stops.py
│  │  │  └─ location_logs.py
│  │  ├─ core/
│  │  ├─ models/
│  │  ├─ schemas/
│  │  └─ services/
│  │     ├─ graphhopper.py      ← GraphHopper /route 호출
│  │     ├─ kakao.py            ← Kakao Mobility API
│  │     ├─ optimizer.py        ← OR-Tools TSP
│  │     └─ rest_stop_inserter.py ← 법정 휴게소 삽입 (내부 GraphHopper 폴리라인 균등 배분)
│  └─ seeds/
│     ├─ seed_rest_stops.py         ← 졸음쉼터 CSV 시드
│     └─ sync_xls_rest_stops.py     ← XLS 기반 truck_rest 동기화
├─ frontend_Test/         ← 관제 웹 (별도 담당 · Kakao 지도 API · 연동 테스트)
└─ (기사 앱)              ← 별도 저장소 · Kakao 내비 SDK
```

## 5. 구현 범위

**완료:**
- 단일 차량 경로 최적화: `POST /optimize/`
- 운행 중 재최적화: `POST /optimize/replan`
- DB trip 없는 데모 최적화: `POST /demo/route`
- 운행·차량·기사·휴게소·위치 로그 CRUD
- 법정 휴게소 자동 삽입 (내부 GraphHopper 폴리라인 균등 배분 + 방향 필터 + 타입 우선순위)
- GraphHopper 화물차 라우팅 엔진 연동
- Kakao `departure_time` 기반 미래 교통 반영
- truck_rest 휴게소 DB 79건 (XLS 전수 검증 완료)
- 위치 로그 기반 누적 운전시간 추적 (`accumulated_drive_sec`) 및 재경로 트리거 플래그 (`needs_replan`)

**미구현 (계산 이후 단계):**
- 다차량 VRPTW 결과의 **DB 저장 파이프라인** (`dispatch_orders` → `Trip` / `DispatchGroup` 반영, §17·`PLAN.md` Phase 1). `POST /optimize/dispatch`는 **OR-Tools VRPTW + 응답 반환**까지 구현됨.

## 6. 로컬 실행

### 사전 요구사항
- Python 3.11+
- PostgreSQL 14+
- Java 21+ (GraphHopper용)

### GraphHopper 엔진 실행

```bash
cd Engine

# 최초 1회: OSM 다운로드 + 화물차 패치 + graph-cache 빌드 (~15분)
# (south-korea-latest.osm.pbf는 .gitignore 대상 — 직접 다운로드 필요)
wget https://download.geofabrik.de/asia/south-korea-latest.osm.pbf

# 국가표준노드링크 다운로드 (.gitignore 대상 — 직접 다운로드 필요)
# ITS 국가교통정보센터: https://www.its.go.kr/opendata/nodelinkFileSDownload/DF_210/0
# 다운로드 후 압축 해제 → Engine/[날짜]NODELINKDATA/ 폴더에 MOCT_LINK.shp 등 위치
# patch_osm.py의 MOCT_SHP 경로가 해당 폴더를 가리키도록 확인

python ../Engine/patch_osm.py   # → south-korea-patched.osm.pbf 생성
# graphhopper-web-10.0.jar도 직접 다운로드 필요 (GitHub Releases)

java -Xmx4g -jar graphhopper-web-10.0.jar server config.yml
# http://localhost:8989 에서 기동 확인
```

### FastAPI 백엔드 실행

```bash
cd backend
python -m venv ../.venv
# Windows PowerShell
../.venv/Scripts/Activate.ps1

pip install -r requirements.txt

# .env 작성
cp .env.example .env   # 없으면 직접 생성 (아래 6.1 참고)

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

접속:
- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- Health: http://localhost:8000/health

### 6.1 환경 변수 (`backend/.env`)

```env
DATABASE_URL=postgresql+asyncpg://routeon:routeon@localhost:5432/routeon
KAKAO_API_KEY=카카오_REST_API_키          # 백엔드 — Kakao Mobility (길찾기·재탐색)
SECRET_KEY=CHANGE_ME_IN_PRODUCTION   ← 운영 시 반드시 교체
DEBUG=false
```

관제 웹·기사 앱은 백엔드 `.env`와 **별도 키**를 사용합니다.

| 클라이언트 | 키 종류 | 용도 |
|---|---|---|
| 관제 웹 | JavaScript 키 (Kakao 지도 API) | 지도 렌더링, 노드 마커·방문 순서 표시 |
| 기사 앱 | 네이티브 앱 키 (Kakao 내비 SDK) | 확정 경로 턴바이턴 내비 연동 |
| 백엔드 | REST API 키 (`KAKAO_API_KEY`) | Mobility API — 행렬·재탐색·시드 지오코딩 |

## 7. 데이터베이스 시드

```bash
cd backend

# 졸음쉼터 CSV 시드 (drowsy_shelter)
python seeds/seed_rest_stops.py

# truck_rest 휴게소 XLS 동기화 (Kakao 지오코딩 사용)
python seeds/sync_xls_rest_stops.py
```

- CSV 인코딩: `euc-kr` 자동 처리
- truck_rest는 현재 DB에 79건 적재 완료

## 8. API 요약

| 엔드포인트 | 메서드 | 설명 |
|---|---|---|
| `/optimize/` | POST | 경로 최적화 (trip_id 기반) |
| `/optimize/replan` | POST | 운행 중 재최적화 |
| `/optimize/dispatch` | POST | 다차량 VRPTW 일괄 배차 (응답만; DB 미저장 — Phase 1). **depot 선택**, 차량별 `start_lat`/`start_lon`, `end_policy`(`open_end` 기본). 차량별 `route[]` 순서·`lat`/`lon`이 계약 중심이며 `polyline`은 선택 디버그 필드 |
| `/demo/route` | POST | DB 없는 데모 최적화 |
| `/trips/` | GET/POST | 운행 목록·생성 |
| `/trips/{id}/status` | PATCH | 운행 상태 변경 |
| `/vehicles/` | GET/POST/PATCH | 차량 CRUD |
| `/drivers/` | GET/POST | 기사 CRUD |
| `/rest-stops/` | GET/POST/DELETE | 휴게소 CRUD |
| `/location-logs/` | GET/POST | 위치 로그 — POST 응답에 `accumulated_drive_sec`, `needs_replan` 포함 |
| `/health` | GET | 헬스체크 |

**시간창 (optimize / replan / dispatch / demo 공통)**

- 요청: `reference_departure_at` (ISO-8601) — 모든 상대 변환의 기준 출발 시각. 미지정 시 `trip.departure_time`(optimize) 또는 현재 시각(Asia/Seoul).
- 노드: `earliest_at` / `latest_at` (ISO, 개점·마감) 또는 `tw_open` / `tw_close` (`HH:MM`, 선택 `service_date`) — **캘린더 필드가 `earliest_sec`/`latest_sec`보다 우선**.
- 하위 호환: `earliest_sec` / `latest_sec` (출발 기준 경과 초)만내도 동작. demo의 `time_window` (분)는 deprecated.

**일괄 배차 (`POST /optimize/dispatch`)**

- **depot (선택):** `depot_name` / `depot_lat` / `depot_lon` 을 생략할 수 있습니다. 미지정 시 공통 창고·기지 노드를 행렬에 넣지 않습니다.
- **차량 출발:** `vehicles[]` 마다 `start_lat` / `start_lon` — 당일 첫 출발지·기사·차량 현재 위치 등. depot 없이도 배차 요청이 가능합니다.
- **종료 정책:** 차량별 `end_policy` — `open_end`(기본, **지입·분산** 배송: 마지막 배송지에서 종료, 복귀 구간 없음) / `return_to_depot`(기지·창고 복귀).
- **직영(레거시) 창고 복귀:** 요청에 **depot을 포함**하고 해당 차량의 `end_policy`를 `return_to_depot`으로 두면, 기존 **직영 물류센터 왕복**(`depot` → 배송지 → `depot`) 모델과 같습니다.
- **Breaking:** 기존 클라이언트가 이전처럼 `depot_*`만내도 **호환**됩니다(동작은 전달한 `end_policy`·차량 출발 좌표에 따름).

## 9. 데모 경로 최적화 (DB 없이 테스트)

trip을 만들지 않고 노드 좌표만으로 즉시 경로 + 휴게소 삽입 결과를 확인합니다.

### 기본 사용 패턴 — 상차지 + 하차지 2개

관제 웹은 **상·하차·경유 노드 목록**을 입력하고, 엔진이 계산한 경로를 **Kakao 지도 API**로 미리 확인합니다.  
**노드 목록**을 기사 앱으로 전달하고, 기사는 **출발지·도착지**를 선택한 뒤 최적화를 요청합니다. 방문 **순서·휴게소**는 백엔드가 정하며, 결과는 웹·앱에 동일하게 표시됩니다. 기사 앱에서는 **Kakao 내비 SDK**로 주행합니다.  
운행 중 추가 경유지가 필요하면 관제가 노드만 추가 전달하고, 기사 앱이 **현재 위치·누적 운전시간** 기준으로 `replan`을 호출합니다.

```bash
curl -s -X POST http://localhost:8000/demo/route \
  -H 'Content-Type: application/json' \
  -d '{
    "profile": "truck",
    "nodes": [
      {"name": "상차지 — 인천 물류센터", "lat": 37.4563, "lon": 126.7052},
      {"name": "하차지 — 부산 물류단지", "lat": 35.1796, "lon": 129.0756}
    ]
  }' | python -m json.tool
```

### 경유지 추가 (다중 납품)

상차지에서 화물을 싣고 여러 하차지에 순차 납품할 때 같은 `cargo_id`로 상·하차 역할을 지정합니다 (`/optimize/`·`/demo/route`·`/optimize/replan` 공통).

```bash
curl -s -X POST http://localhost:8000/demo/route \
  -H 'Content-Type: application/json' \
  -d '{
    "profile": "truck",
    "nodes": [
      {"name": "상차지 — 인천 물류센터",  "lat": 37.4563, "lon": 126.7052},
      {"name": "상차 — 인천", "lat": 37.4563, "lon": 126.7052, "cargo_id": "A", "cargo_role": "pickup"},
      {"name": "하차지1 — 대전", "lat": 36.3504, "lon": 127.3845, "cargo_id": "A", "cargo_role": "delivery"},
      {"name": "하차지2 — 부산", "lat": 35.1796, "lon": 129.0756, "cargo_id": "A", "cargo_role": "delivery"}
    ]
  }' | python -m json.tool
```

## 10. 관제 웹 UI 사용법

지도는 **Kakao 지도 API**, 주행 내비는 기사 앱의 **Kakao 내비 SDK**를 사용합니다. (`http://localhost:8000/map/` 접속)

1. **상차지 버튼** 클릭 → 지도에서 화물을 싣는 지점 클릭
2. **하차지 버튼** 클릭 → 지도에서 화물을 내리는 지점 클릭
3. (선택) **경유지 버튼**으로 추가 경유지 삽입, ⚙ 버튼으로 도착 시각 제약·상차→하차 연결 설정
4. **경로 계산** → 백엔드가 방문 순서·휴게소를 계산 → 지도에 노드와 순서 표시
5. **노드 목록을 기사 앱으로 전달** → 기사가 **출발지·도착지** 선택 후 동일 엔진 결과로 주행

**운행 중 추가 경유지 지시:**

관리자가 "중간에 A 창고도 들러주세요"가 필요할 때:
- 관제: 추가 **노드**만 기사 앱으로 전달 (순서는 지정하지 않음)
- 기사 앱: **현재 위치**(`current_lat/lon`)·**누적 운전시간**(`current_drive_sec`)·출발/도착으로 `POST /optimize/replan` 호출
- 백엔드: 새 순서·휴게소 계산 → 웹(지도 API)·앱(내비 SDK)에 동일 경로 반영

## 11. 최적화 요청 예시

### Trip 기반 최적화

```json
POST /optimize/
{
  "trip_id": 1,
  "origin_name": "서울 자택",
  "origin_lat": 37.5665,
  "origin_lon": 126.978,
  "initial_drive_sec": 0,
  "route_mode": "long_distance"
}
```

### 운행 중 위치 전송 (30초 간격)

```json
POST /location-logs/
{
  "trip_id": 1,
  "latitude": 36.1234,
  "longitude": 127.4567,
  "speed_kmh": 90.0
}
```

응답:
```json
{
  "accumulated_drive_sec": 6200,
  "needs_replan": true
}
```

- `accumulated_drive_sec`: 서버 타임스탬프 기준 누적 연속 운전시간(초). 폰 시간 조작 차단
- `needs_replan`: `accumulated_drive_sec >= REST_PLAN_SEC(6000)` 이면 `true` → 앱이 `POST /optimize/replan` 자동 호출
- `resting` 상태가 15분 이상 지속되면 누적 리셋 (법정 최소 휴식 충족)

### 운행 중 재탐색

`remaining_waypoints`에도 `cargo_id`·`cargo_role`(또는 `stop_type`)을 넣으면 `/optimize/`와 동일하게 상차→하차 순서 제약이 적용됩니다.

```json
POST /optimize/replan
{
  "trip_id": 1,
  "current_lat": 36.1234,
  "current_lon": 127.4567,
  "current_name": "현재위치",
  "current_drive_sec": 5400,
  "remaining_waypoints": [
    {"name": "대구 상차", "lat": 35.87, "lon": 128.60, "cargo_id": "A", "cargo_role": "pickup"},
    {"name": "부산 하차", "lat": 35.18, "lon": 129.08, "cargo_id": "A", "cargo_role": "delivery"}
  ],
  "dest_name": "부산 물류단지",
  "dest_lat": 35.1796,
  "dest_lon": 129.0756,
  "is_emergency": false,
  "route_mode": "long_distance"
}
```

## 12. 테스트

```bash
cd backend
pytest -q
```

- `tests/test_route_pipeline.py` — TSP + 휴게소 삽입 파이프라인
- `tests/test_vrptw.py` — VRPTW(`solve_vrptw`) 단위 테스트; GraphHopper 불필요
- `tests/test_cargo_pairs.py` — 상차·하차 쌍 제약
- `tests/test_time_windows.py` — 캘린더 시간창 → 경과 초 변환

## 13. 주의사항

- GraphHopper가 `localhost:8989`에서 실행 중이어야 `/optimize/`, `/demo/route` 동작
- Kakao API 무료 플랜 10 QPS 제한 — 경유지 4개 초과 시 429 발생 가능
- Kakao 좌표 파라미터는 `lon,lat` 순서 (경도 먼저)
- `SECRET_KEY` 기본값은 운영 전 반드시 교체
- DB 스키마 변경 시 `SCHEMA.md`, `seeds/init_tables.sql`, `models/` 동기화 필요

## 14. 배포

Oracle Cloud 배포 절차는 [DEPLOY.md](DEPLOY.md) 참고.

## 15. 참고 문서

- DB 스키마: [SCHEMA.md](SCHEMA.md)
- DDL: [backend/seeds/init_tables.sql](backend/seeds/init_tables.sql)
- 배포 가이드: [DEPLOY.md](DEPLOY.md)

---

## 16. 패치노트

커밋 **일자 기준 최신순**. 파일 단위 상세는 [CHANGELOG.md](CHANGELOG.md) 참고.

> **로컬 미커밋 (작업 트리, 문서화 제외):** `trips.dest_*` nullable·`ReplanRequest` 목적지 Optional, VRPTW/휴게 삽입·파이프라인 테스트·`frontend_Test/` 등 — 커밋 후 해당 일자 항목으로 옮길 것.

### 2026-05-27 (`d5b6f1d`)

- docs: [PLAN.md](PLAN.md) Phase·API 계약·다차량 배차 범위 정리, [SCHEMA.md](SCHEMA.md)·[DEPLOY.md](DEPLOY.md) 소폭 동기화
- docs: 사후 통계(`docs/POST_TRIP_STATS_*`, `docs/mermaid/post_trip_stats*.mmd`)·출발 전 대시보드 mermaid 토론안
- Cursor: `.cursor/agents/*`, [team-roles](.cursor/rules/team-roles.mdc) 팀 역할 규칙
- README·CHANGELOG 갱신 (본 섹션·온보딩 반영)

### 2026-05-13 (`94a971f`)

- **API:** `POST /optimize/dispatch` VRPTW 다차량 배차 구현(기존 501 → 정상). 차량별 `route[]`·휴게 삽입·미배정 노드 반환
- **알고리즘:** `solve_vrptw()` — 시간창·`max_load_kg` 용량·차량당 방문 수 균등화·미배정 드롭
- **스키마:** `pickup_id`/`delivery_for` → `cargo_id` + `cargo_role` (`pickup`/`delivery`). 동일 `cargo_id` pickup×delivery **N:M** OR-Tools 제약(`_cargo_pickups` / `_cargo_deliveries`)
- **단건 최적화:** 목적지 미지정 시 마지막 delivery를 목적지로 자동 승격
- **GraphHopper:** 도로 불가 등 400 → HTTP **422**; 연결 실패 503. `build_time_matrix` 거리 행렬 추가 반환
- **모델:** `Vehicle.max_load_kg`, 데모 노드 `cargo_weight_kg` 등
- **정리:** 카카오 API 통합 테스트·copilot 임시 파일 제거

### 2026-05-03

- (`77d1322`) DEPLOY·README 보완, Engine CSV 경로 정리
- (`605aba7`) GraphHopper 엔진 버전·설정 조정
- (`4b1fe1e`) 카카오 경로 API 의존 제거(엔진·휴게 로직 GraphHopper 중심으로 이전)
- (`03fec5e`) README·DEPLOY 대폭 정리, 데모·휴게 삽입·관제 `frontend/index.html` 개선, 적용/테스트 이슈 수정
- (`ff92fdb`) **GraphHopper 자체 호스팅** 연동(`Engine/`, `DEPLOY.md`), 고속도로·휴게 시드, `graphhopper.py`·`rest_stop_inserter.py` 개편, 데모 API
- (`635b670`) 실험용 웹 내비 페이지
- 기타 (`0c93565`, `2d9455f` 등): 작업용·잡다한 정리

### 2026-05-02 (`9eaef5e`)

- 상·하차 동일 `cargo_id`로 pickup–delivery 쌍 매핑 정리
- 경로 파이프라인 테스트(`test_route_pipeline`) 보강

### 2026-04-29

- (`9a75718`) OR-Tools **시간창**(`earliest_sec`/`latest_sec`) 제약 추가
- (`9730733`) 휴게소(쉼터) 검색·시드 방식 변경, 파이프라인 테스트 확장

### 2026-04-15

- (`3e8df32`) 고속도로 구간 휴게 검색을 **고속도로 API** 기반으로 전환, 시드·삽입 로직 수정
- (`1cbf0e4`) 불필요 파일·코드 정리

### 2026-04-08 · 2026-04-04

- (`f763dba`, `78aa91f`, `ce883bc`) 병합·런타임 오류 수정

### 2026-04-01

- (`059da26`) 구간 비용을 **거리 비례**로 변경, README 구조 정리
- (`bbe9298`) 지역 내 루트·휴게 검색, 차량 타입, 카카오 연동 테스트 확대
- (`c6abf48`) Kakao 시간 행렬 → **시간·거리 행렬**, 통합 테스트 추가
- (`9d81ea2`) 경로 검색 **1시간 캐시**, 다중 목적지 API로 휴게소 후보 검색
- (`733dd18`, `27628a5`, `bce0c4a` 등) 공영차고지 제외·다중 목적지 지역 최적화·예제 API·버그 수정·테스트 분리

### 2026-03-31 (`0c1b503`)

- 카카오 API 전환 후 백엔드·스키마(`SCHEMA.md` 루트 이동) 재구성

### 2026-03-27 (`08f987a`)

- 상·하행(센터·배송지) 데이터 모델·스키마 초안 추가

### 2026-03-25 (`bf20074`)

- **KDU_RouteOn** 최초 커밋: FastAPI 백엔드, OR-Tools 단건 최적화, Tmap 데모, Docker·시드·인증·Trip CRUD 골격

---

## 17. 확장 계획 — 다차량 자동 배차 (VRPTW)

### 배경

현재 구조는 관리자가 **차량 1대 = Trip 1건**을 수동으로 생성하는 방식입니다.  
중소 물류회사(직고용 기사 10~30명) 환경에서는 매일 배송지 10~20곳을 가용 차량에 자동 분배하는 기능이 필요합니다.

**목표 흐름:**
```
관리자: 오늘 배송지 N곳 + 가용 차량 M대 입력
              ↓
        VRPTW 자동 계산
        · 차량별 담당 배송지 자동 분배 (적재 용량 + 시간창 제약)
        · 각 차량의 최적 방문 순서 계산
        · 법정 휴게소 자동 삽입
              ↓
        DispatchGroup 1건 생성 + 차량별 Trip 자동 생성
              ↓
        기사 앱 Push → 노드 목록 수신 · 출발/도착 선택 → 엔진 경로 확인 · Kakao 내비 SDK 주행
```

**현재 단계:** 위 흐름 중 **VRPTW 계산·응답**(`POST /optimize/dispatch`)과 차량별 `route[]` 순서·휴게 삽입까지는 구현되어 있다. 일괄 배차는 **depot 없이** 차량별 `start_lat`/`start_lon` 출발·`end_policy`=`open_end`(지입·분산 기본)를 지원하며, **depot + `return_to_depot`** 조합은 직영 창고 왕복(레거시)이다. 응답의 `polyline`은 개발/테스트 확인용 선택 필드이며, 앱·웹 계약은 `route[]`의 방문 순서와 `lat`/`lon` 좌표를 기준으로 한다. **DispatchGroup·주문 테이블과의 연동, 차량별 Trip 자동 저장, Push** 등은 [PLAN.md](PLAN.md) Phase 1·§8 범위다.

### 현재 준비된 스키마

```
DispatchGroup (배차 묶음)
├── id, title, admin_id, scheduled_at, note
└── status: draft → dispatched → in_progress → completed

Trip (단건 운행)
└── dispatch_group_id → DispatchGroup (FK)

Vehicle
└── max_load_kg: float | None  ← 최대 적재 중량 (v0.4 추가)

ExtraStopSchema / DemoNode
└── cargo_weight_kg: float | None  ← 노드별 상차(+)/하차(-) 무게 (v0.4 추가)
```

### 구현 필요 항목

#### 백엔드

| 항목 | 설명 |
|---|---|
| `POST /optimize/dispatch` **영속화** | 계산 결과 → `dispatch_orders` / 차량별 `Trip` 저장 (`PLAN.md` Phase 1) |
| 적재 용량 | 요청의 `cargo_weight_kg`/`max_load_kg` — `AddDimensionWithVehicleCapacity` 적용됨 |
| VRPTW Time Window | 배송지별 `earliest_sec / latest_sec` — 적용됨 |
| 차량 출발·종료 정책 | 차량별 `start_lat`/`start_lon`, `end_policy` (`open_end` 기본). depot 포함 + `return_to_depot` = 직영 창고 복귀; depot 생략 = 지입·분산 |
| DispatchGroup Trip 자동 생성 | VRP 결과를 차량별 Trip으로 저장 |
| Push 알림 or Polling | 기사 앱에 배차 결과 전달 |

#### 프론트엔드 (관제 웹)

| 항목 | 설명 |
|---|---|
| 지도 | **Kakao 지도 API** — 입력·배차 결과·운행 모니터링 (내비 없음) |
| 배송 테이블 입력 UI | 배송지 N곳 + 화물 무게 일괄 입력 |
| 가용 차량 선택 | 오늘 출근 기사·차량 체크 |
| 배차 결과 지도 표시 | 엔진이 계산한 경로를 차량별 색상으로 표시 |

#### 기사 앱

| 항목 | 설명 |
|---|---|
| 주행 | **Kakao 내비 SDK** — 엔진이 확정한 경로로 턴바이턴 안내 |
| 노드·경로 수신 | Push/폴링으로 **노드 목록** 수신, **출발·도착**은 기사 선택 |
| 배차 수신 | 최적화 API 응답(`route`)을 내비 waypoint로 연동 |
| 다중 Trip 처리 | Phase 1 이후 **한 기사·여러 Trip**이 생길 수 있음. 현재 앱 UX·계약은 1 Trip 중심일 수 있으니, 확장 시 팀원 2(앱)와 조율 |

### 적재 용량 검증 (단기 대안)

백엔드 `POST /optimize/dispatch`는 이미 VRPTW·용량 차원을 적용한다. 다만 **관제 UI에서만 빠르게 검증**하거나, 응답 직후 **이중 확인**용으로 프론트에서 방문 순서대로 누적 적재량을 돌려 **초과 경고**를 띄우는 패턴을 쓸 수 있다:

```javascript
// 응답받은 route 순서대로 누적 적재량 계산
let load = 0;
for (const node of result.route) {
  load += node.cargo_weight_kg ?? 0;
  if (vehicle.max_load_kg && load > vehicle.max_load_kg) {
    showError(`${node.name}에서 최대 적재량 초과 (${load}kg / ${vehicle.max_load_kg}kg)`);
  }
}
```

> 이 방식은 초과 여부 **경고만** 가능하며, 초과 없는 최적 순서를 자동으로 찾지는 않습니다.
