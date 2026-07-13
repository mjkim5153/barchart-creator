import pandas as pd
import numpy as np
from datetime import timedelta

KOREAN_AIRPORTS = {
    'ICN', 'GMP', 'PUS', 'CJU', 'KWJ', 'CJJ', 'YNY', 'CNJ', 'MWX',
    'TAE', 'HIN', 'KUV', 'KPO', 'RSU', 'USN', 'WJU', 'CHN', 'JDG', 'JCN'
}

DOMESTIC_AIRLINES = {
    'KAL', 'AAR', 'JJA', 'TWB', 'JNA', 'ESR', 'ABL', 'ASV', 'EOK', 'PTA', 'APZ'
}

CARGO_TOF = {'CGE', 'CGO', 'CGC'}

# 대한항공(KAL) ICN 국제선 연결용 지선(피더) 공항 — 현재 KAL만 해당 확인됨, 향후 타사/타 공항 확인 시 확장
KAL_FEEDER_AIRPORTS = {'PUS', 'TAE'}

# #10 Actype 등급
ACTYPE_GRADE = {}
_grade_map = {
    'A': ['AT7', 'DH8', 'E19', 'CRJ'],
    'B': ['E75', 'E90'],
    'C': ['B737', 'B738', 'B739', 'B38M', 'A319', 'A320', 'A321', 'A20N', 'A21N', 'BCS'],
    'D': ['B767'],
    'E': ['B777', 'B772', 'B773', 'B77W', 'A350', 'A359', 'B747', 'B748', 'A380', 'A388', 'B787', 'B788', 'B789', 'B78X', 'A330', 'A332', 'A333'],
}
for grade, types in _grade_map.items():
    for t in types:
        ACTYPE_GRADE[t] = grade


def get_actype_grade(actype: str) -> str:
    """기종 코드에서 등급을 조회 (정확한 일치 후 prefix 매칭)"""
    if not actype:
        return ''

    # 1단계: 정확한 매핑
    if actype in ACTYPE_GRADE:
        return ACTYPE_GRADE[actype]

    # 2단계: Prefix 매칭 (BCS 계열: BCS, BCS2, BCS3, ...)
    if actype.startswith('BCS'):
        return 'C'

    return ''


REQUIRED_COLUMNS = {
    'Sch_date_KST', 'Fltno', 'Depstn', 'Arrstn', 'Acno', 'Actype',
    'TOF', 'STD_UTC', 'STA_UTC'
}


def process_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """func_ubkais.py 출력 DataFrame에 누락 컬럼 추가 후처리"""
    df = df.copy()

    # 필수 컬럼 검증
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"필수 컬럼 누락: {', '.join(sorted(missing))}. 데이터 수집이 정상적으로 완료되지 않았을 수 있습니다.")

    # Airline_Code: Fltno 앞 3글자
    df['Airline_Code'] = df['Fltno'].str[:3]

    # STD_KST, STA_KST: UTC+9
    for utc_col, kst_col in [('STD_UTC', 'STD_KST'), ('STA_UTC', 'STA_KST')]:
        if utc_col in df.columns:
            df[kst_col] = pd.to_datetime(df[utc_col]) + timedelta(hours=9)
        else:
            df[kst_col] = pd.NaT

    # RO_KST, RI_KST: 실적(Actual) Out/In 시각, UTC+9 (없으면 NaT — 바차트에서 결측 경고 처리)
    for utc_col, kst_col in [('RO_UTC', 'RO_KST'), ('RI_UTC', 'RI_KST')]:
        if utc_col in df.columns:
            df[kst_col] = pd.to_datetime(df[utc_col]) + timedelta(hours=9)
        else:
            df[kst_col] = pd.NaT

    # 지연 지표(결항/출발/관제): 없으면 NaN, 있으면 숫자로 정제 (바차트 툴팁 표시용)
    for col in ('CNX_DLA', 'DEP_DLA', 'ATC_DLA'):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        else:
            df[col] = np.nan

    # Status: 없으면 전부 유효편(ACT)으로 간주 (엑셀 업로드는 유효편만 입력한다고 가정)
    if 'Status' not in df.columns:
        df['Status'] = 'ACT'

    # Bt_idx: 없으면 전부 Y (엑셀 업로드는 편당 1행만 입력한다고 가정, DEP/ARR 중복 없음)
    if 'Bt_idx' not in df.columns:
        df['Bt_idx'] = 'Y'

    # Blocktime: 없으면 STD_KST/STA_KST 차이(분)로 계산
    if 'Blocktime' not in df.columns:
        df['Blocktime'] = (
            (df['STA_KST'] - df['STD_KST']).dt.total_seconds() / 60
        ).round().astype(int)

    # Domestic_Intl (벡터화: 행 단위 apply 대신 isin 기반 마스크 연산)
    dep_kr = df['Depstn'].isin(KOREAN_AIRPORTS)
    arr_kr = df['Arrstn'].isin(KOREAN_AIRPORTS)
    df['Domestic_Intl'] = np.where(dep_kr & arr_kr, '국내선', '국제선')

    # Carrier_Type
    df['Carrier_Type'] = df['Airline_Code'].apply(
        lambda x: '국적사' if x in DOMESTIC_AIRLINES else '외항사'
    )

    # #10 Actype_Grade (정확한 일치 후 prefix 매칭)
    df['Actype_Grade'] = df['Actype'].apply(get_actype_grade)

    return df


def _filter_by_sch_date(df: pd.DataFrame, date_str: str) -> pd.DataFrame:
    """date_str(YYYY-MM-DD)이 주어지면 Sch_date_KST가 일치하는 행만 반환"""
    if not date_str or 'Sch_date_KST' not in df.columns:
        return df
    target = pd.to_datetime(date_str).date()
    return df[pd.to_datetime(df['Sch_date_KST']).dt.date == target]


