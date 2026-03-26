# 루트온(RouteOn) DB 스키마

> DB: PostgreSQL (asyncpg)  
> ORM: SQLAlchemy 2.x (Mapped / mapped_column)  
> 기준 파일: `backend/seeds/init_tables.sql` + `backend/app/models/`

---

## ENUM 타입

| ENUM 이름 | 값 |
|---|---|
| `userrole` | `admin`, `driver`, `contractor` |
| `tripstatus` | `scheduled`, `in_progress`, `completed`, `cancelled` |
| `reststoptype` | `highway_rest`, `drowsy_shelter`, `depot`, `custom` |
| `drivingstate` | `driving`, `resting`, `traffic_stop`, `unknown` |
| `dispatchgroupstatus` | `draft`, `dispatched`, `in_progress`, `completed`, `cancelled` |
| `dispatchorderstatus` | `pending`, `assigned`, `delivered`, `cancelled` |
| `zonetype` | `no_cross`, `no_entry`, `time_restrict` |
| `deliverytype` | `recurring`, `one_time` |

---

## 테이블 구조

### `users`

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | SERIAL | PK | |
| `username` | VARCHAR(50) | UNIQUE NOT NULL | 로그인 ID |
| `email` | VARCHAR(100) | UNIQUE NOT NULL | 이메일 |
| `hashed_password` | VARCHAR(255) | NOT NULL | bcrypt 해시 |
| `role` | userrole | NOT NULL DEFAULT 'driver' | `admin` / `driver` / `contractor` |
| `is_active` | BOOLEAN | NOT NULL DEFAULT TRUE | 계정 활성 여부 |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |

---

### `drivers`

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | SERIAL | PK | |
| `user_id` | INTEGER | UNIQUE NOT NULL → users.id CASCADE | |
| `name` | VARCHAR(50) | NOT NULL | 기사 이름 |
| `license_number` | VARCHAR(50) | | 운전면허 번호 |
| `phone` | VARCHAR(20) | | 연락처 |
| `company_id` | INTEGER | → users.id (admin) SET NULL | 소속 회사. NULL=일반기사, NOT NULL=지입기사 |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |

> **역할별 동작 차이**  
> - `driver`: Trip은 admin만 생성. 기사는 실행만.
> - `contractor`: Trip 직접 생성 가능. `company_id`로 지정된 admin이 실시간 위치/ETA 조회 가능.

---

### `vehicles`

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | SERIAL | PK | |
| `plate_number` | VARCHAR(20) | UNIQUE NOT NULL | 차량 번호판 |
| `vehicle_type` | VARCHAR(50) | NOT NULL | 예: `5톤카고`, `15톤탑차` |
| `height_m` | FLOAT | NOT NULL | 차량 높이 (m) |
| `weight_kg` | FLOAT | NOT NULL | 총중량 (kg) |
| `length_cm` | FLOAT | | 차량 길이 (cm) |
| `width_cm` | FLOAT | | 차량 폭 (cm) |
| `is_active` | BOOLEAN | NOT NULL DEFAULT TRUE | |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |

---

### `trips`

