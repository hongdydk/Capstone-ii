# RouteOn — 화물차 경로 최적화 API 서버

화물차 법정 휴게 규정(2시간 운전 시 15분 휴식)을 자동으로 반영하여  
OR-Tools + TMAP 화물차 전용 API로 최적 동선을 계산하는 VRP 엔진입니다.

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [기술 스택](#2-기술-스택)
3. [빠른 시작 (Docker)](#3-빠른-시작-docker)
4. [로컬 개발 환경 설정](#4-로컬-개발-환경-설정)
5. [환경 변수](#5-환경-변수)
6. [DB 초기화 및 시드 데이터](#6-db-초기화-및-시드-데이터)
7. [API 엔드포인트](#7-api-엔드포인트)
8. [핵심 요청/응답 예시](#8-핵심-요청응답-예시)
9. [VRP 알고리즘 설명](#9-vrp-알고리즘-설명)
10. [프로젝트 구조](#10-프로젝트-구조)
11. [테스트 실행](#11-테스트-실행)
12. [향후 구현 예정](#12-향후-구현-예정)

---

## 1. 프로젝트 개요

| 항목 | 내용 |
|---|---|
| 프로젝트명 | RouteOn (루트온) |
| 목적 | 화물차 법정 휴게 규정 자동 반영 경로 최적화 |
| 핵심 기능 | TSP 기반 경유지 순서 최적화 + 법정 휴게소 자동 삽입 |
| 법적 근거 | 2시간(7,200초) 연속 운전 시 15분(900초) 이상 의무 휴식 |
| 계획 임계값 | 1시간 40분(6,000초) 도달 시 선제적으로 휴게소 삽입 |
| 역할 분리 | 관리자(경유지·목적지 등록) / 기사(출발지 전달 → 최적 동선 수신) |
| 차량 제원 입력 | 관리자 또는 기사(지입기사) 모두 입력 가능 — 기사 입력값이 우선 적용 |

---

## 2. 기술 스택

| 구성 요소 | 버전 |
|---|---|
| Python | 3.13 |
| FastAPI | 0.115.0 |
| SQLAlchemy (asyncio) | 2.0.34 |
| PostgreSQL | 16 |
| OR-Tools | 9.15.6755 |
| TMAP 화물차 경로 API | `/tmap/truck/routes` (실시간) |
| TMAP 타임머신 API | `/tmap/routes/prediction` (출발 예정 시각 기반 예측 교통) |
| Docker / Docker Compose | - |

---

## 3. 빠른 시작 (Docker)

### 사전 요구사항
- Docker Desktop 설치
- TMAP App Key 발급 ([SK Open API](https://openapi.sk.com))

### 실행

```bash
# 1. 저장소 클론
git clone https://github.com/hongdydk/Capstone-ii.git
cd Capstone-ii

# 2. 환경 변수 파일 생성
cp backend/.env.example backend/.env
# backend/.env 파일을 열고 TMAP_APP_KEY 값을 입력

# 3. Docker Compose 실행
docker compose up -d

# 4. 컨테이너 상태 확인
docker compose ps
```

정상 실행 시:
- API 서버: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- 헬스 체크: http://localhost:8000/health

### 중지

```bash
docker compose down          # 컨테이너만 중지
docker compose down -v       # 컨테이너 + DB 데이터 완전 삭제
```

---

## 4. 로컬 개발 환경 설정

Docker 없이 로컬에서 직접 실행하는 경우입니다.

### 사전 요구사항
- Python 3.13
- PostgreSQL 16 (로컬 설치 또는 Docker로 DB만 기동)

```bash
# DB만 Docker로 띄우기
docker compose up -d db
```

### 설치 및 실행

```bash
# 1. 가상환경 생성 및 활성화
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 환경 변수 설정
cp backend/.env.example backend/.env
# backend/.env 편집 → DATABASE_URL을 로컬 DB 주소로 변경
# 예: DATABASE_URL=postgresql+asyncpg://routeon:routeon@localhost:5432/routeon

# 4. 서버 실행
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## 5. 환경 변수

`backend/.env` 파일에서 설정합니다. (`backend/.env.example` 참고)

| 변수명 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://routeon:routeon@db:5432/routeon` | PostgreSQL 연결 URL |
| `TMAP_APP_KEY` | _(필수 입력)_ | TMAP Open API 앱 키 |
| `SECRET_KEY` | `CHANGE_ME_IN_PRODUCTION` | JWT 서명 키 (배포 시 변경) |
| `DEBUG` | `false` | 디버그 모드 |

> **주의**: `TMAP_APP_KEY`가 없으면 경로 최적화 API 호출 시 오류가 발생합니다.

---

## 6. DB 초기화 및 시드 데이터

서버 최초 기동 시 `startup` 이벤트에서 테이블이 자동 생성됩니다.  
아래 시드 스크립트로 고속도로 휴게소 및 물류단지 데이터를 초기 적재합니다.

```bash
cd backend

# 휴게소(highway_rest 78건) + 물류단지(depot 56건) 시드 삽입
python seeds/seed_rest_stops.py
```

시드 완료 후 `/rest-stops` API에서 휴게소 목록을 확인할 수 있습니다.

---

## 7. API 엔드포인트

Swagger UI에서 전체 스펙 확인 가능: **http://localhost:8000/docs**

> 현재 인증 없이 모든 엔드포인트를 호출할 수 있습니다.

### 경로 최적화 (핵심)

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/optimize/` | 단일 차량 경로 최적화 (배차) |
| `POST` | `/optimize/replan` | 운행 중 재경로 계산 |
| `POST` | `/optimize/dispatch` | 다수 차량 배차 (구현 예정, 501 반환) |

### 마스터 데이터

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/vehicles/` | 차량 목록 조회 |
| `POST` | `/vehicles/` | 차량 등록 |
| `PATCH` | `/vehicles/{id}` | 차량 정보 수정 |
| `GET` | `/drivers/` | 운전자 목록 조회 |
| `POST` | `/drivers/` | 운전자 등록 |
| `GET` | `/rest-stops/` | 휴게소 목록 조회 |
| `POST` | `/rest-stops/` | 휴게소 등록 |
| `DELETE` | `/rest-stops/{id}` | 휴게소 비활성화 |

### 운행 관리

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/trips/` | 운행 목록 조회 |
| `POST` | `/trips/` | 운행 생성 |
| `GET` | `/trips/{id}` | 운행 상세 조회 |
| `PATCH` | `/trips/{id}/status` | 운행 상태 변경 |

---

## 8. 핵심 요청/응답 예시

### 워크플로우 — 관리자 → 기사

```
[관리자]  POST /trips/        → 경유지·목적지·(차량 제원)·출발 예정 시각 등록
[기사]    POST /optimize/     → trip_id + 현재 출발 위치 + (차량 제원 override) 전달 → 최적 동선 수신
```

> **차량 제원 우선순위**: 기사(optimize 요청) 입력 > 관리자(trip 등록) 입력  
> - 관리자가 미리 차량 제원을 등록한 경우 → 기사는 출발지만 전달해도 됩니다.  
> - 지입기사처럼 본인 차량을 직접 아는 경우 → optimize 호출 시 차량 제원을 직접 입력하면 덮어씁니다.

---

### POST `/trips/` — 운행 생성 (관리자)

**요청**
```json
{
  "driver_id": 1,
  "vehicle_id": 1,
  "dest_name": "부산 물류단지",
  "dest_lat": 35.1796,
  "dest_lon": 129.0756,
  "waypoints": [
    {"name": "대전 창고", "lat": 36.3504, "lon": 127.3845},
    {"name": "대구 창고", "lat": 35.8714, "lon": 128.6014}
  ],
  "vehicle_height_m": 4.0,
  "vehicle_weight_kg": 25000,
  "vehicle_length_cm": 1600,
  "vehicle_width_cm": 250,
  "departure_time": "2026-03-26T08:00:00+0900"
}
```

> `departure_time` 입력 시 TMAP 타임머신 API(`/tmap/routes/prediction`)를 사용하여  
> 실제 출발 예정 시각의 교통 상황을 반영한 시간 행렬을 계산합니다.

---

### POST `/optimize/` — 경로 최적화 (기사)

**요청 — 관리자가 차량 제원을 미리 등록한 경우 (출발지만 입력)**
```json
{
  "trip_id": 1,
  "origin_name": "서울 자택",
  "origin_lat": 37.5665,
  "origin_lon": 126.9780,
  "initial_drive_sec": 0
}
```

**요청 — 지입기사가 본인 차량 제원을 직접 입력하는 경우**
```json
{
  "trip_id": 1,
  "origin_name": "인천 자택",
  "origin_lat": 37.4563,
  "origin_lon": 126.7052,
  "initial_drive_sec": 0,
  "vehicle_height_m": 4.0,
  "vehicle_weight_kg": 25000,
  "vehicle_length_cm": 1600,
  "vehicle_width_cm": 250
}
```

> - 경유지·목적지·출발 예정 시각은 `trip_id`로 DB에서 자동 로드됩니다.
> - 차량 제원(`vehicle_*`)을 전달하면 trip에 등록된 값을 override합니다.
> - 아무것도 전달하지 않으면 관리자가 등록한 trip의 차량 제원을 그대로 사용합니다.

**응답**
```json
{
  "trip_id": 1,
  "route": [
    {"type": "origin",      "name": "서울 물류단지", "lat": 37.5665, "lon": 126.9780},
    {"type": "waypoint",    "name": "대전 창고",     "lat": 36.3504, "lon": 127.3845},
    {"type": "rest_stop",   "name": "금강휴게소",    "lat": 35.9876, "lon": 127.5432,
     "min_rest_minutes": 15},
    {"type": "waypoint",    "name": "대구 창고",     "lat": 35.8714, "lon": 128.6014},
    {"type": "destination", "name": "부산 물류단지", "lat": 35.1796, "lon": 129.0756}
  ],
  "total_distance_km": 420.5,
  "estimated_duration_min": 327.0,
  "rest_stops_count": 1
}
```

### POST `/optimize/replan` — 운행 중 재경로 (기사)

운행 도중 정체 등으로 누적 운전시간이 늘어났을 때 호출합니다.

```json
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
  "vehicle_height_m": 4.0,
  "vehicle_weight_kg": 25000
}
```

### ExtraStop — 경유지/목적지/선호 휴게소 추가

`extra_stops` 필드로 운전자·관리자가 실시간으로 지점을 추가할 수 있습니다.

```json
"extra_stops": [
  {
    "stop_type": "waypoint",
    "name": "긴급 추가 납품처",
    "lat": 36.0000,
    "lon": 127.8000,
    "note": "오전 10시 이전 도착 필요"
  },
  {
    "stop_type": "rest_preferred",
    "name": "칠원휴게소",
    "lat": 35.2345,
    "lon": 128.4567
  }
]
```

| `stop_type` | 동작 |
|---|---|
| `"waypoint"` | TSP 순서 최적화 대상에 포함 |
| `"destination"` | 최종 목적지 변경 (기존 목적지는 경유지로 전환) |
| `"rest_preferred"` | 선호 휴게소로 후보 목록 최우선 배치 |

---

## 9. VRP 알고리즘 설명

### 주요 상수

| 상수 | 값 | 설명 |
|---|---|---|
| `MAX_DRIVE_SEC` | 7,200초 (2시간) | 법정 최대 연속 운전 시간 |
| `REST_PLAN_SEC` | 6,000초 (1시간 40분) | 선제적 휴게 삽입 임계값 |
| `MIN_REST_SEC` | 900초 (15분) | 법정 최소 휴식 시간 |

### TMAP API 선택 기준

| 조건 | 사용 API | 설명 |
|---|---|---|
| `departure_time` 없음 | `POST /tmap/truck/routes` | 실시간 교통 반영 화물차 경로 |
| `departure_time` 있음 | `POST /tmap/routes/prediction` | 출발 예정 시각의 예측 교통 반영 (타임머신) |

타임머신 API는 `searchOption: "17"` (화물차 전용), `predictionType: "arrival"` 모드로 호출되며  
차량 높이·중량·길이·폭 제약이 동일하게 적용됩니다.

### 처리 흐름

```
1. ExtraStop 분류
   └─ waypoint → 경유지 목록에 합류
   └─ destination → 최종 목적지 교체
   └─ rest_preferred → 휴게소 후보 맨 앞에 배치

2. TMAP 화물차 API로 N×N 시간 행렬 계산
   └─ departure_time 있으면 타임머신 API, 없으면 실시간 API
   └─ 차량 높이/중량/길이/폭 제약 반영

3. OR-Tools TSP로 경유지 방문 순서 최적화

4. 최적화된 순서로 구간별 누적 운전시간 계산
   └─ REST_PLAN_SEC(6,000초) 도달 구간에서 휴게소 삽입
   └─ 삽입 기준: 우회 비용(prev→휴게소→next 거리) 최소화
   └─ 1단계 lookahead: 다음 구간이 더 효율적이면 미룸
      (단, MAX_DRIVE_SEC 초과 시 강제 삽입)
```

---

## 10. 프로젝트 구조

```
Capstone-ii/
├── docker-compose.yml          # PostgreSQL + API 서버
├── requirements.txt            # Python 패키지 목록
└── backend/
    ├── Dockerfile
    ├── .env.example            # 환경 변수 템플릿
    ├── app/
    │   ├── main.py             # FastAPI 앱 진입점
    │   ├── api/
    │   │   ├── deps.py         # DB 의존성
    │   │   └── routes/
    │   │       ├── optimize.py # ★ 핵심: 경로 최적화 API
    │   │       ├── trips.py    # 운행 관리
    │   │       ├── vehicles.py # 차량 관리
    │   │       ├── drivers.py  # 운전자 관리
    │   │       ├── rest_stops.py # 휴게소 관리
    │   │       └── auth.py     # 인증 (현재 미사용)
    │   ├── services/
    │   │   ├── route_optimizer.py  # ★ VRP 엔진 (OR-Tools)
    │   │   └── tmap_service.py     # TMAP 화물차 경로 API
    │   ├── models/             # SQLAlchemy ORM 모델
    │   ├── schemas/            # Pydantic 요청/응답 스키마
    │   └── core/
    │       ├── config.py       # 환경 변수 설정
    │       └── database.py     # DB 연결 설정
    ├── seeds/
    │   └── seed_rest_stops.py  # 휴게소·물류단지 초기 데이터
    └── tests/
        └── test_route_optimizer.py  # 단위 테스트 (17개)
```

---

## 11. 테스트 실행

```bash
cd c:\Capstone-ii   # 또는 프로젝트 루트

# 전체 테스트 실행
.venv\Scripts\python.exe -m pytest backend/tests/ -v

# 예상 결과
# ======================= 17 passed in ~15s =======================
```

실제 TMAP API 호출 없이 순수 알고리즘(거리 행렬 모킹)만 테스트합니다.

---

## 12. 향후 구현 예정

| 기능 | 설명 |
|---|---|
| 다수 차량 배차 (CVRP) | `POST /optimize/dispatch` — OR-Tools CVRP로 여러 차량에 경유지 분배 |
| 인증 복원 | `auth.py` 기반 JWT 인증을 엔드포인트에 재적용 |
| 하이브리드 라우팅 | 단거리(< 50 km) Haversine, 장거리(≥ 50 km) TMAP으로 API 호출 절감 |

---

## 역할 분담

| 역할 | 담당 |
|---|---|
| 경로 최적화 엔진, 규정 로직, 총괄 | 팀원 A |
| 운전자 앱, 관리자 웹 | 팀원 B |
| API 서버, DB 스키마, Docker 인프라 | 팀원 C |