def _sort_key_series(df: pd.DataFrame) -> pd.Series:
    """RO_KST(실적) 오름차순 정렬용 키. 결측 시 STD_KST로 순서만 보완
    (barchart_display_rules.md 2번 규칙과 동일 — 그려지는 시각/BT/GT 자체는
    여전히 RO/RI 기준이며, 이 키는 그룹 내 순서 결정 전용).
    """
    return df['RO_KST'].fillna(df['STD_KST'])


def _na_safe_equal(a: pd.Series, b: pd.Series) -> pd.Series:
    """NaT/NaN을 서로 같은 값으로 취급하는 벡터화 비교 (datetime/숫자 Series 공용)."""
    a_na = a.isna()
    b_na = b.isna()
    both_na = a_na & b_na
    return both_na | (~a_na & ~b_na & (a == b))


def _build_predecessor_map(df: pd.DataFrame) -> dict:
    """유효편(Status!=CNL, Bt_idx==Y, Acno!='')을 (Sch_date_KST, Acno)로 그룹핑해
    각 행(원본 df 인덱스)이 그 체인 안에서 바로 앞에 연결된 편의 인덱스/RI_KST를
    갖도록 매핑한다. 체인의 첫 편은 {'pred_idx': None, 'pred_ri': None}.

    반환: {row_index: {'pred_idx': int|None, 'pred_ri': Timestamp|None}}

    구현 노트: 그룹별로 DataFrame을 물리적으로 분리해 iterrows()를 도는 대신,
    전체를 (Sch_date_KST, Acno, 정렬키) 기준 한 번만 정렬한 뒤 shift(1)로
    "바로 이전 행"을 벡터화 계산한다(그룹 수가 많을 때 groupby 서브프레임 생성
    오버헤드가 지배적이었음 — 실측 기준 52k행/13,881개 그룹에서 13초 이상 소요,
    벡터화 후 0.1초). pandas groupby(dropna=True 기본값)와 동일하게 그룹 키
    (Sch_date_KST 또는 Acno)가 NaT/NaN인 행은 결과에서 제외한다.
    """
    result = {}
    if df.empty or 'Acno' not in df.columns:
        return result

    valid = df[
        (df['Status'] != 'CNL') & (df['Bt_idx'] == 'Y') &
        (df['Acno'].astype(str).str.strip() != '') &
        df['Sch_date_KST'].notna() & df['Acno'].notna()
    ].copy()
    if valid.empty:
        return result

    valid['_sk'] = _sort_key_series(valid)
    sv = valid.sort_values(['Sch_date_KST', 'Acno', '_sk'])

    same_as_prev = (
        (sv['Sch_date_KST'] == sv['Sch_date_KST'].shift(1)) &
        (sv['Acno'] == sv['Acno'].shift(1))
    ).tolist()
    prev_idx_list = sv.index.tolist()
    prev_ri_list = sv['RI_KST'].tolist()

    for i, idx in enumerate(prev_idx_list):
        if same_as_prev[i]:
            pred_idx = prev_idx_list[i - 1]
            pred_ri = prev_ri_list[i - 1]
            result[idx] = {'pred_idx': pred_idx, 'pred_ri': pred_ri if pd.notna(pred_ri) else None}
        else:
            result[idx] = {'pred_idx': None, 'pred_ri': None}
    return result


