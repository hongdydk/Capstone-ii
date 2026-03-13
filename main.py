import os
from typing import List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# 1. 환경 변수 로드 (.env 파일 읽기)
load_dotenv()

# --- FastAPI 객체 생성 (uvicorn이 이 'app'을 실행합니다) ---
app = FastAPI(
    title="중소 물류 기업용 배차 관리 API",
    description="TMAP API와 PostGIS를 연동한 배차 관리 서버"
)

# --- 데이터 모델 정의 ---
class OrderCreate(BaseModel):
    destination_name: str
    address: str

# --- 유틸리티 함수 ---
def get_db_connection():
    """PostgreSQL 데이터베이스 연결"""
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )

def get_coords(address: str):
    """TMAP API를 사용하여 주소를 좌표로 변환"""
    url = "https://apis.openapi.sk.com/tmap/geo/fullAddrGeo?version=1&format=json"
    headers = {"appKey": os.getenv("TMAP_API_KEY")}
    try:
        response = requests.get(url, headers=headers, params={"fullAddr": address})
        if response.status_code == 200:
            data = response.json()
            info = data.get("coordinateInfo", {})
            # 응답 데이터에서 좌표 추출 (Tmap 응답 구조 대응)
            coord = info.get("coordinate", [{}])[0] if info.get("coordinate") else info
            lon = coord.get("newLon") or coord.get("lon")
            lat = coord.get("newLat") or coord.get("lat")
            
            if lon and lat:
                return {"lon": float(lon), "lat": float(lat)}
        return None
    except Exception as e:
        print(f"API Error: {e}")
        return None

# --- API 엔드포인트 ---

@app.get("/", tags=["기본"])
async def root():
    return {"message": "물류 배차 관리 API 서버가 가동 중입니다."}

@app.post("/orders/", tags=["주문 관리"])
async def create_order(order: OrderCreate):
    """
    주소 정보를 받아 좌표로 변환 후 DB에 저장합니다.
    """
    # 1. TMAP 좌표 변환
    coords = get_coords(order.address)
    if not coords:
        raise HTTPException(status_code=400, detail="주소를 좌표로 변환할 수 없습니다.")
    
    # 2. DB 저장
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        sql = """
        INSERT INTO delivery_orders (destination_name, address, geom)
        VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
        RETURNING order_id;
        """
        cur.execute(sql, (order.destination_name, order.address, coords['lon'], coords['lat']))
        new_id = cur.fetchone()['order_id']
        
        conn.commit()
        cur.close()
        conn.close()
        
        return {
            "order_id": new_id,
            "status": "success",
            "destination_name": order.destination_name,
            "coords": coords
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB 저장 오류: {str(e)}")

@app.get("/orders/", tags=["주문 관리"])
async def list_orders():
    """
    DB에 저장된 모든 배송지 목록을 가져옵니다 (지도 표시용)
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # PostGIS ST_X, ST_Y 함수를 사용하여 위경도 추출
        sql = """
        SELECT order_id, destination_name, address, 
               ST_X(geom) as lon, ST_Y(geom) as lat 
        FROM delivery_orders;
        """
        cur.execute(sql)
        rows = cur.fetchall()
        
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB 조회 오류: {str(e)}")