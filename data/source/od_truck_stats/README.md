# 영업용화물 OD 통계 (운행기록계)

`제6권 전국화물 OD 보완갱신` 보고서 중 **영업용화물자동차 운행기록계(DTG)** 자료의 표 22~26을 JSON으로 정리한 참조 데이터입니다.  
원본 PDF: `자료/제6권 전국화물 OD 보완갱신.pdf` (보고서 내 표 5-2~5-13과 동일 내용, 캡처·자료집 표 번호는 **표 22~26**).

## 기준

- **자료**: 영업용화물자동차 운행거리 기록계(운행기록계) 표본
- **기간**: **10월** 기준 일평균·월간 집계 (보고서 본문)
- **톤급**: 소형 / 중형 / 대형 / 전체(가중 평균)
- **지역**: 17개 시·도 (짧은 키: `서울`, `경기`, `전북` … `제주`, `세종`)

## 파일

| 파일 | 표 | 단위 | 용도 |
|------|-----|------|------|
| `table26_daily_distance_km.json` | 26 | km/일 | **일평균 통행거리** — 가명 거리 상한·벤치마크 |
| `table24_daily_trips.json` | 24 | 통행/일 | 일평균 통행수 |
| `table25_daily_hours.json` | 25 | 시간/일 | 일평균 통행시간 |
| `table22_sample_vehicles.json` | 22 | 대/일 | 표본 차량수 (참고) |
| `table23_trip_generation_attraction.json` | 23 | 통행/월 | 발생·도착량 (지역 가중 참고) |

## 톤급 ↔ 스크립트

`scripts/od_stats.py`의 `ton_to_class()`는 가명 데이터 `무게(톤)`에 적용:

- **small (소형)**: &lt; 3.5 t  
- **medium (중형)**: 3.5 t ≤ 무게 &lt; 8 t  
- **large (대형)**: ≥ 8 t  

(운행기록계 분류와 완전 일치하지 않을 수 있음 — 데모·가명용 근사.)

## 사용

```python
from scripts.od_stats import lookup_daily_km, address_to_region, ton_to_class

region = address_to_region("경기도 수원시 ...")
cls = ton_to_class(5.2)
km = lookup_daily_km(region, cls)
```

가명 데이터 생성: `python scripts/generate_fake_logistics_data.py`