def compute_scenario_delay_adjustments(current_df: pd.DataFrame, original_df: pd.DataFrame) -> dict:
    """연결(Acno)이 바뀐 편들의 실적 RO/RI/연결지연(CNX_DLA)을 캐스케이딩 재계산한다.

    새로 연결된 직전편의 RI를 기준으로 물리적 최소 연결지연(턴어라운드 하한)을 다시 계산한다:
        필요 정비완료시각 = 직전편 RI + MTTT
        새 연결지연(CNX_DLA) = max(0, 필요 정비완료시각 - STD)
        DEP_DLA/ATC_DLA 등 연결과 무관한 지연 성분(= 원본 RO - STD - 원본 CNX_DLA)은 그대로
        보존하여 새 RO = STD + 새 연결지연 + 연결외지연성분, 새 RI = 새 RO + 원본 블록타임(RI-RO)
    을 계산한다. 기존 연결지연(orig_cnx)은 더 이상 새 지연의 기준선(빼는 대상)으로 쓰지 않고,
    연결외지연성분을 분리해내는 용도로만 쓴다 — 새 연결이 이전보다 여유가 있든(양수 슬랙)
    부족하든(음수 슬랙) 항상 동일한 물리 모델(하한선)로 재계산되므로, "여유가 조금 부족한
    연결로 바꿨는데 기존 지연 위에 그대로 얹혀 더 크게 늘어나는" 부호 오류가 발생하지 않는다.
    직전편의 RI 자체가 이미 재계산된 값이면 그 값을 그대로 이어받아 하위 체인까지 연쇄적으로
    (cascading) 반영한다. 연결 대상·시간이 원본과 동일하면 조정하지 않는다. STD/MTTT/직전RI/
    원본RO·RI 중 하나라도 없으면 그 편은 조정을 건너뛰고(원본 유지) 캐스케이드가 거기서 끊긴다.

    반환: {row_index: {'ro_kst': Timestamp, 'ri_kst': Timestamp, 'cnx_dla': float}}
    (조정이 실제 적용된 행만 포함)
    """
    adjustments = {}
    if current_df.empty or 'Acno' not in current_df.columns:
        return adjustments

    orig_pred_map = _build_predecessor_map(original_df) if original_df is not None else {}

    valid = current_df[
        (current_df['Status'] != 'CNL') & (current_df['Bt_idx'] == 'Y') &
        (current_df['Acno'].astype(str).str.strip() != '') &
        current_df['Sch_date_KST'].notna() & current_df['Acno'].notna()
    ].copy()
    if valid.empty:
        return adjustments

    valid['_sk'] = _sort_key_series(valid)
    # 그룹별 DataFrame 물리적 분리(iterrows) 대신 한 번만 정렬한 뒤 그룹 경계만
    # 표시해 순회한다 — 캐스케이드 자체는 체인 내에서 순차 의존적이라 값 계산
    # 로직은 그대로 유지하되, groupby 서브프레임 생성 오버헤드만 제거한다.
    sv = valid.sort_values(['Sch_date_KST', 'Acno', '_sk'])
    is_first_in_group = ~(
        (sv['Sch_date_KST'] == sv['Sch_date_KST'].shift(1)) &
        (sv['Acno'] == sv['Acno'].shift(1))
    )

    idx_list = sv.index.tolist()
    ri_list = sv['RI_KST'].tolist()
    std_list = sv['STD_KST'].tolist()
    mttt_list = pd.to_numeric(sv['MTTT'], errors='coerce').tolist() if 'MTTT' in sv.columns else [np.nan] * len(sv)
    first_list = is_first_in_group.tolist()

    has_orig = original_df is not None
    orig_ro_col = original_df['RO_KST'] if has_orig else None
    orig_ri_col = original_df['RI_KST'] if has_orig else None
    orig_cnx_col = original_df['CNX_DLA'] if has_orig and 'CNX_DLA' in original_df.columns else None
    orig_index = original_df.index if has_orig else None

    prev_idx = None
    prev_ri_effective = None

    for i, idx in enumerate(idx_list):
        if first_list[i]:
            prev_idx = idx
            prev_ri_effective = ri_list[i] if pd.notna(ri_list[i]) else None
            continue

        orig_info = orig_pred_map.get(idx, {})
        pred_idx_orig = orig_info.get('pred_idx')
        pred_ri_orig = orig_info.get('pred_ri')

        same_connection = (
            prev_idx == pred_idx_orig and
            ((pd.isna(prev_ri_effective) and pd.isna(pred_ri_orig)) or prev_ri_effective == pred_ri_orig)
        )

        if same_connection or pd.isna(prev_ri_effective) or not has_orig or idx not in orig_index:
            prev_idx = idx
            prev_ri_effective = ri_list[i] if pd.notna(ri_list[i]) else None
            continue

        std = std_list[i]
        mttt = mttt_list[i]
        orig_ro = orig_ro_col.at[idx]
        orig_ri = orig_ri_col.at[idx]
        orig_cnx_raw = orig_cnx_col.at[idx] if orig_cnx_col is not None else np.nan
        orig_cnx = float(orig_cnx_raw) if pd.notna(orig_cnx_raw) else 0.0

        if pd.isna(std) or pd.isna(mttt) or pd.isna(orig_ro) or pd.isna(orig_ri):
            # 계산에 필요한 값이 없으면 조정 불가 -> 원본 유지, 캐스케이드 단절
            prev_idx = idx
            prev_ri_effective = ri_list[i] if pd.notna(ri_list[i]) else None
            continue

        available_slack_min = (std - prev_ri_effective).total_seconds() / 60 - float(mttt)
        new_cnx = max(0.0, -available_slack_min)

        # DEP_DLA/ATC_DLA 등 연결과 무관한 지연 성분 (원본 RO에서 STD·원본 연결지연을 뺀 나머지, 고정값으로 보존)
        non_cnx_extra = orig_ro - std - pd.Timedelta(minutes=orig_cnx)
        new_ro = std + pd.Timedelta(minutes=new_cnx) + non_cnx_extra
        new_ri = new_ro + (orig_ri - orig_ro)  # 원본 블록타임(RI-RO) 보존

        adjustments[idx] = {'ro_kst': new_ro, 'ri_kst': new_ri, 'cnx_dla': new_cnx}

        prev_idx = idx
        prev_ri_effective = new_ri

    return adjustments


def apply_scenario_delay_adjustments(current_df: pd.DataFrame, original_df) -> pd.DataFrame:
    """연결이 바뀐 편들의 RO/RI/CNX_DLA를 재계산해 반영하고, 툴팁 비교용 원본 값과
    변경 여부(_scenario_changed) 컬럼을 추가한 바차트 표출 전용 작업용 df를 반환한다
    (인자로 받은 current_df/original_df 자체는 건드리지 않음).

    original_df가 없으면(아직 크롤링/업로드 전) 재계산 없이 원본 df만 반환한다.
    """
    df = current_df.copy()
    df['_orig_acno'] = None
    df['_orig_actype'] = None
    df['_orig_ro_kst'] = pd.NaT
    df['_orig_ri_kst'] = pd.NaT
    df['_orig_cnx_dla'] = np.nan
    df['_scenario_changed'] = False

    if original_df is None or original_df.empty:
        return df

    common_idx = df.index.intersection(original_df.index)
    if len(common_idx) == 0:
        return df

    df.loc[common_idx, '_orig_acno'] = original_df.loc[common_idx, 'Acno']
    df.loc[common_idx, '_orig_actype'] = original_df.loc[common_idx, 'Actype']
    df.loc[common_idx, '_orig_ro_kst'] = original_df.loc[common_idx, 'RO_KST']
    df.loc[common_idx, '_orig_ri_kst'] = original_df.loc[common_idx, 'RI_KST']
    df.loc[common_idx, '_orig_cnx_dla'] = original_df.loc[common_idx, 'CNX_DLA']

    adjustments = compute_scenario_delay_adjustments(df, original_df)
    for idx, adj in adjustments.items():
        df.at[idx, 'RO_KST'] = adj['ro_kst']
        df.at[idx, 'RI_KST'] = adj['ri_kst']
        df.at[idx, 'CNX_DLA'] = adj['cnx_dla']

    in_common = df.index.isin(common_idx)
    acno_diff = df['Acno'].astype(str) != df['_orig_acno'].astype(str)
    actype_diff = df['Actype'].astype(str) != df['_orig_actype'].astype(str)
    ro_diff = ~_na_safe_equal(df['RO_KST'], df['_orig_ro_kst'])
    ri_diff = ~_na_safe_equal(df['RI_KST'], df['_orig_ri_kst'])
    cnx_diff = ~_na_safe_equal(df['CNX_DLA'], df['_orig_cnx_dla'])

    df['_scenario_changed'] = (acno_diff | actype_diff | ro_diff | ri_diff | cnx_diff) & in_common

    return df


