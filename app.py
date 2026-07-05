import os
import io
import sys
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from data_processor import process_dataframe, filter_for_barchart, compute_summary


def _get_base_path():
    """번들된 리소스(static/, examples/) 경로"""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _get_app_dir():
    """실행파일 위치 (쓰기 가능 data/ 폴더용)"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_PATH = _get_base_path()
APP_DIR = _get_app_dir()

# func_ubkais는 임포트 시 sys.stdout/stderr의 버퍼를 detach하므로,
# 임포트 전에 더미 스트림으로 교체하여 원본 버퍼를 보호한다.
_orig_stdout = sys.stdout
_orig_stderr = sys.stderr
sys.stdout = io.TextIOWrapper(io.BytesIO())
sys.stderr = io.TextIOWrapper(io.BytesIO())
try:
    from func_ubkais import process_flight_schedule as _process_flight_schedule
finally:
    sys.stdout = _orig_stdout
    sys.stderr = _orig_stderr

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="BarChart Creator")


@app.middleware("http")
async def no_cache_static(request, call_next):
    """정적 파일(JS/CSS)에 대해 브라우저가 항상 서버에 재검증하도록 강제.

    Cache-Control 헤더가 없으면 브라우저가 휴리스틱 캐싱으로 구버전 JS를
    계속 사용해, 백엔드 API 응답 구조가 바뀌어도 프론트가 갱신되지 않는
    문제(예: 가동률 표가 최신 데이터에도 "데이터 없음"으로 표출)가 발생한다.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


# 정적 파일 서빙
app.mount("/static", StaticFiles(directory=str(BASE_PATH / "static")), name="static")

# 인메모리 캐시
_current_df: pd.DataFrame | None = None

DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

ICAO_CODES = [
    "RKSI",  # ICN 인천
    "RKSS",  # GMP 김포
    "RKPK",  # PUS 부산
    "RKPC",  # CJU 제주
    "RKJJ",  # KWJ 광주
    "RKTN",  # TAE 대구
    "RKNY",  # YNY 양양
    "RKTH",  # CJJ 청주
    "RKNW",  # WJU 원주
    "RKJB",  # MWX 무안
    "RKPU",  # USN 울산
    "RKPS",  # RSU 여수
    "RKJK",  # KUV 군산
]


@app.get("/")
async def root():
    return FileResponse(str(BASE_PATH / "static" / "index.html"))


class CrawlRequest(BaseModel):
    start_date: str  # yyyymmdd
    end_date: str    # yyyymmdd


@app.post("/api/crawl")
async def crawl_data(req: CrawlRequest):
    """func_ubkais.process_flight_schedule() 호출 → 메모리 캐시"""
    global _current_df
    try:
        file_name = str(DATA_DIR / f"flight_schedule_{req.start_date}_{req.end_date}.xlsx")
        logger.info(f"크롤링 시작: {req.start_date} ~ {req.end_date}")

        _process_flight_schedule(
            start_date=req.start_date,
            end_date=req.end_date,
            icao_airline=[""],
            icao_codes=ICAO_CODES,
            file_name=file_name,
        )

        if not os.path.exists(file_name):
            raise HTTPException(status_code=500, detail="데이터 수집 실패: 파일이 생성되지 않았습니다. 서버에서 UBIKAIS API에 접근할 수 없을 수 있습니다.")

        df = pd.read_excel(file_name)
        if df.empty:
            raise HTTPException(status_code=500, detail="데이터 수집 결과가 비어 있습니다. 서버에서 UBIKAIS API에 접근할 수 없을 수 있습니다.")

        _current_df = process_dataframe(df)
        logger.info(f"크롤링 완료: {len(_current_df)} rows")
        return {"status": "ok", "rows": len(_current_df)}

    except Exception as e:
        logger.error(f"크롤링 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload")
async def upload_excel(file: UploadFile = File(...)):
    """엑셀 업로드 → 메모리 캐시"""
    global _current_df
    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        _current_df = process_dataframe(df)
        logger.info(f"업로드 완료: {len(_current_df)} rows")
        return {"status": "ok", "rows": len(_current_df)}
    except Exception as e:
        logger.error(f"업로드 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/metadata")
async def get_metadata():
    """현재 데이터의 고유 국적사, NAT 목록"""
    if _current_df is None:
        raise HTTPException(status_code=404, detail="데이터 없음. 검색 또는 업로드 필요.")

    from data_processor import DOMESTIC_AIRLINES
    airlines = sorted(
        _current_df[_current_df['Carrier_Type'] == '국적사']['Airline_Code']
        .dropna().unique().tolist()
    )
    airlines = [a for a in airlines if a in DOMESTIC_AIRLINES]

    nat_values = []
    if 'NAT' in _current_df.columns:
        nat_values = sorted(_current_df['NAT'].dropna().unique().tolist())

    return {"airlines": airlines, "nat": nat_values}


@app.get("/api/barchart")
async def get_barchart(
    airline: str = Query(default=""),
    nat: str = Query(default=""),
):
    """바차트 표출용 데이터 반환"""
    if _current_df is None:
        raise HTTPException(status_code=404, detail="데이터 없음.")

    nat_list = [n.strip() for n in nat.split(",") if n.strip()] if nat else []
    result = filter_for_barchart(_current_df, airline, nat_list)
    return JSONResponse(content=result)


