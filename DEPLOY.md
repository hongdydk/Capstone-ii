# Oracle Cloud 배포 가이드

## 권장 인스턴스

| 항목 | 설정 |
|---|---|
| 인스턴스 유형 | **Ampere A1 Flex (ARM64) — Always Free** |
| OCPU | 4 |
| RAM | **24 GB** (GraphHopper 한국 전체 OSM 로드에 최소 3 GB 필요) |
| 부트 볼륨 | 50 GB 이상 (graph-cache 약 372 MB + OS) |
| OS | Ubuntu 22.04 LTS (ARM) |

> AMD micro (1 GB RAM)은 메모리 부족으로 GraphHopper 실행 불가.

> **GraphHopper 배포 비용 비교:** Oracle Cloud A1 Flex Always Free (4 OCPU · 24 GB RAM) 컴퓨팅 비용은 **월 $0**입니다. 반면 Kakao Mobility API로 TSP 행렬을 채우면 경유지 5개 기준 42번/배차, 하루 100건이면 월 약 126,000건을 소비합니다. 컴퓨팅 비용이 API 호출 비용보다 저렴해 GraphHopper를 클라우드에 배포하는 것이 합리적입니다.

---

## 1단계 — 기본 패키지 설치

```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y git python3.11 python3.11-venv python3-pip \
    postgresql postgresql-contrib \
    osmium-tool    # OSM PBF 처리용
```

### Java 21 설치 (GraphHopper 10.x 요구사항)

```bash
sudo apt-get install -y openjdk-21-jre-headless
java -version   # openjdk 21 확인
```

---

## 2단계 — 소스코드 클론

```bash
git clone https://github.com/hongdydk/Capstone-ii.git /opt/routeon
cd /opt/routeon
```

---

## 3단계 — PostgreSQL 설정

```bash
sudo -u postgres psql <<'SQL'
CREATE USER routeon WITH PASSWORD '여기에_강한_비밀번호';
CREATE DATABASE routeon OWNER routeon;
\q
SQL
```

---

## 4단계 — Python 가상환경 & 의존성

```bash
cd /opt/routeon/backend
python3.11 -m venv ../.venv
source ../.venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5단계 — 환경변수 설정

```bash
cat > /opt/routeon/backend/.env <<'ENV'
DATABASE_URL=postgresql+asyncpg://routeon:여기에_강한_비밀번호@localhost:5432/routeon
KAKAO_API_KEY=카카오_API_키
SECRET_KEY=랜덤_64자_이상_문자열_반드시_교체
DEBUG=false
ENV
chmod 600 /opt/routeon/backend/.env
```

> `SECRET_KEY` 생성 예시: `python3 -c "import secrets; print(secrets.token_hex(32))"`

---

## 6단계 — DB 테이블 초기화 & 휴게소 시드

```bash
cd /opt/routeon/backend
source ../.venv/bin/activate

# 테이블 생성 (FastAPI lifespan에서 자동 실행되지만 시드 전 먼저 실행)
python - <<'PY'
import asyncio
from app.core.database import Base, engine
asyncio.run(engine.begin().__aenter__().__class__.__init__)
PY

# 또는 간단히 서버를 한 번 기동했다가 Ctrl+C로 종료해도 테이블 자동 생성됨
uvicorn app.main:app --port 8000 &
sleep 5 && kill %1

# 졸음쉼터 CSV 시드 (drowsy_shelter — EUC-KR 자동 처리)
python seeds/seed_rest_stops.py

# truck_rest 휴게소 시드 (XLS 기반 Kakao 지오코딩 — KAKAO_API_KEY 필요)
python seeds/sync_xls_rest_stops.py
# → 자료/휴게소정보_260325.xls 파싱 후 Kakao 지오코딩으로 좌표 확정
# → 신규 추가 / 기존 업데이트 / 폐업 비활성화 자동 처리
```

---

## 7단계 — GraphHopper 설정

### 7-1. OSM PBF 다운로드

```bash
mkdir -p /opt/routeon/Engine
cd /opt/routeon/Engine

# Geofabrik에서 한국 최신 데이터 다운로드 (~264 MB)
wget https://download.geofabrik.de/asia/south-korea-latest.osm.pbf \
    -O south-korea-latest.osm.pbf
```

### 7-2. 화물차 제한 패치 적용

```bash
cd /opt/routeon
source .venv/bin/activate

# osmium이 필요 (1단계에서 설치됨)
python Engine/patch_osm.py
# → south-korea-patched.osm.pbf 생성 (~265 MB)
```

> `patch_osm.py`가 `osmium` CLI를 호출합니다. osmium이 없으면:  
> `sudo apt-get install -y osmium-tool`

### 7-3. GraphHopper JAR 다운로드

```bash
cd /opt/routeon/Engine
wget https://github.com/graphhopper/graphhopper/releases/download/10.0/graphhopper-web-10.0.jar
```

### 7-4. config.yml 확인

`Engine/config.yml`의 포트가 `8989`, bind_host가 `localhost`인지 확인:

```yaml
server:
  application_connectors:
  - type: http
    port: 8989
    bind_host: localhost   # 외부 직접 노출 차단
```

### 7-5. GraphHopper 첫 실행 (graph-cache 빌드)

```bash
cd /opt/routeon/Engine
mkdir -p logs graph-cache