def _assign_overlap_lanes(std_ri_pairs: list) -> tuple:
    """같은 Acno 안에서 겹치는 편을 위/아래로 배치하기 위한 lane 배정.

    std_ri_pairs: `_sort_key` 순서로 정렬된 (STD_KST, RI_KST) 튜플 리스트.
    직전 편의 RI_KST 대비 다음 편의 STD_KST가 같거나 더 이르면(지연 BAR가 직전 편
    쪽으로 겹쳐 그려짐) 겹침으로 보고 직전과 다른 lane(0/1 토글)을 배정한다.
    """
    lanes = []
    prev_ri = None
    cur_lane = 0
    for std, ri in std_ri_pairs:
        if prev_ri is not None and pd.notna(std) and std <= prev_ri:
            cur_lane = 1 - cur_lane
        else:
            cur_lane = 0
        lanes.append(cur_lane)
        if pd.notna(ri):
            prev_ri = ri
    lane_count = (max(lanes) + 1) if lanes else 1
    return lanes, lane_count


def filter_for_barchart(df: pd.DataFrame, airline: str, tof_list: list, date_str: str = '') -> dict:
    """바차트 표출용 데이터 필터링 및 JSON 변환"""
    df = _filter_by_sch_date(df, date_str)

    # 기본 필터: Status != CNL, Bt_idx == Y
    filtered = df[
        (df['Status'] != 'CNL') &
        (df['Bt_idx'] == 'Y')
    ].copy()

    # 여객기만: TOF not in CARGO_TOF
    if 'TOF' in filtered.columns:
        filtered = filtered[~filtered['TOF'].isin(CARGO_TOF)]

    # 항공사 필터
    if airline:
        filtered = filtered[filtered['Airline_Code'] == airline]

    # TOF 필터
    if tof_list and 'TOF' in filtered.columns:
        filtered = filtered[filtered['TOF'].isin(tof_list)]

    missing_ro_ri = []
    has_scenario_cols = '_scenario_changed' in filtered.columns

    # groupby('Acno')는 기본적으로 Acno가 NaN인 행을 모든 그룹에서 제외한다
    # (dropna=True) — 아래 벡터화 버전에서도 동일하게 제외해야 'nan' 문자열의
    # 유령 기재가 생기지 않는다.
    filtered = filtered[filtered['Acno'].notna()]

    if filtered.empty:
        return {'aircraft': [], 'missing_ro_ri': missing_ro_ri}

    def _dla_value(val):
        return int(val) if pd.notna(val) else None

    # 원래는 Acno별로 groupby한 뒤 그룹마다 DataFrame을 copy/sort_values/reset_index
    # 했으나(그룹 수만큼 pandas 내부 BlockManager 재생성 비용이 누적되어 느렸음),
    # 전체를 (Acno, 정렬키) 기준으로 한 번만 정렬한 뒤 Acno가 바뀌는 경계만 찾아
    # 순수 파이썬 리스트 슬라이싱으로 그룹을 순회한다. row_id는 원본 DataFrame의
    # 인덱스(=/api/update-acno가 참조하는 _current_df.index)를 그대로 사용한다.
    # _orig_pos: 같은 Acno에서 _sort_key까지 동일한 동시각 편(예: DIV/RAMP RETURN
    # 중복 레코드)이 있을 때, 정렬 알고리즘에 따라 우연히 뒤바뀌지 않도록 원본 데이터
    # 순서를 명시적 3차 정렬 키로 고정한다(원래 그룹별 sort_values는 이런 동률을
    # quicksort의 비보장 동작에 맡기고 있었음).
    filtered['_sort_key'] = _sort_key_series(filtered)
    filtered['_orig_pos'] = np.arange(len(filtered))
    sv = filtered.sort_values(['Acno', '_sort_key', '_orig_pos'])

    n = len(sv)
    acno_l = sv['Acno'].tolist()
    row_id_l = sv.index.tolist()

    def _col(name, default_list):
        return sv[name].tolist() if name in sv.columns else default_list

    depstn_l = _col('Depstn', [''] * n)
    arrstn_l = _col('Arrstn', [''] * n)
    domestic_intl_l = _col('Domestic_Intl', [''] * n)
    ro_kst_l = sv['RO_KST'].tolist()
    ri_kst_l = sv['RI_KST'].tolist()
    std_kst_l = sv['STD_KST'].tolist()
    sta_kst_l = sv['STA_KST'].tolist()
    fltno_l = _col('Fltno', [''] * n)
    actype_l = _col('Actype', [''] * n)
    actype_grade_l = _col('Actype_Grade', [''] * n)
    status_l = _col('Status', [''] * n)
    tof_l = _col('TOF', [''] * n)
    nat_l = _col('NAT', [None] * n)
    mttt_l = _col('MTTT', [None] * n)
    cnx_dla_l = _col('CNX_DLA', [None] * n)
    dep_dla_l = _col('DEP_DLA', [None] * n)
    atc_dla_l = _col('ATC_DLA', [None] * n)

    if has_scenario_cols:
        acno_orig_l = sv['_orig_acno'].tolist()
        actype_orig_l = sv['_orig_actype'].tolist()
        ro_kst_orig_l = sv['_orig_ro_kst'].tolist()
        ri_kst_orig_l = sv['_orig_ri_kst'].tolist()
        cnx_dla_orig_l = sv['_orig_cnx_dla'].tolist()
        scenario_changed_l = sv['_scenario_changed'].tolist()

    result = []
    group_start = 0
    for pos in range(1, n + 1):
        if pos < n and acno_l[pos] == acno_l[group_start]:
            continue
        group_end = pos  # [group_start, group_end) 구간이 하나의 Acno 그룹

        acno = acno_l[group_start]
        lanes, lane_count = _assign_overlap_lanes(
            list(zip(std_kst_l[group_start:group_end], ri_kst_l[group_start:group_end]))
        )

        flights = []
        connection_error_acno = False

        for idx in range(group_start, group_end):
            i = idx - group_start  # 그룹 내 상대 위치 (0-base)

            # 배경색
            dep = str(depstn_l[idx]).strip()
            arr = str(arrstn_l[idx]).strip()
            domestic_intl_val = str(domestic_intl_l[idx]).strip()
            if domestic_intl_val == '국내선':
                color = 'navy' if (dep == 'CJU' or arr == 'CJU') else 'cobalt'
            else:
                color = 'gray'

            is_first_row = (i == 0)

            # 연결 오류 검증
            connection_error = False
            if not is_first_row:
                prev_arr = str(arrstn_l[idx - 1])
                if prev_arr != dep:
                    connection_error = True
                    connection_error_acno = True

            ro_kst = ro_kst_l[idx]
            ri_kst = ri_kst_l[idx]
            fltno = str(fltno_l[idx])

            # RO/RI 결측 시 STD/STA로 폴백하지 않고 경고 목록에 수집
            missing_parts = []
            if pd.isna(ro_kst):
                missing_parts.append('RO')
            if pd.isna(ri_kst):
                missing_parts.append('RI')
            if missing_parts:
                missing_ro_ri.append({
                    'acno': str(acno),
                    'fltno': fltno,
                    'missing': ','.join(missing_parts),
                })

            # Ground Time: 이전편 RI_KST(실적 In) ~ 해당편 RO_KST(실적 Out)
            ground_time_before = None
            if not is_first_row:
                prev_ri = ri_kst_l[idx - 1]
                if pd.notna(prev_ri) and pd.notna(ro_kst):
                    gt_minutes = int((ro_kst - prev_ri).total_seconds() / 60)
                    ground_time_before = gt_minutes

            # 실적 블록타임: RI_KST - RO_KST (요약 영역의 계획 Blocktime과는 별개)
            actual_blocktime = None
            if pd.notna(ro_kst) and pd.notna(ri_kst):
                actual_blocktime = int((ri_kst - ro_kst).total_seconds() / 60)

            # #7 domestic_intl 전달
            domestic_intl = str(domestic_intl_l[idx])

            if has_scenario_cols:
                acno_orig = acno_orig_l[idx]
                actype_orig = actype_orig_l[idx]
                ro_kst_orig = ro_kst_orig_l[idx]
                ri_kst_orig = ri_kst_orig_l[idx]
                cnx_dla_orig = cnx_dla_orig_l[idx]
                scenario_changed = bool(scenario_changed_l[idx])
            else:
                acno_orig = actype_orig = ro_kst_orig = ri_kst_orig = cnx_dla_orig = None
                scenario_changed = False

            nat_val = nat_l[idx]
            mttt_val = mttt_l[idx]

            flights.append({
                'row_id': int(row_id_l[idx]),
                'fltno': fltno,
                'depstn': dep,
                'arrstn': arr,
                'ro_kst': ro_kst.isoformat() if pd.notna(ro_kst) else None,
                'ri_kst': ri_kst.isoformat() if pd.notna(ri_kst) else None,
                'std_kst': std_kst_l[idx].isoformat() if pd.notna(std_kst_l[idx]) else None,
                'sta_kst': sta_kst_l[idx].isoformat() if pd.notna(sta_kst_l[idx]) else None,
                'blocktime': actual_blocktime,
                'actype': str(actype_l[idx]),
                'actype_grade': str(actype_grade_l[idx]),
                'status': str(status_l[idx]),
                'tof': str(tof_l[idx]),
                'nat': (str(nat_val).strip() if pd.notna(nat_val) and str(nat_val).strip() else None),
                'mttt': (int(mttt_val) if pd.notna(mttt_val) else None),
                'domestic_intl': domestic_intl,
                'color': color,
                'connection_error': connection_error,
                'ground_time_before': ground_time_before,
                'cnx_dla': _dla_value(cnx_dla_l[idx]),
                'dep_dla': _dla_value(dep_dla_l[idx]),
                'atc_dla': _dla_value(atc_dla_l[idx]),
                'lane': int(lanes[i]),
                'acno_orig': (str(acno_orig) if pd.notna(acno_orig) else None),
                'actype_orig': (str(actype_orig) if pd.notna(actype_orig) else None),
                'ro_kst_orig': (ro_kst_orig.isoformat() if pd.notna(ro_kst_orig) else None),
                'ri_kst_orig': (ri_kst_orig.isoformat() if pd.notna(ri_kst_orig) else None),
                'cnx_dla_orig': _dla_value(cnx_dla_orig),
                'scenario_changed': scenario_changed,
            })

        result.append({
            'acno': str(acno),
            'connection_error': connection_error_acno,
            'lane_count': int(lane_count),
            'flights': flights,
        })

        group_start = group_end

    # Acno 알파벳 순 정렬
    result.sort(key=lambda x: x['acno'])

    return {'aircraft': result, 'missing_ro_ri': missing_ro_ri}


