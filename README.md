# RouteOn (루트온)

화물차 운행 경로를 최적화하면서 **법정 휴게 규정을 자동 반영**하는 물류 관제 시스템입니다.

## 1. 시스템 구성

```
┌──────────────────────────────────┐      ┌─────────────────────┐
│         관제 웹 (Web)            │      │   기사 앱 (Mobile)   │
│  - 관리자 전용                    │      │  - 운전기사/용차 공용 │
│  - 상차지 + 하차지 노드 전달      │      │  - 노드 수신 후       │
│    → 경로 선택은 기사가 직접      │      │    경로 직접 선택     │
│  - 운행 중 추가 노드 전달 가능    │      │  - 추가 노드 수신 시  │
│    (중간 경유지 지시)             │      │    현재 위치 기준     │
│                                  │      │    재탐색             │
└────────┬─────────────────────────┘      └──────────┬──────────┘
         │                                           │
         └──────────────┬─────────────────────────────┘
                        ▼
         ┌──────────────────────────────┐
         │      FastAPI 백엔드 (8000)    │
         │  - 경로 최적화 API            │
         │  - 운행·차량·기사 CRUD        │
         │  - 법정 휴게소 자동 삽입      │
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

### 엔진(GraphHopper)이 하는 일

TSP 행렬을 구성하려면 N개 노드에 대해 **N²-N번의 구간 거리·시간**이 필요합니다. 이를 Kakao API로 채우면 경유지가 늘수록 호출 수가 폭발적으로 증가해 API 비용과 QPS 제한(10 req/s)이 병목이 됩니다.

GraphHopper는 한국 전체 OSM 도로 데이터를 클라우드 서버에 빌드해두고, 두 지점 간 경로를 **API 호출 없이** 직접 계산합니다. 클라우드 컴퓨팅 비용이 API 호출 비용보다 저렴하므로, TSP 행렬 계산은 GraphHopper로 처리하고 Kakao는 실시간 교통이 반드시 필요한 재탐색·ETA 조회에만 사용합니다.

| | GraphHopper | Kakao Mobility |
|---|---|---|
| TSP 행렬 계산 | ✅ API 호출 없음 | ❌ N²-N 호출 필요 |
| 실시간 교통 | ❌ 정적 OSM | ✅ |
| 미래 시간대 예측 | ❌ | ✅ (`departure_time`) |
| 사용 용도 | TSP 행렬 거리·시간 | 재탐색·실시간 ETA |

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
법정 휴게소 삽입 (폴리라인 기반 균등 배분)
  · 전체 경로 시간 ÷ MAX_DRIVE_SEC → 필요 휴게소 수 선계산
  · 폴리라인 위 균등 시간 지점 추출 → 방향·타입 우선순위(truck > highway > drowsy)로 최근접 선택
  · DB direction 컬럼 또는 이름 패턴으로 주행 방위각 ±90° 이내 후보 우선 (반대 차선 방지)
  · 경유지 존재 시 구간별 독립 평가, 경유지에서 누적 운전시간 리셋
  ※ 기존(Haversine 임계값 초과 즉시 삽입) 대비: 경로 전체 균등 배분 + 반대 차선 방지
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
├─ 자료/
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
│  │     └─ rest_stop_inserter.py ← 법정 휴게소 삽입 (폴리라인 균등 배분)
│  └─ seeds/
│     ├─ seed_rest_stops.py         ← 졸음쉼터 CSV 시드
│     └─ sync_xls_rest_stops.py     ← XLS 기반 truck_rest 동기화
└─ frontend/              ← 정적 파일 (옵션)
```

## 5. 구현 범위

**완료:**
- 단일 차량 경로 최적화: `POST /optimize/`
- 운행 중 재최적화: `POST /optimize/replan`
- DB trip 없는 데모 최적화: `POST /demo/route`
- 운행·차량·기사·휴게소·위치 로그 CRUD
- 법정 휴게소 자동 삽입 (폴리라인 균등 배분 + 방향 필터 + 타입 우선순위)
- GraphHopper 화물차 라우팅 엔진 연동
- Kakao `departure_time` 기반 미래 교통 반영
- truck_rest 휴게소 DB 79건 (XLS 전수 검증 완료)
- 위치 로그 기반 누적 운전시간 추적 (`accumulated_drive_sec`) 및 재경로 트리거 플래그 (`needs_replan`)

