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

from data_processor import (
    process_dataframe, filter_for_barchart, compute_ontime_records, get_actype_grade,
    apply_flight_cancellation, apply_chain_reassignment, apply_scenario_delay_adjustments,
)


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
    """정적 파일(JS/CSS)과 index.html에 대해 브라우저가 항상 서버에 재검증하도록 강제.

    Cache-Control 헤더가 없으면 브라우저가 휴리스틱 캐싱으로 구버전 JS/HTML을
    계속 사용해, 백엔드 API 응답 구조나 index.html의 DOM 구조가 바뀌어도 프론트가
    갱신되지 않는 문제(예: 가동률 표가 최신 데이터에도 "데이터 없음"으로 표출,
    또는 구버전 HTML의 element id를 신버전 JS가 찾지 못해 발생하는 오류)가 발생한다.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


# 정적 파일 서빙
app.mount("/static", StaticFiles(directory=str(BASE_PATH / "static")), name="static")

# 인메모리 캐시
_current_df: pd.DataFrame | None = None
_current_ontime_cache: dict | None = None
_original_df: pd.DataFrame | None = None  # 크롤링/업로드 직후 스냅샷 (시나리오 초기화용)
_baseline_ontime_cache: dict | None = None  # _original_df 기준 정시율(실적) 캐시
_scenario_chart_df: pd.DataFrame | None = None  # 연결 변경편 RO/RI 재계산 반영된 바차트 표출용 df


def _rebuild_ontime_cache():
    """_current_df 기준으로 정시율 레코드를 1회 계산해 캐싱.

    compute_ontime_records()는 airline/tof/date와 무관하게 항상 동일한 결과를
    반환하므로(필터는 프론트에서 처리), 데이터셋이 바뀌는 시점(업로드/크롤링/
    기번 재배정)에만 재계산하고 /api/ontime GET은 캐시를 그대로 반환한다.

    _current_df를 그대로 넘기지 않고 apply_scenario_delay_adjustments()로 재배정
    캐스케이드(연결 변경편의 RO_KST/RI_KST 재계산)를 먼저 반영한 df를 넘긴다.
    이걸 빠뜨리면 바차트 툴팁의 재계산된 지연시간과 정시율 표의 지연편수 집계가
    서로 다른 RO 값을 기준으로 계산되어 어긋난다. _scenario_chart_df 전역 캐시를
    재사용하지 않고 직접 재계산하는 이유는 호출 순서(_rebuild_scenario_chart_df가
    아직 최신화되지 않았을 수 있음)에 의존하지 않기 위함이다.
    """
    global _current_ontime_cache
    if _current_df is None:
        _current_ontime_cache = None
        return
    adjusted_df = apply_scenario_delay_adjustments(_current_df, _original_df)
    _current_ontime_cache = compute_ontime_records(adjusted_df)


def _rebuild_baseline_ontime_cache():
    """_original_df(크롤링/업로드 직후 스냅샷) 기준 정시율(실적) 레코드 캐싱.

    _original_df는 시나리오 조작(비운항/재배정/드래그/초기화)으로 바뀌지 않으므로
    _original_df가 실제로 새로 설정되는 시점(크롤링/업로드)에만 호출한다.
    """
    global _baseline_ontime_cache
    _baseline_ontime_cache = compute_ontime_records(_original_df)


def _rebuild_scenario_chart_df():
    """연결(Acno)이 바뀐 편들의 RO/RI/연결지연을 재계산해 바차트 표출용 df를 캐싱.

    _rebuild_ontime_cache()와 동일한 시점(업로드/크롤링/드래그재배정/시나리오
    3종/초기화)에 호출한다. /api/barchart는 _current_df 대신 이 df를 사용한다.
    """
    global _scenario_chart_df
    if _current_df is not None:
        _scenario_chart_df = apply_scenario_delay_adjustments(_current_df, _original_df)
    else:
        _scenario_chart_df = None

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


class UpdateAcnoRequest(BaseModel):
    row_id: int
    new_acno: str


class CancelFlightsRequest(BaseModel):
    fltnos: list[str]


class ReassignPattern(BaseModel):
    front_fltno: str
    back_fltno: str


class ReassignChainRequest(BaseModel):
    patterns: list[ReassignPattern]


@app.post("/api/crawl")
async def crawl_data(req: CrawlRequest):
    """func_ubkais.process_flight_schedule() 호출 → 메모리 캐시"""
    global _current_df, _original_df
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
        _original_df = _current_df.copy()
        _rebuild_ontime_cache()
        _rebuild_baseline_ontime_cache()
        _rebuild_scenario_chart_df()
        logger.info(f"크롤링 완료: {len(_current_df)} rows")
        return {"status": "ok", "rows": len(_current_df)}

    except Exception as e:
        logger.error(f"크롤링 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload")
async def upload_excel(file: UploadFile = File(...)):
    """엑셀 업로드 → 메모리 캐시"""
    global _current_df, _original_df
    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))

        if 'NAT' not in df.columns:
            raise HTTPException(status_code=400, detail="필수 컬럼 누락: NAT")
        if df['NAT'].isna().any() or (df['NAT'].astype(str).str.strip() == '').any():
            raise HTTPException(status_code=400, detail="NAT 컬럼에 빈 값이 있는 행이 있습니다.")

        if 'MTTT' not in df.columns:
            raise HTTPException(status_code=400, detail="필수 컬럼 누락: MTTT")
        if df['MTTT'].isna().any():
            raise HTTPException(status_code=400, detail="MTTT 컬럼에 빈 값이 있는 행이 있습니다.")
        try:
            df['MTTT'] = df['MTTT'].astype(int)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="MTTT 컬럼은 정수만 허용합니다.")

        if 'D_OPER' not in df.columns:
            raise HTTPException(status_code=400, detail="필수 컬럼 누락: D_OPER")
        d_oper_str = df['D_OPER'].astype(str).str.strip()
        d_oper_valid = df['D_OPER'].isna() | (d_oper_str == '') | (d_oper_str == 'Y')
        if not d_oper_valid.all():
            raise HTTPException(status_code=400, detail="D_OPER 컬럼은 Y 또는 빈칸만 허용합니다.")

        _current_df = process_dataframe(df)
        _original_df = _current_df.copy()
        _rebuild_ontime_cache()
        _rebuild_baseline_ontime_cache()
        _rebuild_scenario_chart_df()
        logger.info(f"업로드 완료: {len(_current_df)} rows")

        dates = []
        if 'Sch_date_KST' in _current_df.columns:
            dates = sorted(
                pd.to_datetime(_current_df['Sch_date_KST']).dt.date.dropna().unique().tolist()
            )
        return {"status": "ok", "rows": len(_current_df), "dates": [str(d) for d in dates]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"업로드 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/metadata")
async def get_metadata():
    """현재 데이터의 고유 국적사, TOF 목록"""
    if _current_df is None:
        raise HTTPException(status_code=404, detail="데이터 없음. 검색 또는 업로드 필요.")

    from data_processor import DOMESTIC_AIRLINES
    airlines = sorted(
        _current_df[_current_df['Carrier_Type'] == '국적사']['Airline_Code']
        .dropna().unique().tolist()
    )
    airlines = [a for a in airlines if a in DOMESTIC_AIRLINES]

    tof_values = []
    if 'TOF' in _current_df.columns:
        tof_values = sorted(_current_df['TOF'].dropna().unique().tolist())

    fltnos = sorted(_current_df['Fltno'].dropna().astype(str).unique().tolist())

    return {"airlines": airlines, "tof": tof_values, "fltnos": fltnos}


@app.get("/api/barchart")
async def get_barchart(
    airline: str = Query(default=""),
    tof: str = Query(default=""),
    date: str = Query(default=""),
):
    """바차트 표출용 데이터 반환"""
    if _current_df is None:
        raise HTTPException(status_code=404, detail="데이터 없음.")

    tof_list = [t.strip() for t in tof.split(",") if t.strip()] if tof else []
    chart_df = _scenario_chart_df if _scenario_chart_df is not None else _current_df
    result = filter_for_barchart(chart_df, airline, tof_list, date)
    return JSONResponse(content=result)


@app.get("/api/ontime")
async def get_ontime():
    """정시율 분석용 편 단위 레코드 리스트 반환 (필터는 전부 프론트에서 처리)

    airline/tof/date와 무관하게 결과가 항상 동일하므로, 업로드/크롤링/기번재배정
    시점에 미리 계산해둔 캐시(_current_ontime_cache)를 그대로 반환한다.
    - records: _current_df 기준(시나리오 - 비운항/재배정/드래그 등 모든 변경 반영)
    - baseline_records: _original_df 기준(실적 - 크롤링/업로드 직후 원본, 변경 미반영)
    """
    if _current_df is None:
        raise HTTPException(status_code=404, detail="데이터 없음.")

    return JSONResponse(content={
        "records": (_current_ontime_cache or {}).get("records", []),
        "baseline_records": (_baseline_ontime_cache or {}).get("records", []),
    })


@app.get("/api/template")
async def download_template():
    """업로드용 엑셀 양식 템플릿 다운로드"""
    columns = [
        'Sch_date_KST', 'Fltno', 'Depstn', 'Arrstn', 'Acno', 'Actype',
        'TOF', 'STD_UTC', 'STA_UTC', 'RO_UTC', 'RI_UTC',
        'CNX_DLA', 'DEP_DLA', 'ATC_DLA', 'NAT', 'MTTT', 'D_OPER'
    ]
    sample = pd.DataFrame([{
        'Sch_date_KST': '2026-03-16', 'Fltno': 'KE101',
        'Depstn': 'ICN', 'Arrstn': 'PUS', 'Acno': 'HL7234', 'Actype': 'B738',
        'TOF': 'D', 'STD_UTC': '2026-03-16 00:00:00', 'STA_UTC': '2026-03-16 01:20:00',
        'RO_UTC': '2026-03-16 00:05:00', 'RI_UTC': '2026-03-16 01:15:00',
        'CNX_DLA': 0, 'DEP_DLA': 5, 'ATC_DLA': 0,
        'NAT': '예시 메모', 'MTTT': 60, 'D_OPER': 'Y'
    }], columns=columns)
    buf = io.BytesIO()
    sample.to_excel(buf, index=False)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename=upload_template.xlsx'}
    )


@app.post("/api/update-acno")
async def update_acno(req: UpdateAcnoRequest):
    """드래그 재배정: 특정 원본 행의 Acno(+ 파생 Actype/Actype_Grade)를 변경"""
    global _current_df
    if _current_df is None:
        raise HTTPException(status_code=404, detail="데이터 없음.")

    if req.row_id not in _current_df.index:
        raise HTTPException(status_code=404, detail=f"row_id {req.row_id}에 해당하는 행을 찾을 수 없습니다. 데이터가 갱신되었을 수 있습니다.")

    new_acno = req.new_acno.strip()
    old_acno = str(_current_df.loc[req.row_id, 'Acno'])

    if new_acno == '':
        # 바차트 CANCEL 행으로 드롭한 경우: 기번 재배정이 아니라 비운항 처리.
        # apply_flight_cancellation()과 동일하게 Acno/D_OPER만 비우고 Actype은 유지한다.
        if old_acno == '':
            return {"status": "ok", "changed": False, "old_acno": old_acno, "new_acno": "CANCEL"}

        sch_date = _current_df.loc[req.row_id, 'Sch_date_KST']
        fltno = _current_df.loc[req.row_id, 'Fltno']
        pair_mask = (
            (_current_df['Sch_date_KST'] == sch_date) &
            (_current_df['Fltno'] == fltno) &
            (_current_df['Status'] != 'CNL')
        )
        _current_df.loc[pair_mask, 'Acno'] = ''
        _current_df.loc[pair_mask, 'D_OPER'] = ''
        _rebuild_ontime_cache()
        _rebuild_scenario_chart_df()

        logger.info(f"드래그 비운항 처리: row_id={req.row_id} Fltno={fltno} {old_acno} -> CANCEL (대상행수={int(pair_mask.sum())})")
        return {
            "status": "ok", "changed": True,
            "old_acno": old_acno, "new_acno": "CANCEL",
        }

    if new_acno not in _current_df['Acno'].astype(str).values:
        raise HTTPException(status_code=400, detail=f"기번 '{new_acno}'이(가) 현재 데이터에 존재하지 않습니다.")

    if old_acno == new_acno:
        return {"status": "ok", "changed": False, "old_acno": old_acno, "new_acno": new_acno}

    target_rows = _current_df[_current_df['Acno'].astype(str) == new_acno]
    actype_mode = target_rows['Actype'].mode()
    new_actype = str(actype_mode.iloc[0]) if not actype_mode.empty else str(_current_df.loc[req.row_id, 'Actype'])

    # Bt_idx는 Sch_date_KST+Fltno로 그룹화되어 DEP/ARR 짝을 이루므로(func_ubkais.py assign_bt_idx),
    # 같은 편의 짝 레코드도 함께 갱신하지 않으면 RAW 시트에서 기번이 어긋난다.
    sch_date = _current_df.loc[req.row_id, 'Sch_date_KST']
    fltno = _current_df.loc[req.row_id, 'Fltno']
    pair_mask = (_current_df['Sch_date_KST'] == sch_date) & (_current_df['Fltno'] == fltno)

    _current_df.loc[pair_mask, 'Acno'] = new_acno
    _current_df.loc[pair_mask, 'Actype'] = new_actype
    _current_df.loc[pair_mask, 'Actype_Grade'] = get_actype_grade(new_actype)
    _rebuild_ontime_cache()
    _rebuild_scenario_chart_df()

    logger.info(f"기번 재배정: row_id={req.row_id} {old_acno} -> {new_acno} (Actype={new_actype}, 대상행수={int(pair_mask.sum())})")
    return {
        "status": "ok", "changed": True,
        "old_acno": old_acno, "new_acno": new_acno, "new_actype": new_actype,
    }


@app.post("/api/scenario/cancel-flights")
async def scenario_cancel_flights(req: CancelFlightsRequest):
    """비운항 시나리오: 선택 편명을 전체 로드 기간에서 일괄 비운항 처리(Acno/D_OPER 빈칸)"""
    global _current_df
    if _current_df is None:
        raise HTTPException(status_code=404, detail="데이터 없음.")

    report = apply_flight_cancellation(_current_df, req.fltnos)
    _rebuild_ontime_cache()
    _rebuild_scenario_chart_df()
    logger.info(f"비운항 시나리오 적용: {report}")
    return {"status": "ok", **report}


@app.post("/api/scenario/reassign-chain")
async def scenario_reassign_chain(req: ReassignChainRequest):
    """스케줄 조정 시나리오: 앞편-뒤편 패턴을 순차 적용, 패턴별 적용/변경없음/스킵 날짜 리포트"""
    global _current_df
    if _current_df is None:
        raise HTTPException(status_code=404, detail="데이터 없음.")

    patterns = [(p.front_fltno, p.back_fltno) for p in req.patterns]
    results = apply_chain_reassignment(_current_df, patterns)
    _rebuild_ontime_cache()
    _rebuild_scenario_chart_df()
    logger.info(f"스케줄 조정 시나리오 적용: {len(results)}개 패턴")
    return {"status": "ok", "results": results}


@app.post("/api/scenario/reset")
async def scenario_reset():
    """시나리오 초기화: 크롤링/업로드 시점 원본 스냅샷으로 복원(드래그 재배정 포함 모든 변경 취소)"""
    global _current_df
    if _original_df is None:
        raise HTTPException(status_code=404, detail="복원할 원본 데이터가 없습니다.")

    _current_df = _original_df.copy()
    _rebuild_ontime_cache()
    _rebuild_scenario_chart_df()
    logger.info("시나리오 초기화: 원본 스냅샷으로 복원")
    return {"status": "ok", "rows": len(_current_df)}


@app.get("/api/download")
async def download_excel(airline: str = Query(default=""), tof: str = Query(default=""), date: str = Query(default="")):
    """3시트 엑셀 다운로드 (정시율분석/바차트/RAW)"""
    if _current_df is None:
        raise HTTPException(status_code=404, detail="데이터 없음.")

    from data_processor import filter_for_barchart, add_aircraft_type_columns

    tof_list = [t.strip() for t in tof.split(",") if t.strip()] if tof else []

    # Sheet 1: 정시율분석 (지연기준 15분 고정, 필터 없이 전체 기준 날짜별 집계)
    ONTIME_DELAY_THRESHOLD = 15
    ontime_records = (_current_ontime_cache or {}).get('records', [])
    ontime_rows = []
    if ontime_records:
        ontime_df = pd.DataFrame(ontime_records)
        for date_val, group in ontime_df.groupby('date'):
            total = len(group)
            delayed = int((group['delay_min'] > ONTIME_DELAY_THRESHOLD).sum())
            rate = round((1 - delayed / total) * 100, 1) if total > 0 else 0.0
            ontime_rows.append({
                '날짜': date_val,
                '운항편수': total,
                '지연편수': delayed,
                '정시율(%)': rate,
            })
        ontime_rows.sort(key=lambda r: r['날짜'])
    summary_df = pd.DataFrame(ontime_rows) if ontime_rows else pd.DataFrame()

    # Sheet 2: 바차트 데이터
    barchart_json = filter_for_barchart(_current_df, airline, tof_list, date)
    bar_rows = []
    for ac in barchart_json.get('aircraft', []):
        for fl in ac.get('flights', []):
            bar_rows.append({
                'Acno': ac['acno'],
                'Fltno': fl['fltno'],
                'Depstn': fl['depstn'],
                'Arrstn': fl['arrstn'],
                'RO_KST': fl['ro_kst'],
                'RI_KST': fl['ri_kst'],
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
        summary_df.to_excel(writer, sheet_name='정시율분석', index=False)
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