def _aircraft_type_acno_sets(df: pd.DataFrame) -> dict:
    """Acno별 인천기재/국내기재 판정 (filters.js의 filterAircraftByType과 동일 규칙)

    해당 Acno가 가진 항공편 중 하나라도 조건에 맞으면 그 기재 유형에 포함시킨다.

    예외 1: KAL 지선편(PUS/TAE↔ICN, NAT=PAX) 이후 해당 Acno의 나머지 모든 편이
    국제선이면(ICN 경유 여부 무관 — PUS/TAE발 국제선도 포함), 그 지선편은 국내기재
    판정에서 제외한다 (인천기재 판정에는 영향 없음).

    예외 2: 그날 ICN을 전혀 경유하지 않는 Acno가 국내 비-ICN 공항(GMP/PUS 등)을
    기점/종점으로 국제선을 운항하면(예: GMP-KIX, PUS-PVG), 그 Acno는 국내기재로
    분류한다 — ICN 기반이 아니라 지방공항을 거점으로 하는 기재이기 때문.
    """
    if df.empty or 'Acno' not in df.columns:
        return {'icn': set(), 'domestic': set()}

    dep = df['Depstn'].astype(str)
    arr = df['Arrstn'].astype(str)

    icn_mask = (dep == 'ICN') | (arr == 'ICN')

    dep_kr = dep.isin(KOREAN_AIRPORTS)
    arr_kr = arr.isin(KOREAN_AIRPORTS)
    icn_only = (dep == 'ICN') & (arr == 'ICN')
    domestic_mask = dep_kr & arr_kr & ~icn_only

    # 예외 2: ICN 미경유 + 국내 비-ICN 공항 기점 국제선(지방공항 기반 기재)
    icn_acnos = set(df.loc[icn_mask, 'Acno'].unique())
    no_icn_acno = ~df['Acno'].isin(icn_acnos)
    dep_kr_nonicn = dep_kr & (dep != 'ICN')
    arr_kr_nonicn = arr_kr & (arr != 'ICN')
    kr_based_intl_mask = ((dep_kr_nonicn & ~arr_kr) | (arr_kr_nonicn & ~dep_kr)) & no_icn_acno
    domestic_mask = domestic_mask | kr_based_intl_mask

    if 'Airline_Code' in df.columns:
        airline = df['Airline_Code'].astype(str)
        feeder_route = (
            ((dep == 'ICN') & arr.isin(KAL_FEEDER_AIRPORTS)) |
            ((arr == 'ICN') & dep.isin(KAL_FEEDER_AIRPORTS))
        )
        feeder_mask = airline.eq('KAL') & feeder_route
        if 'TOF' in df.columns:
            feeder_mask &= df['TOF'].astype(str).eq('PAX')

        if feeder_mask.any():
            # 국제선 여부 = classify_route와 동일 조건 (양쪽 모두 한국공항이 아니면 국제선)
            is_intl = ~(dep_kr & arr_kr)

            # 원래는 그날의 전체 Acno(수백 개)를 순회하며 매번 .loc[idx] 팬시 인덱싱을
            # 했으나, 실제로 필요한 건 지선편이 있는 소수의 Acno뿐이다. value_counts로
            # "그 Acno의 나머지(비지선) 편 수"와 "그 중 국제선 수"를 한 번에 계산해두고
            # 지선편 보유 Acno만 순회(대개 수 개 수준)해 두 값이 같은지(=나머지 전부
            # 국제선)만 확인한다.
            acno_series = df['Acno']
            non_feeder_mask = ~feeder_mask
            non_feeder_total = acno_series[non_feeder_mask].value_counts()
            non_feeder_intl = acno_series[non_feeder_mask & is_intl].value_counts()

            exempt_acnos = set()
            for acno in acno_series[feeder_mask].unique():
                nft = non_feeder_total.get(acno, 0)
                if nft == 0:
                    continue
                if non_feeder_intl.get(acno, 0) == nft:
                    exempt_acnos.add(acno)

            if exempt_acnos:
                domestic_mask = domestic_mask & ~(feeder_mask & df['Acno'].isin(exempt_acnos))

    return {
        'icn': set(df.loc[icn_mask, 'Acno'].unique()),
        'domestic': set(df.loc[domestic_mask, 'Acno'].unique()),
    }


