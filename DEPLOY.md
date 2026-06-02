# RouteOn 배포/운영 절차

발표 직전 운영 기준의 최소 절차만 남겼습니다.  
대상 환경: Oracle Cloud Ubuntu 22.04 (A1 Flex 권장).

## 1) 서버 준비

```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y git python3.11 python3.11-venv python3-pip \
    postgresql postgresql-contrib openjdk-21-jre-headless osmium-tool
```

## 2) 코드 배치

```bash
git clone https://github.com/hongdydk/Capstone-ii.git /opt/routeon
cd /opt/routeon/backend
python3.11 -m venv ../.venv
source ../.venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## 3) DB/환경 변수

```bash
sudo -u postgres psql <<'SQL'
CREATE USER routeon WITH PASSWORD '강한비밀번호';
CREATE DATABASE routeon OWNER routeon;
\q
SQL
```

`/opt/routeon/backend/.env`
```env
DATABASE_URL=postgresql+asyncpg://routeon:강한비밀번호@localhost:5432/routeon
KAKAO_API_KEY=카카오_REST_API_키
SECRET_KEY=반드시_운영용으로_교체
DEBUG=false
```

## 4) GraphHopper

1. `Engine/`에 한국 OSM PBF 다운로드  
2. 필요 시 `patch_osm.py`로 화물차 제한 패치 반영  
3. `graphhopper-web-11.0.jar` 준비  
4. 최초 1회 graph-cache 빌드

```bash
cd /opt/routeon/Engine
java -Xmx6g -jar graphhopper-web-11.0.jar server config.yml
```

정상 기동 확인: `http://localhost:8989/health`

## 5) 서비스 등록 (systemd)

### `graphhopper.service`
- WorkingDirectory: `/opt/routeon/Engine`
- ExecStart: `java -Xmx6g -jar graphhopper-web-11.0.jar server config.yml`

### `routeon.service`
- WorkingDirectory: `/opt/routeon/backend`
- EnvironmentFile: `/opt/routeon/backend/.env`
- ExecStart: `/opt/routeon/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`

서비스 적용:
```bash
sudo systemctl daemon-reload
sudo systemctl enable graphhopper routeon
sudo systemctl restart graphhopper routeon
```

## 6) 운영 점검

```bash
curl http://localhost:8000/health
curl http://localhost:8989/health
sudo systemctl status routeon graphhopper
sudo journalctl -u routeon -f
sudo journalctl -u graphhopper -f
```

## 7) 보안/네트워크

- 외부 오픈 권장 포트: `22`, `8000`, `443`
- `8989`는 외부 미개방(내부 접근 전용)
- `.env` 권한 최소화(`chmod 600`)