# 첫 실행 — graph-cache 빌드 (15~30분 소요, 메모리 4 GB 사용)
java -Xmx6g -jar graphhopper-web-10.0.jar server config.yml
```

> 로그에 `Started DropwizardWebServer` 가 출력되면 성공.  
> 이후부터는 graph-cache를 재사용해 30초 내 기동.

---

## 8단계 — systemd 서비스 등록

### GraphHopper 서비스

```bash
sudo tee /etc/systemd/system/graphhopper.service <<'UNIT'
[Unit]
Description=GraphHopper Routing Engine
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/routeon/Engine
ExecStart=/usr/bin/java -Xmx6g -jar graphhopper-web-10.0.jar server config.yml
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable graphhopper
sudo systemctl start graphhopper
```

### FastAPI 서비스

```bash
sudo tee /etc/systemd/system/routeon.service <<'UNIT'
[Unit]
Description=RouteOn FastAPI Backend
After=network.target postgresql.service graphhopper.service

[Service]
User=ubuntu
WorkingDirectory=/opt/routeon/backend
EnvironmentFile=/opt/routeon/backend/.env
ExecStart=/opt/routeon/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable routeon
sudo systemctl start routeon
```

---

## 9단계 — truck_rest 휴게소 데이터 적재

**방법 1 (권장) — XLS 직접 시드**

`자료/휴게소정보_260325.xls` 파일이 git clone에 포함되어 있으므로, 서버에서 바로 실행:

```bash
cd /opt/routeon/backend
source ../.venv/bin/activate
python seeds/sync_xls_rest_stops.py
# → Kakao 지오코딩으로 좌표 확정 후 DB 적재 (KAKAO_API_KEY 필요)
```

**방법 2 (대안) — 로컬 DB 덤프 복원**

로컬에서 이미 시드된 DB를 서버로 전송할 때:

```powershell
# 로컬 Windows에서 실행
pg_dump -U routeon -d routeon -t rest_stops --data-only -F p -f rest_stops.sql
scp rest_stops.sql ubuntu@서버IP:/tmp/
```

서버에서 복원:

```bash
psql -U routeon -d routeon -f /tmp/rest_stops.sql
```

---

## 10단계 — 방화벽 (Oracle Cloud 보안 목록)

Oracle Cloud 콘솔 → VCN → Security List에서 인바운드 규칙 추가:

| 포트 | 프로토콜 | 용도 |
|---|---|---|
| 22 | TCP | SSH |
| 8000 | TCP | FastAPI (앱 접근) |
| 443 | TCP | HTTPS (Nginx 리버스 프록시 사용 시) |

> **8989 (GraphHopper)는 외부에 열지 마세요** — `bind_host: localhost`로 FastAPI에서만 내부 접근.

OS 방화벽도 허용:

```bash
sudo iptables -I INPUT -p tcp --dport 8000 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

---

## 11단계 — 동작 확인

```bash
# FastAPI 헬스체크
curl http://localhost:8000/health
# → {"status":"ok"}

# GraphHopper 헬스체크
curl "http://localhost:8989/health"
# → {"status":"GREEN",...}

# 데모 경로 테스트 (법정 휴게소 자동 삽입 + 대안 top-3 포함)
curl -s -X POST http://localhost:8000/demo/route \
  -H 'Content-Type: application/json' \
  -d '{"profile":"truck","nodes":[{"name":"서울","lat":37.5665,"lon":126.978},{"name":"부산","lat":35.1796,"lon":129.0756}]}' \
  | python3 -m json.tool | head -40

# 위치 로그 전송 테스트 (응답에 accumulated_drive_sec + needs_replan 포함)
# accumulated_drive_sec: 서버 타임스탬프 기준 누적 연속 운전시간(초) — 폰 시간 조작 차단
# needs_replan: accumulated_drive_sec >= 6000 이면 true → 앱이 POST /optimize/replan 자동 호출
curl -s -X POST http://localhost:8000/location-logs/ \
  -H 'Content-Type: application/json' \
  -d '{"trip_id":1,"latitude":37.1234,"longitude":127.5678,"speed_kmh":85.0}' \
  | python3 -m json.tool
```

---

## 서비스 관리 명령어

```bash
# 상태 확인
sudo systemctl status routeon graphhopper

# 로그 확인
sudo journalctl -u routeon -f
sudo journalctl -u graphhopper -f

# 재시작
sudo systemctl restart routeon
sudo systemctl restart graphhopper
```

---

## 파일 크기 참고 (서버에 필요한 것만)

| 파일 | 크기 | 비고 |
|---|---|---|
| `south-korea-latest.osm.pbf` | ~264 MB | Geofabrik에서 다운로드 주소: https://download.geofabrik.de/asia/south-korea-latest.osm.pbf 
사이트 주소: https://download.geofabrik.de/asia/south-korea.html|
| `south-korea-patched.osm.pbf` | ~265 MB | patch_osm.py로 생성 |
| `graphhopper-web-10.0.jar` | ~45 MB | GitHub Releases에서 다운로드 주소: https://repo1.maven.org/maven2/com/graphhopper/graphhopper-web/11.0/graphhopper-web-11.0.jar 
사이트 주소: https://github.com/graphhopper/graphhopper|
| `graph-cache/` | ~372 MB | GraphHopper 첫 실행 시 자동 생성 |
| 소스코드 + 설정 | ~1 MB | git clone |

**Git push 대상: ~1 MB / 서버 실제 사용: ~700 MB**