@app.get("/api/summary")
async def get_summary(nat: str = Query(default=""), airline: str = Query(default="")):
    """좌측 요약 패널용 집계 데이터 반환"""
    if _current_df is None:
        raise HTTPException(status_code=404, detail="데이터 없음.")

    nat_list = [n.strip() for n in nat.split(",") if n.strip()] if nat else []
    result = compute_summary(_current_df, nat_list, airline)
    return JSONResponse(content=result)


@app.get("/api/template")
async def download_template():
    """업로드용 엑셀 양식 템플릿 다운로드"""
    columns = [
        'Sch_date_KST', 'Sort', 'Fltno', 'Depstn', 'Arrstn', 'Acno', 'Actype',
        'Status', 'NAT', 'Stand', 'STD_UTC', 'STA_UTC', 'ATD_UTC', 'ATA_UTC',
        'Blocktime', 'Bt_idx'
    ]
    sample = pd.DataFrame([{
        'Sch_date_KST': '2026-03-16', 'Sort': 'DEP', 'Fltno': 'KE101',
        'Depstn': 'ICN', 'Arrstn': 'PUS', 'Acno': 'HL7234', 'Actype': 'B738',
        'Status': 'ACT', 'NAT': 'D', 'Stand': '101',
        'STD_UTC': '2026-03-16 00:00:00', 'STA_UTC': '2026-03-16 01:20:00',
        'ATD_UTC': '', 'ATA_UTC': '', 'Blocktime': 80, 'Bt_idx': 'Y'
    }], columns=columns)
    buf = io.BytesIO()
    sample.to_excel(buf, index=False)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename=upload_template.xlsx'}
    )


@app.get("/api/download")
async def download_excel(airline: str = Query(default=""), nat: str = Query(default="")):
    """3시트 엑셀 다운로드 (요약/바차트/RAW)"""
    if _current_df is None:
        raise HTTPException(status_code=404, detail="데이터 없음.")

    from data_processor import filter_for_barchart, compute_summary, CARGO_NAT, add_aircraft_type_columns

    nat_list = [n.strip() for n in nat.split(",") if n.strip()] if nat else []

    # Sheet 1: 요약정보 (가동률 + GT 분석)
    summary = compute_summary(_current_df, nat_list, airline)
    op_rows = summary.get('operation_summary', {}).get('rows', {}).get('all', [])
    summary_df = pd.DataFrame(op_rows) if op_rows else pd.DataFrame()

    # GT 분석 데이터를 테이블 형태로 변환
    gt_table = summary.get('gt_table', {})
    gt_excel_rows = []
    for route_key, route_label in [('domestic', '국내선'), ('international', '국제선')]:
        route_data = gt_table.get(route_key, {})
        for al_code, al_data in route_data.items():
            grade_data = al_data.get('grades', {})
            grade_flights = al_data.get('grade_flights', {})
            for grade, bins in grade_data.items():
                grade_label = '전체' if grade == '전체' else f'{grade}급'
                flight_count = grade_flights.get(grade, 0)
                row = {
                    '노선유형': route_label,
                    '항공사': al_code,
                    '등급': grade_label,
                    '운항편수': flight_count,
                }
                for bin_name, bin_val in bins.items():
                    row[f'GT {bin_name} (편수)'] = bin_val['count']
                    row[f'GT {bin_name} (%)'] = bin_val['pct']
                gt_excel_rows.append(row)
    gt_df = pd.DataFrame(gt_excel_rows) if gt_excel_rows else pd.DataFrame()

    # Sheet 2: 바차트 데이터
    barchart_json = filter_for_barchart(_current_df, airline, nat_list)
    bar_rows = []
    for ac in barchart_json.get('aircraft', []):
        for fl in ac.get('flights', []):
            bar_rows.append({
                'Acno': ac['acno'],
                'Fltno': fl['fltno'],
                'Depstn': fl['depstn'],
                'Arrstn': fl['arrstn'],
                'STD_KST': fl['std_kst'],
                'STA_KST': fl['sta_kst'],
                'Blocktime': fl['blocktime'],
                'GT': fl['ground_time_before'],
                'Status': fl['status'],
                'Actype': fl['actype'],
            })
    barchart_df = pd.DataFrame(bar_rows) if bar_rows else pd.DataFrame()

    # Sheet 3: RAW
    raw_df = add_aircraft_type_columns(_current_df)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        # 요약정보 시트: 가동률 테이블 + 빈 행 + GT 분석 테이블
        if not summary_df.empty:
            summary_df.to_excel(writer, sheet_name='요약정보', index=False, startrow=0)
            gt_start_row = len(summary_df) + 3  # 가동률 아래 빈 행 2줄
        else:
            gt_start_row = 0
        if not gt_df.empty:
            gt_df.to_excel(writer, sheet_name='요약정보', index=False, startrow=gt_start_row)
        barchart_df.to_excel(writer, sheet_name='바차트', index=False)
        raw_df.to_excel(writer, sheet_name='RAW', index=False)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename=flight_data_export.xlsx'}
    )


if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import threading

    def _open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:8000")

    threading.Thread(target=_open_browser, daemon=True).start()
    print("서버 시작: http://127.0.0.1:8000")
    print("종료하려면 이 창을 닫거나 Ctrl+C를 누르세요.")
    uvicorn.run(app, host="127.0.0.1", port=8000)