def add_aircraft_type_columns(df: pd.DataFrame) -> pd.DataFrame:
    """RAW 시트용: 일자별 Acno 기준 인천기재/국내기재 여부('O') 컬럼 추가

    유효편(Status!=CNL, Bt_idx==Y) 기준으로 해당 일자(Sch_date_KST)·Acno가
    인천기재/국내기재로 분류되면 원본 df의 모든 행(무효편 포함)에 'O' 표시.
    """
    result = df.copy()
    result['인천기재'] = ''
    result['국내기재'] = ''

    if df.empty or 'Sch_date_KST' not in df.columns or 'Acno' not in df.columns:
        return result

    valid = df[(df['Status'] != 'CNL') & (df['Bt_idx'] == 'Y')].dropna(subset=['Acno'])
    valid = valid[valid['Acno'].astype(str).str.strip() != '']  # 비운항 시나리오로 Acno가 빈 편 제외(유령 기재 방지)
    if valid.empty:
        return result

    valid_dates = pd.to_datetime(valid['Sch_date_KST']).dt.date
    row_dates = pd.to_datetime(df['Sch_date_KST']).dt.date

    icn_pairs, domestic_pairs = set(), set()
    for date_val, day_group in valid.groupby(valid_dates):
        acno_sets = _aircraft_type_acno_sets(day_group)
        icn_pairs.update((date_val, acno) for acno in acno_sets['icn'])
        domestic_pairs.update((date_val, acno) for acno in acno_sets['domestic'])

    row_pairs = list(zip(row_dates, df['Acno']))
    result['인천기재'] = ['O' if p in icn_pairs else '' for p in row_pairs]
    result['국내기재'] = ['O' if p in domestic_pairs else '' for p in row_pairs]

    return result


