# data/

데모·태스크 시드용 **원본**과 **생성 산출물**을 루트와 분리해 둡니다. `자료/`는 휴게소·고속도로 등 **백엔드 시드**용 공개 데이터를 그대로 둡니다.

- **`source/`** — 가짜 태스크 생성에 쓰는 물류창고·물류단지 XLS (`scripts/generate_fake_logistics_data.py` 입력).
- **`source/od_truck_stats/`** — 영업용화물 운행기록계 표 22~26(JSON). 가명 거리·톤급 벤치마크 (`scripts/od_stats.py`).
- **`generated/`** — 위 스크립트가 만든 CSV·`routeon_태스크양식.xlsx` (재생성 시 덮어씀). `scripts/fill_task_xlsx.py`도 이 경로를 사용합니다.

재생성: 저장소 루트에서 `python scripts/generate_fake_logistics_data.py`