운행 건 1개를 표현합니다. 관리자가 생성하고, 기사가 출발 시 최적 경로가 계산됩니다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | SERIAL | PK | |
| `driver_id` | INTEGER | NOT NULL → drivers.id | |
| `vehicle_id` | INTEGER | NOT NULL → vehicles.id | |
| `origin_name` | VARCHAR(200) | | 출발지 이름 (기사가 출발 시 전달) |
| `origin_lat` | FLOAT | | 출발지 위도 |
| `origin_lon` | FLOAT | | 출발지 경도 |
| `dest_name` | VARCHAR(200) | NOT NULL | 목적지 이름 (관리자 설정) |
| `dest_lat` | FLOAT | NOT NULL | 목적지 위도 |
| `dest_lon` | FLOAT | NOT NULL | 목적지 경도 |
| `waypoints` | JSONB | | 경유지 배열 `[{"name","lat","lon"}]` |
| `vehicle_height_m` | FLOAT | | 차량 높이 오버라이드 (m) |
| `vehicle_weight_kg` | FLOAT | | 총중량 오버라이드 (kg) |
| `vehicle_length_cm` | FLOAT | | 차량 길이 오버라이드 (cm) |
| `vehicle_width_cm` | FLOAT | | 차량 폭 오버라이드 (cm) |
| `departure_time` | VARCHAR(50) | | 출발 예정 시각 ISO-8601 (타임머신 API) |
| `optimized_route` | JSONB | | 계산된 최적 경로 노드 목록 |
| `status` | tripstatus | NOT NULL DEFAULT 'scheduled' | 운행 상태 |
| `total_driving_seconds` | INTEGER | NOT NULL DEFAULT 0 | 누적 운전 시간 (초) |
| `total_rest_seconds` | INTEGER | NOT NULL DEFAULT 0 | 누적 휴식 시간 (초) |
| `dispatch_group_id` | INTEGER | → dispatch_groups.id SET NULL | 다수 배차 묶음. NULL=단건 배차 |
| `started_at` | TIMESTAMPTZ | | 실제 출발 시각 |
| `completed_at` | TIMESTAMPTZ | | 운행 완료 시각 |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |

> **차량 제원 우선순위**: `trips.vehicle_*` 값이 있으면 `vehicles.*` 값보다 우선 적용됩니다.  
> 지입기사처럼 vehicle 테이블에 제원이 없을 경우 trip 생성 시 직접 입력합니다.

---
### `dispatch_groups` (차후 구현 예정 — VRP)

다수 차량 배차 묶음입니다. 관리자가 배차 1건에 여러 기사/차량을 한번에 배정할 때 사용합니다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | SERIAL | PK | |
| `admin_id` | INTEGER | NOT NULL → users.id | 배차 생성 관리자 |
| `center_id` | INTEGER | → centers.id SET NULL | 출발 거점 센터. NULL이면 기사 현재 위치에서 출발 |
| `title` | VARCHAR(200) | NOT NULL | 예: "2026-03-26 부산행 3대" |
| `scheduled_at` | TIMESTAMPTZ | | 출발 예정 일시 |
| `note` | TEXT | | 관리자 메모 |
| `status` | dispatchgroupstatus | NOT NULL DEFAULT 'draft' | 배차 상태 |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |

---

### `dispatch_orders` (차후 구현 예정 — VRP)

배차 묶음 내 개별 배송 주문입니다. VRP 최적화 실행 후 `assigned_trip_id` / `visit_order` 가 채워집니다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | SERIAL | PK | |
| `group_id` | INTEGER | NOT NULL → dispatch_groups.id CASCADE | |
| `pickup_name` | VARCHAR(200) | | 상차지 이름 (선택) |
| `pickup_lat` / `pickup_lon` | FLOAT | | 상차지 좌표 |
| `dest_name` | VARCHAR(200) | NOT NULL | 하차지 이름 |
| `dest_lat` / `dest_lon` | FLOAT | NOT NULL | 하차지 좌표 |
| `cargo_desc` | VARCHAR(200) | | 화물 설명 |
| `cargo_weight_kg` | FLOAT | | 화물 무게 (kg) |
| `delivery_point_id` | INTEGER | → delivery_points.id SET NULL | 거래처 마스터 참조. NULL이면 dest_* 직접 사용 |
| `deadline` | VARCHAR(50) | | **하드 마감 시각** ISO-8601. 이 시각까지 미도착 시 페널티 부여 |
| `tw_open` | VARCHAR(50) | | **도착 가능 시작** ISO-8601. NULL이면 delivery_point.tw_open 적용 |
| `tw_close` | VARCHAR(50) | | **도착 마감** ISO-8601. NULL이면 delivery_point.tw_close 적용 |
| `priority` | INTEGER | NOT NULL DEFAULT 0 | 배송 우선순위 (0=보통, 1=높음, 2=긴급). VRP 가중치로 사용 |
| `assigned_trip_id` | INTEGER | → trips.id SET NULL | VRP 결과 배정된 운행. NULL=미배정 |
| `visit_order` | INTEGER | | 해당 trip 내 방문 순서 (1-based) |
| `status` | dispatchorderstatus | NOT NULL DEFAULT 'pending' | |
| `note` | TEXT | | |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |

> **VRP 최적화 흐름** (차후 구현 예정):  
> dispatch_group 생성 → dispatch_orders 등록 → VRP 실행 → orders를 trips에 배분 + 각 trip 내 방문 순서 확정

---
### `location_logs`

운행 중 GPS 위치를 시계열로 기록합니다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | SERIAL | PK | |
| `trip_id` | INTEGER | NOT NULL → trips.id CASCADE | |
| `latitude` | FLOAT | NOT NULL | 위도 |
| `longitude` | FLOAT | NOT NULL | 경도 |
| `speed_kmh` | FLOAT | | 속도 (km/h) |
| `state` | drivingstate | NOT NULL DEFAULT 'unknown' | 운전 상태 |
| `recorded_at` | TIMESTAMPTZ | NOT NULL DEFAULT NOW() | GPS 기록 시각 |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |

---

### `rest_stops`

휴게소, 졸음쉼터, 공영차고지, 사용자 추가 장소 POI 목록입니다. 경로 최적화 시 휴게 노드 삽입 후보로 사용됩니다.

**타입별 특성:**

| `type` | 등록 주체 | 설명 | 방향 필터 |
|---|---|---|---|
| `highway_rest` | 시스템 (관리자) | 고속도로 휴게소. 공공 데이터 기반 | O |
| `drowsy_shelter` | 시스템 (관리자) | 졸음쉼터. 공공 데이터 기반 | O |
| `depot` | 시스템 (관리자) | 공영차고지. 공공 데이터 기반 | X |
| `custom` | 회사(admin) / 기사(driver) | 직접 추가한 즐겨찾기 장소. `created_by_id`로 소유자 추적, `scope`로 공개 범위 설정 | X |

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | SERIAL | PK | |
| `name` | VARCHAR(100) | NOT NULL | POI 이름 |
| `type` | reststoptype | NOT NULL | `highway_rest` / `drowsy_shelter` / `depot` / `custom` |
| `latitude` | FLOAT | NOT NULL | 위도 |
| `longitude` | FLOAT | NOT NULL | 경도 |
| `is_active` | BOOLEAN | NOT NULL DEFAULT TRUE | |
| `direction` | VARCHAR(10) | | `상행` / `하행` / NULL(양방향 또는 미분류) |
| `created_by_id` | INTEGER | → users.id SET NULL | 등록자. NULL=시스템 등록(공공 데이터) |
| `scope` | VARCHAR(10) | DEFAULT 'private' | `private`=등록자만 / `company`=같은 회사 기사 공유 / `public`=전체 공개 |
| `note` | TEXT | | 메모 (예: "주차 공간 넓음", "샤워실 있음") |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |

> **scope 동작 규칙** (차후 구현):  
> - `private`: `created_by_id` 본인에게만 경로 후보로 표시  
> - `company`: `created_by_id` 가 속한 회사(`drivers.company_id`)의 모든 기사에게 공유  
> - `public`: 전체 시스템에서 공유 (관리자 승인 후 전환 권장)
---

### `centers` (차후 구현 예정 — VRP)

물류 센터 / 차고지 / 출발 거점 정보입니다.  
`dispatch_groups.center_id` 로 참조되어 VRP 최적화 시 출발점으로 사용됩니다.

| 콜럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | SERIAL | PK | |
| `name` | VARCHAR(100) | NOT NULL | 예: "인천 물류센터" |
| `address` | VARCHAR(300) | | |
| `latitude` / `longitude` | FLOAT | NOT NULL | |
| `manager_name` | VARCHAR(50) | | 담당자 |
| `manager_phone` | VARCHAR(20) | | |
| `note` | TEXT | | 메모 |
| `is_active` | BOOLEAN | NOT NULL DEFAULT TRUE | |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |

---

### `delivery_points` (차후 구현 예정 — VRP)

배송지 마스터 테이블입니다. `delivery_type` 으로 반복/단발을 구분하며,  
`dispatch_orders.delivery_point_id` 로 참조하면 좌표 및 기본 시간창이 자동으로 적용됩니다.

**배송지 3단계 계층:**

| 단계 | 설명 | delivery_type | delivery_point_id |
|---|---|---|---|
| 반복 거래처 | 매주/매월 배송하는 고정 거래처. 영구 마스터로 보관 | `recurring` | NOT NULL |
| 단발 거래처 | 이번 배차에만 사용. 배차 완료 후 `is_active=False` 체크 | `one_time` | NOT NULL |
| 즉흥 배송 | 마스터 등록 없이 `dest_*` 직접 입력. 시간창은 `dispatch_orders.tw_*`로만 설정 | — | NULL |

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | SERIAL | PK | |
| `name` | VARCHAR(100) | NOT NULL | 거래처명 |
| `address` | VARCHAR(300) | | |
| `latitude` / `longitude` | FLOAT | NOT NULL | |
| `contact_name` | VARCHAR(50) | | 담당자 |
| `contact_phone` | VARCHAR(20) | | |
| `delivery_type` | deliverytype | NOT NULL DEFAULT 'recurring' | `recurring`=반복 / `one_time`=단발 |
| `tw_open` | VARCHAR(5) | | **기본 수령 시작 시각** "HH:MM" (예: "09:00"). NULL이면 제한 없음 |
| `tw_close` | VARCHAR(5) | | **기본 수령 마감 시각** "HH:MM" (예: "17:00"). NULL이면 제한 없음 |
| `service_min` | INTEGER | | **하역 소요 시간** (분). VRP 계산 시 이 시간만큼 다음 이동 출발 지연 |
| `blackout_json` | TEXT | | **방문 금지 규칙** JSON 배열. 형식은 아래 참고 |
| `delivery_note` | TEXT | | 배송 특이사항 메모 (예: "지하 주차장 진입 불가") |
| `is_active` | BOOLEAN | NOT NULL DEFAULT TRUE | |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |

**`blackout_json` 형식 예시:**
```json
[
  { "type": "weekday", "days": [5, 6] },
  { "type": "time_range", "start": "12:00", "end": "13:00" }
]
```
- `weekday`: 방문 금지 요일 목록 (0=월 ~ 6=일)
- `time_range`: 방문 금지 시간대 ("HH:MM" 형식)

---

### `restricted_zones` (차후 구현 예정 — VRP)

교차 금지선 / 진입 금지 구역입니다. VRP 경로 최적화 시 특정 구역을 통과하지 못하도로 제약합니다.

| 콜럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | SERIAL | PK | |
| `name` | VARCHAR(100) | NOT NULL | 예: "한강 이남 진입 금지" |
| `zone_type` | zonetype | NOT NULL | `no_cross` / `no_entry` / `time_restrict` |
| `geometry_json` | TEXT | NOT NULL | GeoJSON (LineString 또는 Polygon) |
| `restrict_start_hour` | INTEGER | | 시간대 제한 시작시 (0시~23시) |
| `restrict_end_hour` | INTEGER | | 시간대 제한 종료시 |
| `description` | TEXT | | |
| `is_active` | BOOLEAN | NOT NULL DEFAULT TRUE | |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |
---

## 관계 다이어그램

```
users ──────────── drivers ──────────── trips ──────────── location_logs
 (1:1, CASCADE)      (1:N)          │     (1:N)
                            company_id│ (contractor)    vehicles (N:1)
                                       │
               centers (1:N) ─── dispatch_groups (1:N) ─── trips (VRP)
                                       │
                              dispatch_orders (N:1 → delivery_points)
                                       │
                              assigned_trip_id → trips

rest_stops   (독립 — trips.optimized_route JSONB에서 참조)
restricted_zones (독립 — VRP 최적화 시 경로 제약)
```

