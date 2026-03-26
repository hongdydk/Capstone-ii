-- routeon DB 초기 테이블 생성
-- 사용법: docker exec -i routeon-db psql -U routeon -d routeon < backend/seeds/init_tables.sql

DO $$ BEGIN
    CREATE TYPE userrole AS ENUM ('admin', 'driver', 'contractor');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- contractor: 지입기사 — 본인 Trip 직접 생성 가능, 소속 회사(admin)에 위치 공유

DO $$ BEGIN
    CREATE TYPE reststoptype AS ENUM ('highway_rest', 'drowsy_shelter', 'depot');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE tripstatus AS ENUM ('scheduled', 'in_progress', 'completed', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE drivingstate AS ENUM ('driving', 'resting', 'traffic_stop', 'unknown');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS users (
    id              SERIAL       PRIMARY KEY,
    username        VARCHAR(50)  UNIQUE NOT NULL,
    email           VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    role            userrole     NOT NULL DEFAULT 'driver',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS drivers (
    id             SERIAL  PRIMARY KEY,
    user_id        INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name           VARCHAR(50) NOT NULL,
    license_number VARCHAR(50),
    phone          VARCHAR(20),
    -- 지입기사(contractor) 전용: 위치 정보를 공유할 소속 회사(admin user)
    -- NULL = 일반 소속 기사, NOT NULL = 지입기사
    company_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vehicles (
    id           SERIAL       PRIMARY KEY,
    plate_number VARCHAR(20)  UNIQUE NOT NULL,
    vehicle_type VARCHAR(50)  NOT NULL,
    height_m     FLOAT        NOT NULL,
    weight_kg    FLOAT        NOT NULL,
    length_cm    FLOAT,
    width_cm     FLOAT,
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ  DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trips (
    id                    SERIAL   PRIMARY KEY,
    driver_id             INTEGER  NOT NULL REFERENCES drivers(id),
    vehicle_id            INTEGER  NOT NULL REFERENCES vehicles(id),
    -- 출발지 (기사가 출발 시 전달)
    origin_name           VARCHAR(200),
    origin_lat            FLOAT,
    origin_lon            FLOAT,
    -- 목적지 (관리자 설정)
    dest_name             VARCHAR(200) NOT NULL,
    dest_lat              FLOAT        NOT NULL,
    dest_lon              FLOAT        NOT NULL,
    -- 경유지
    waypoints             JSONB,
    -- 차량 제원 오버라이드 (통행 제한 경로 자동 우회)
    vehicle_height_m      FLOAT,
    vehicle_weight_kg     FLOAT,
    vehicle_length_cm     FLOAT,
    vehicle_width_cm      FLOAT,
    -- 출발 예정 시각 (타임머신 예측 교통 API)
    departure_time        VARCHAR(50),
    -- 경로 / 상태
    optimized_route       JSONB,
    status                tripstatus NOT NULL DEFAULT 'scheduled',
    -- 운행 시간 누적 (초)
    total_driving_seconds INTEGER    NOT NULL DEFAULT 0,
    total_rest_seconds    INTEGER    NOT NULL DEFAULT 0,
    -- 다수 차량 배차 무름 소속 (VRP 확장용) — NULL = 단건 배차
    dispatch_group_id INTEGER REFERENCES dispatch_groups(id) ON DELETE SET NULL,
    started_at            TIMESTAMPTZ,
    completed_at          TIMESTAMPTZ,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS location_logs (
    id          SERIAL  PRIMARY KEY,
    trip_id     INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    latitude    FLOAT   NOT NULL,
    longitude   FLOAT   NOT NULL,
    speed_kmh   FLOAT,
    state       drivingstate NOT NULL DEFAULT 'unknown',
    recorded_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at  TIMESTAMPTZ  DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rest_stops (
    id          SERIAL       PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    type        reststoptype NOT NULL,
    latitude    FLOAT        NOT NULL,
    longitude   FLOAT        NOT NULL,
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    direction   VARCHAR(10),   -- '상행' / '하행' / NULL(양방향 또는 미분류)
    created_at  TIMESTAMPTZ  DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  DEFAULT NOW()
);

DO $$ BEGIN
    CREATE TYPE dispatchgroupstatus AS ENUM ('draft', 'dispatched', 'in_progress', 'completed', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE dispatchorderstatus AS ENUM ('pending', 'assigned', 'delivered', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE zonetype AS ENUM ('no_cross', 'no_entry', 'time_restrict');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- no_cross: 교차 금지선, no_entry: 진입 금지 구역, time_restrict: 시간대 제한 구역

DO $$ BEGIN
    CREATE TYPE deliverytype AS ENUM ('recurring', 'one_time');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- recurring: 반복 거래처 (영구 마스터), one_time: 단발 거래처 (배차 완료 후 정리 가능)

CREATE TABLE IF NOT EXISTS centers (
    id            SERIAL       PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,          -- 예: "인천 물류센터"
    address       VARCHAR(300),
    latitude      FLOAT        NOT NULL,
    longitude     FLOAT        NOT NULL,
    manager_name  VARCHAR(50),
    manager_phone VARCHAR(20),
    note          TEXT,
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS delivery_points (
    id            SERIAL       PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,          -- 거래처명
    address       VARCHAR(300),
    latitude      FLOAT        NOT NULL,
    longitude     FLOAT        NOT NULL,
    contact_name  VARCHAR(50),
    contact_phone VARCHAR(20),
    delivery_type deliverytype NOT NULL DEFAULT 'recurring',  -- 반복/단발 구분
    -- 기본 시간창 (VRPTW) ── dispatch_orders에 값 없으면 이 값이 사용됨
    tw_open       VARCHAR(5),                     -- 수령 시작 시각 "HH:MM" (예: "09:00")
    tw_close      VARCHAR(5),                     -- 수령 마감 시각 "HH:MM" (예: "17:00")
    service_min   INTEGER,                        -- 하역 소요 시간 (분)
    -- 방문 금지 규칙 JSON 배열
    -- 예: [{"type":"weekday","days":[5,6]},{"type":"time_range","start":"12:00","end":"13:00"}]
    -- type: weekday  → days 배열 (0=월 ~ 6=일)
    -- type: time_range → start/end "HH:MM"
    blackout_json TEXT,
    delivery_note TEXT,                           -- 배송 특이사항 메모
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS restricted_zones (
    id                   SERIAL  PRIMARY KEY,
    name                 VARCHAR(100) NOT NULL,   -- 예: "한강 이남 진입 금지"
    zone_type            zonetype NOT NULL,
    geometry_json        TEXT NOT NULL,            -- GeoJSON (LineString 또는 Polygon)
    restrict_start_hour  INTEGER,                  -- 시간대 제한 시작시 (0~23)
    restrict_end_hour    INTEGER,                  -- 시간대 제한 종료시 (0~23)
    description          TEXT,
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dispatch_groups (
    id           SERIAL       PRIMARY KEY,
    admin_id     INTEGER      NOT NULL REFERENCES users(id),
    center_id    INTEGER      REFERENCES centers(id) ON DELETE SET NULL,  -- 출발 거점 센터
    title        VARCHAR(200) NOT NULL,
    scheduled_at TIMESTAMPTZ,
    note         TEXT,
    status       dispatchgroupstatus NOT NULL DEFAULT 'draft',
    created_at   TIMESTAMPTZ  DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dispatch_orders (
    id               SERIAL       PRIMARY KEY,
    group_id         INTEGER      NOT NULL REFERENCES dispatch_groups(id) ON DELETE CASCADE,
    -- 상차지 (선택)
    pickup_name      VARCHAR(200),
    pickup_lat       FLOAT,
    pickup_lon       FLOAT,
    -- 하차지 (필수)
    dest_name        VARCHAR(200) NOT NULL,
    dest_lat         FLOAT        NOT NULL,
    dest_lon         FLOAT        NOT NULL,
    -- 화물 정보
    cargo_desc       VARCHAR(200),
    cargo_weight_kg  FLOAT,
    delivery_point_id INTEGER REFERENCES delivery_points(id) ON DELETE SET NULL,  -- 배송지 마스터 참조
    -- 이번 건 시간 제약 (VRPTW) ── NULL이면 delivery_point 기본값 사용
    deadline         VARCHAR(50),                -- 절대 마감 시각 ISO-8601 (예: "2026-03-26T17:00:00+09:00")
    tw_open          VARCHAR(50),                -- 도착 가능 시작 시각 ISO-8601
    tw_close         VARCHAR(50),                -- 도착 마감 시각 ISO-8601
    priority         INTEGER      NOT NULL DEFAULT 0,  -- 우선순위 (0=보통, 1=높음, 2=긴급)
    -- VRP 최적화 결과 — 미배정 시 NULL
    assigned_trip_id INTEGER      REFERENCES trips(id) ON DELETE SET NULL,
    visit_order      INTEGER,                    -- 해당 trip 내 방문 순서 (1-based)
    status           dispatchorderstatus NOT NULL DEFAULT 'pending',
    note             TEXT,
    created_at       TIMESTAMPTZ  DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  DEFAULT NOW()
);

SELECT 'tables created' AS result;