def compute_ontime_records(df: pd.DataFrame) -> dict:
    """정시율 분석용: 편 단위 플랫 레코드 리스트 반환.

    날짜/기재/TOF/NAT/지연기준 5종 필터는 프론트에서 이 레코드 리스트를 그대로
    필터링·집계하는 방식으로 처리한다(조합이 많아 백엔드에서 미리 계산하지 않음).

    "운항편수" 카운트 대상(= 바차트에 실제로 그려지는 편, barchart_display_rules.md 참고):
    - Status != 'CNL' AND Bt_idx == 'Y' (유효편)
    - RO_KST, RI_KST 모두 존재 (하나라도 없으면 바차트에 바가 그려지지 않으므로 제외)
    - D_OPER == 'Y' (사용자 지정: 엑셀 업로드 시 D_OPER가 'Y'인 행만 카운트)

    지연시간(delay_min) = RO_KST - STD_KST (분). UTC 컬럼(RO_UTC/STD_UTC)이 아닌 KST
    컬럼을 쓰는 이유: 재배정 시나리오의 캐스케이드 재계산(compute_scenario_delay_adjustments)이
    RO_KST/RI_KST만 갱신하고 RO_UTC는 건드리지 않으므로, UTC 기준으로 계산하면 재배정 후에도
    지연시간이 갱신되지 않는다(값 자체는 RO_KST=RO_UTC+9h, STD_KST=STD_UTC+9h로 고정
    오프셋이라 미조정 상태에서는 두 계산식의 결과가 동일하다). 이 함수를 시나리오
    재계산 반영된 df(app.py::_rebuild_ontime_cache 참고)에 넘겨야 재배정이 지연편수
    집계에 실제로 반영된다. 기재(icn/domestic) 판정은 위 카운트 조건과 무관하게 그날의
    전체 유효편 기준으로 계산한다(_aircraft_type_acno_sets는 그날 Acno의 전체 운항
    패턴을 봐야 정확하므로 D_OPER로 미리 좁히지 않음).
    """
    if df.empty:
        return {'records': []}

    valid = df[(df['Status'] != 'CNL') & (df['Bt_idx'] == 'Y')].copy()
    if valid.empty or 'Sch_date_KST' not in valid.columns or 'Acno' not in valid.columns:
        return {'records': []}
    valid = valid[valid['Acno'].astype(str).str.strip() != '']  # 비운항 시나리오로 Acno가 빈 편 제외(유령 기재 방지)
    if valid.empty:
        return {'records': []}

    valid_dates = pd.to_datetime(valid['Sch_date_KST']).dt.date

    icn_pairs, domestic_pairs = set(), set()
    for date_val, day_group in valid.groupby(valid_dates):
        acno_sets = _aircraft_type_acno_sets(day_group)
        icn_pairs.update((date_val, acno) for acno in acno_sets['icn'])
        domestic_pairs.update((date_val, acno) for acno in acno_sets['domestic'])

    d_oper_ok = (
        valid['D_OPER'].astype(str).str.strip() == 'Y'
        if 'D_OPER' in valid.columns else pd.Series(False, index=valid.index)
    )
    ro_ok = valid['RO_KST'].notna() if 'RO_KST' in valid.columns else pd.Series(False, index=valid.index)
    ri_ok = valid['RI_KST'].notna() if 'RI_KST' in valid.columns else pd.Series(False, index=valid.index)
    countable = valid[d_oper_ok & ro_ok & ri_ok].copy()

    if countable.empty:
        return {'records': []}

    countable_dates = valid_dates.loc[countable.index]
    delay_min = (
        pd.to_datetime(countable['RO_KST']) - pd.to_datetime(countable['STD_KST'])
    ).dt.total_seconds() / 60

    # 행 단위 .loc[idx] 스칼라 접근(수만 회 반복 시 느림) 대신 컬럼을 리스트로 한 번에
    # 뽑아 zip으로 순회 — 값과 순서는 기존과 동일, pandas 인덱싱 오버헤드만 제거.
    tof_col = countable['TOF'] if 'TOF' in countable.columns else pd.Series('', index=countable.index)
    nat_col = countable['NAT'] if 'NAT' in countable.columns else pd.Series('', index=countable.index)

    records = [
        {
            'date': str(date_val),
            'tof': str(tof_val) if pd.notna(tof_val) else '',
            'nat': str(nat_val) if pd.notna(nat_val) else '',
            'icn': (date_val, acno) in icn_pairs,
            'domestic': (date_val, acno) in domestic_pairs,
            'delay_min': round(float(dm), 1) if pd.notna(dm) else None,
        }
        for date_val, acno, tof_val, nat_val, dm in zip(
            countable_dates.tolist(),
            countable['Acno'].tolist(),
            tof_col.tolist(),
            nat_col.tolist(),
            delay_min.tolist(),
        )
    ]

    return {'records': records}


