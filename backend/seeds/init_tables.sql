-- RouteOn 초기 테이블 생성 SQL
-- 실행: psql -U routeon -d routeon -f seeds/init_tables.sql
-- (서버 lifespan에서 SQLAlchemy Base.metadata.create_all로도 자동 생성됩니다)

-- ENUM 타입 생성
DO $$ BEGIN
    CREATE TYPE userrole          AS ENUM ('admin', 'driver', 'contractor');
    CREATE TYPE tripstatus        AS ENUM ('scheduled', 'in_progress', 'completed', 'cancelled');
    CREATE TYPE reststoptype      AS ENUM ('highway_rest', 'drowsy_shelter', 'depot', 'custom');
    CREATE TYPE drivingstate      AS ENUM ('driving', 'resting', 'traffic_stop', 'unknown');
    CREATE TYPE dispatchgroupstatus AS ENUM ('draft', 'dispatched', 'in_progress', 'completed', 'cancelled');
    CREATE TYPE dispatchorderstatus AS ENUM ('pending', 'assigned', 'delivered', 'cancelled');
    CREATE TYPE zonetype          AS ENUM ('no_cross', 'no_entry', 'time_restrict');
    CREATE TYPE deliverytype      AS ENUM ('recurring', 'one_time');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- users
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(50)  UNIQUE NOT NULL,
    email           VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    role            userrole     NOT NULL DEFAULT 'driver',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  DEFAULT NOW()
);

-- drivers
CREATE TABLE IF NOT EXISTS drivers (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name           VARCHAR(50)  NOT NULL,
    license_number VARCHAR(50),
    phone          VARCHAR(20),
    company_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

-- vehicles
CREATE TABLE IF NOT EXISTS vehicles (
    id           SERIAL PRIMARY KEY,
    plate_number VARCHAR(20) UNIQUE NOT NULL,
    vehicle_type VARCHAR(50) NOT NULL,
    height_m     FLOAT NOT NULL,
    weight_kg    FLOAT NOT NULL,
    length_cm    FLOAT,
    width_cm     FLOAT,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- dispatch_groups (VRP — 차후 구현)
CREATE TABLE IF NOT EXISTS dispatch_groups (
    id           SERIAL PRIMARY KEY,
    admin_id     INTEGER NOT NULL REFERENCES users(id),
    title        VARCHAR(200) NOT NULL,
    scheduled_at TIMESTAMPTZ,
    note         TEXT,
    status       dispatchgroupstatus NOT NULL DEFAULT 'draft',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- trips
CREATE TABLE IF NOT EXISTS trips (
    id                   SERIAL PRIMARY KEY,
    driver_id            INTEGER NOT NULL REFERENCES drivers(id),
    vehicle_id           INTEGER NOT NULL REFERENCES vehicles(id),
    origin_name          VARCHAR(200),
    origin_lat           FLOAT,
    origin_lon           FLOAT,
    dest_name            VARCHAR(200) NOT NULL,
    dest_lat             FLOAT NOT NULL,
    dest_lon             FLOAT NOT NULL,
    waypoints            JSONB,
    vehicle_height_m     FLOAT,
    vehicle_weight_kg    FLOAT,
    vehicle_length_cm    FLOAT,
    vehicle_width_cm     FLOAT,
    departure_time       VARCHAR(50),
    optimized_route      JSONB,
    status               tripstatus NOT NULL DEFAULT 'scheduled',
    total_driving_seconds INTEGER NOT NULL DEFAULT 0,
    total_rest_seconds   INTEGER NOT NULL DEFAULT 0,
    dispatch_group_id    INTEGER REFERENCES dispatch_groups(id) ON DELETE SET NULL,
    started_at           TIMESTAMPTZ,
    completed_at         TIMESTAMPTZ,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

-- rest_stops
CREATE TABLE IF NOT EXISTS rest_stops (
    id             SERIAL PRIMARY KEY,
    name           VARCHAR(100) NOT NULL,
    type           reststoptype NOT NULL,
    latitude       FLOAT NOT NULL,
    longitude      FLOAT NOT NULL,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    direction      VARCHAR(100),
    created_by_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    scope          VARCHAR(10) DEFAULT 'private',
    note           TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

-- location_logs
CREATE TABLE IF NOT EXISTS location_logs (
    id          SERIAL PRIMARY KEY,
    trip_id     INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    latitude    FLOAT NOT NULL,
    longitude   FLOAT NOT NULL,
    speed_kmh   FLOAT,
    state       drivingstate NOT NULL DEFAULT 'unknown',
    recorded_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at  TIMESTAMPTZ  DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  DEFAULT NOW()
);