---

## 인덱스

| 테이블 | 컬럼 | 종류 |
|---|---|---|
| `users` | `username` | UNIQUE INDEX |
| `users` | `email` | UNIQUE INDEX |
| `vehicles` | `plate_number` | UNIQUE INDEX |
| `drivers` | `user_id` | UNIQUE INDEX |
| `trips` | `driver_id` | INDEX |
| `trips` | `vehicle_id` | INDEX |
| `trips` | `dispatch_group_id` | INDEX |
| `location_logs` | `trip_id` | INDEX |
| `dispatch_groups` | `admin_id` | INDEX |
| `dispatch_orders` | `group_id` | INDEX |
| `dispatch_orders` | `assigned_trip_id` | INDEX |
| `dispatch_groups` | `center_id` | INDEX |
| `dispatch_orders` | `delivery_point_id` | INDEX |

---

## VRPTW — 시간창 제약 설계

> **VRPTW (Vehicle Routing Problem with Time Windows)**  
> 각 배송지에 "언제 도착 가능한지" 제약을 두는 VRP 변형.  
> 시간창을 위반하면 페널티를 부여하거나 해당 경로를 제외합니다.

### 시간창 우선순위 (낮을수록 우선 적용)

```
dispatch_orders.tw_open / tw_close / deadline   ← 이번 건만의 오버라이드 (우선)
        ↓ NULL이면
delivery_points.tw_open / tw_close              ← 거래처 기본값 적용
        ↓ NULL이면
제약 없음 (언제든 방문 가능)
```

### 컬럼별 역할

| 컬럼 | 위치 | 타입 | 역할 |
|---|---|---|---|
| `tw_open` | delivery_points | VARCHAR(5) `"HH:MM"` | 이 거래처의 매일 수령 시작 시각 |
| `tw_close` | delivery_points | VARCHAR(5) `"HH:MM"` | 이 거래처의 매일 수령 마감 시각 |
| `service_min` | delivery_points | INTEGER | 하역 소요 시간(분). VRP에서 다음 이동 출발 지연 |
| `blackout_json` | delivery_points | TEXT (JSON) | 반복 방문 금지 규칙 (요일/시간대) |
| `tw_open` | dispatch_orders | VARCHAR(50) ISO-8601 | 이번 건 도착 가능 시작 (날짜+시각) |
| `tw_close` | dispatch_orders | VARCHAR(50) ISO-8601 | 이번 건 도착 마감 (날짜+시각) |
| `deadline` | dispatch_orders | VARCHAR(50) ISO-8601 | 하드 마감. 초과 시 미배송 페널티 부여 |
| `priority` | dispatch_orders | INTEGER (0/1/2) | VRP 가중치. 높을수록 먼저 배정 |

### delivery_points 시간창 vs dispatch_orders 시간창

| 구분 | delivery_points | dispatch_orders |
|---|---|---|
| 적용 범위 | 이 거래처에 대한 **모든** 배송 건 | **이번 배송 건만** |
| 시각 형식 | `"HH:MM"` (시각만) | ISO-8601 (날짜+시각+시간대) |
| 활용 예 | "항상 09:00~17:00만 배송 가능" | "이번 건은 오늘 오후 2시까지 필수" |

### blackout_json 규칙 형식

```json
[
  { "type": "weekday",    "days":  [5, 6]              },
  { "type": "time_range", "start": "12:00", "end": "13:00" }
]
```

| `type` | 필드 | 의미 |
|---|---|---|
| `weekday` | `days`: 정수 배열 (0=월 ~ 6=일) | 해당 요일에 방문 금지 |
| `time_range` | `start`, `end`: `"HH:MM"` | 해당 시간대에 방문 금지 (점심 시간 등) |