def apply_flight_cancellation(df: pd.DataFrame, fltnos: list) -> dict:
    """비운항 시나리오: 선택된 Fltno들의 모든 유효편(Status!=CNL, DEP/ARR 짝 포함)을
    Acno=''/D_OPER=''로 설정해 CANCEL 행으로 빠지고 정시율 집계에서 제외되게 한다.

    df는 in-place로 수정한다(app.py의 _current_df를 직접 넘겨받는 것을 전제).
    특정 날짜에 해당 편명이 아예 없으면(이미 결항/비운항이었던 날) 그 날짜는
    mask 연산에서 자연히 걸리지 않으므로 별도 스킵 처리가 필요 없다.
    """
    fltno_set = {str(f).strip() for f in fltnos if f and str(f).strip()}
    if not fltno_set:
        return {'affected_rows': 0, 'affected_fltnos': [], 'not_found_fltnos': []}

    mask = df['Fltno'].astype(str).isin(fltno_set) & (df['Status'] != 'CNL')
    affected_rows = int(mask.sum())
    touched_fltnos = set(df.loc[mask, 'Fltno'].astype(str).unique())

    df.loc[mask, 'Acno'] = ''
    df.loc[mask, 'D_OPER'] = ''

    return {
        'affected_rows': affected_rows,
        'affected_fltnos': sorted(touched_fltnos),
        'not_found_fltnos': sorted(fltno_set - touched_fltnos),
    }


def apply_chain_reassignment(df: pd.DataFrame, patterns: list) -> list:
    """스케줄 조정 시나리오: [(front_fltno, back_fltno), ...] 패턴을 입력 순서대로
    df에 로드된 전체 기간의 모든 날짜에 순차 적용한다(뒤 패턴은 앞 패턴이 반영된
    df 상태를 그대로 봄).

    각 날짜별로 앞편의 기번(front_acno)은 고정하고, 뒤편이 속한 기번(back_acno)의
    그날 체인에서 뒤편(포함) 이후 모든 편을 front_acno로 재배정한다. 앞편/뒤편 중
    하나라도 그날 없으면(비운항 처리되어 Acno가 빈 경우 포함) 스킵한다.

    df는 in-place로 수정한다. 반환값은 패턴별 적용/변경없음/스킵 날짜 리포트 리스트.
    """
    reports = []
    if df.empty or 'Sch_date_KST' not in df.columns:
        return reports

    all_dates = sorted(pd.to_datetime(df['Sch_date_KST']).dt.date.dropna().unique())

    for pattern in patterns:
        front_fltno, back_fltno = pattern
        front_fltno = str(front_fltno).strip()
        back_fltno = str(back_fltno).strip()
        report = {
            'pattern': f'{front_fltno}-{back_fltno}',
            'front_fltno': front_fltno,
            'back_fltno': back_fltno,
            'applied_dates': [],
            'no_change_dates': [],
            'skipped_dates': [],
        }

        if not front_fltno or not back_fltno or front_fltno == back_fltno:
            report['error'] = '앞편/뒤편 편명이 비어있거나 동일합니다.'
            reports.append(report)
            continue

        row_dates = pd.to_datetime(df['Sch_date_KST']).dt.date

        for date_val in all_dates:
            day_mask = row_dates == date_val
            # "존재" 판정: 유효편(Status!=CNL, Bt_idx==Y) & 실제 배정된 기번(Acno!='')
            valid_mask = (
                day_mask & (df['Status'] != 'CNL') & (df['Bt_idx'] == 'Y') &
                (df['Acno'].astype(str).str.strip() != '')
            )

            front_rows = df[valid_mask & (df['Fltno'].astype(str) == front_fltno)]
            back_rows = df[valid_mask & (df['Fltno'].astype(str) == back_fltno)]

            if front_rows.empty or back_rows.empty:
                report['skipped_dates'].append(str(date_val))
                continue

            front_acno = str(front_rows.iloc[0]['Acno'])
            back_acno = str(back_rows.iloc[0]['Acno'])

            if front_acno == back_acno:
                report['no_change_dates'].append(str(date_val))
                continue

            # 뒤편이 속한 기번(back_acno)의 그날 체인을 정렬해 뒤편(포함) 이후 편 산출
            chain = df[valid_mask & (df['Acno'].astype(str) == back_acno)].copy()
            chain['_sk'] = _sort_key_series(chain)
            back_sk_rows = chain.loc[chain['Fltno'].astype(str) == back_fltno, '_sk']
            back_sk = back_sk_rows.iloc[0]
            move_fltnos = set(chain.loc[chain['_sk'] >= back_sk, 'Fltno'].astype(str))

            # 실제 갱신 대상: 그날 + 기존 back_acno + move_fltnos (Bt_idx Y/N 모두 = DEP/ARR 짝 포함)
            update_mask = (
                day_mask & (df['Acno'].astype(str) == back_acno) &
                df['Fltno'].astype(str).isin(move_fltnos)
            )

            target_rows = df[df['Acno'].astype(str) == front_acno]
            actype_mode = target_rows['Actype'].mode()
            new_actype = str(actype_mode.iloc[0]) if not actype_mode.empty else None

            df.loc[update_mask, 'Acno'] = front_acno
            if new_actype is not None:
                df.loc[update_mask, 'Actype'] = new_actype
                df.loc[update_mask, 'Actype_Grade'] = get_actype_grade(new_actype)

            report['applied_dates'].append(str(date_val))

        reports.append(report)

    return reports