**미구현:**
- 다수 차량 VRP 배차: `POST /optimize/dispatch` (501)

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
KAKAO_API_KEY=카카오_REST_API_키
SECRET_KEY=CHANGE_ME_IN_PRODUCTION   ← 운영 시 반드시 교체
DEBUG=false
```

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
| `/optimize/dispatch` | POST | 다차량 VRP (501) |
| `/demo/route` | POST | DB 없는 데모 최적화 |
| `/trips/` | GET/POST | 운행 목록·생성 |
| `/trips/{id}/status` | PATCH | 운행 상태 변경 |
| `/vehicles/` | GET/POST/PATCH | 차량 CRUD |
| `/drivers/` | GET/POST | 기사 CRUD |
| `/rest-stops/` | GET/POST/DELETE | 휴게소 CRUD |
| `/location-logs/` | GET/POST | 위치 로그 — POST 응답에 `accumulated_drive_sec`, `needs_replan` 포함 |
| `/health` | GET | 헬스체크 |

## 9. 데모 경로 최적화 (DB 없이 테스트)

trip을 만들지 않고 노드 좌표만으로 즉시 경로 + 휴게소 삽입 결과를 확인합니다.

### 기본 사용 패턴 — 상차지 + 하차지 2개

관제 웹은 **상차지(cargo pickup)와 하차지(cargo dropoff) 노드**를 입력해 경로를 미리 확인합니다.  
노드 목록을 기사 앱으로 전달하면 **경로 선택은 기사가 직접** 합니다.  
관리자가 운행 중 추가 경유지가 필요할 때만 노드를 추가 전달하며, 기사 앱이 **현재 위치 기준으로 재계산**합니다.

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

상차지에서 화물을 싣고 여러 하차지에 순차 납품할 때 `pickup_from_idx`로 상차→하차 순서 제약을 걸 수 있습니다.

```bash
curl -s -X POST http://localhost:8000/demo/route \
  -H 'Content-Type: application/json' \
  -d '{
    "profile": "truck",
    "nodes": [
      {"name": "상차지 — 인천 물류센터",  "lat": 37.4563, "lon": 126.7052},
      {"name": "하차지1 — 대전 창고",      "lat": 36.3504, "lon": 127.3845, "pickup_from_idx": 0},
      {"name": "하차지2 — 부산 물류단지",  "lat": 35.1796, "lon": 129.0756, "pickup_from_idx": 0}
    ]
  }' | python -m json.tool
```

## 10. 관제 웹 UI 사용법

`http://localhost:8000/map/` 접속 후:

1. **상차지 버튼** 클릭 → 지도에서 화물을 싣는 지점 클릭
2. **하차지 버튼** 클릭 → 지도에서 화물을 내리는 지점 클릭
3. (선택) **경유지 버튼**으로 추가 경유지 삽입, ⚙ 버튼으로 도착 시각 제약·상차→하차 연결 설정
4. **경로 계산** → 법정 휴게소 자동 삽입 결과 미리 확인
5. **노드 목록을 기사 앱으로 전달** → 기사가 직접 경로 선택

**운행 중 추가 경유지 지시:**

관리자가 "중간에 A 창고도 들러주세요"가 필요할 때:
- 추가 노드만 기사 앱으로 전달
- 기사 앱이 **현재 위치(`current_lat/lon`) + 누적 운전시간(`current_drive_sec`) 기준으로 `POST /optimize/replan` 재호출**
- 재탐색 후 기사에게 새 경로 안내

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

```json
POST /optimize/replan
{
  "trip_id": 1,
  "current_lat": 36.1234,
  "current_lon": 127.4567,
  "current_name": "현재위치",
  "current_drive_sec": 5400,
  "remaining_waypoints": [
    {"name": "대구 창고", "lat": 35.8714, "lon": 128.6014}
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
- `tests/test_kakao_local.py` — 지역 배송 모드
- `tests/test_kakao_long.py` — 장거리 모드

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
