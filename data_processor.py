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

    # Domestic_Intl
    def classify_route(row):
        dep = row.get('Depstn', '')
        arr = row.get('Arrstn', '')
        if dep in KOREAN_AIRPORTS and arr in KOREAN_AIRPORTS:
            return '국내선'
        return '국제선'

    df['Domestic_Intl'] = df.apply(classify_route, axis=1)

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

    result = []
    missing_ro_ri = []

    for acno, group in filtered.groupby('Acno'):
        # 정렬은 RO_KST(실적) 기준. RO_KST가 결측인 편은 STD_KST로 보완해 그룹 내 순서만 안정화
        # (그려지는 시각/BT/GT 값 자체는 여전히 RO/RI를 따름 — 순서 결정 전용 보조 키)
        group = group.copy()
        group['_sort_key'] = group['RO_KST'].fillna(group['STD_KST'])
        group = group.sort_values('_sort_key').reset_index().rename(columns={'index': 'row_id'})
        flights = []
        connection_error_acno = False

        lanes, lane_count = _assign_overlap_lanes(
            list(zip(group['STD_KST'], group['RI_KST']))
        )

        for i, row in group.iterrows():
            # 배경색
            dep = str(row.get('Depstn', '')).strip()
            arr = str(row.get('Arrstn', '')).strip()
            domestic_intl_val = str(row.get('Domestic_Intl', '')).strip()
            if domestic_intl_val == '국내선':
                color = 'navy' if (dep == 'CJU' or arr == 'CJU') else 'cobalt'
            else:
                color = 'gray'

            # 연결 오류 검증
            connection_error = False
            if i > group.index[0]:
                prev_idx = group.index[group.index.get_loc(i) - 1]
                prev_arr = str(group.loc[prev_idx, 'Arrstn'])
                if prev_arr != dep:
                    connection_error = True
                    connection_error_acno = True

            ro_kst = row['RO_KST']
            ri_kst = row['RI_KST']
            fltno = str(row.get('Fltno', ''))

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
            if i > group.index[0]:
                prev_idx = group.index[group.index.get_loc(i) - 1]
                prev_ri = group.loc[prev_idx, 'RI_KST']
                if pd.notna(prev_ri) and pd.notna(ro_kst):
                    gt_minutes = int((ro_kst - prev_ri).total_seconds() / 60)
                    ground_time_before = gt_minutes

            # 실적 블록타임: RI_KST - RO_KST (요약 영역의 계획 Blocktime과는 별개)
            actual_blocktime = None
            if pd.notna(ro_kst) and pd.notna(ri_kst):
                actual_blocktime = int((ri_kst - ro_kst).total_seconds() / 60)

            # #7 domestic_intl 전달
            domestic_intl = str(row.get('Domestic_Intl', ''))

            def _dla_value(val):
                return int(val) if pd.notna(val) else None

            flights.append({
                'row_id': int(row['row_id']),
                'fltno': fltno,
                'depstn': dep,
                'arrstn': arr,
                'ro_kst': ro_kst.isoformat() if pd.notna(ro_kst) else None,
                'ri_kst': ri_kst.isoformat() if pd.notna(ri_kst) else None,
                'std_kst': row['STD_KST'].isoformat() if pd.notna(row['STD_KST']) else None,
                'sta_kst': row['STA_KST'].isoformat() if pd.notna(row['STA_KST']) else None,
                'blocktime': actual_blocktime,
                'actype': str(row.get('Actype', '')),
                'actype_grade': str(row.get('Actype_Grade', '')),
                'status': str(row.get('Status', '')),
                'tof': str(row.get('TOF', '')),
                'nat': (str(row.get('NAT')).strip() if pd.notna(row.get('NAT')) and str(row.get('NAT')).strip() else None),
                'mttt': (int(row.get('MTTT')) if pd.notna(row.get('MTTT')) else None),
                'domestic_intl': domestic_intl,
                'color': color,
                'connection_error': connection_error,
                'ground_time_before': ground_time_before,
                'cnx_dla': _dla_value(row.get('CNX_DLA')),
                'dep_dla': _dla_value(row.get('DEP_DLA')),
                'atc_dla': _dla_value(row.get('ATC_DLA')),
                'lane': int(lanes[i]),
            })

        result.append({
            'acno': str(acno),
            'connection_error': connection_error_acno,
            'lane_count': int(lane_count),
            'flights': flights,
        })

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

            exempt_acnos = set()
            for acno, idx in df.groupby('Acno').groups.items():
                acno_feeder_idx = idx[feeder_mask.loc[idx]]
                if len(acno_feeder_idx) == 0:
                    continue
                other_idx = idx.difference(acno_feeder_idx)
                if len(other_idx) == 0:
                    continue
                if is_intl.loc[other_idx].all():
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

    지연시간(delay_min) = RO_UTC - STD_UTC (분). 기재(icn/domestic) 판정은 위 카운트
    조건과 무관하게 그날의 전체 유효편 기준으로 계산한다(_aircraft_type_acno_sets는
    그날 Acno의 전체 운항 패턴을 봐야 정확하므로 D_OPER로 미리 좁히지 않음).
    """
    if df.empty:
        return {'records': []}

    valid = df[(df['Status'] != 'CNL') & (df['Bt_idx'] == 'Y')].copy()
    if valid.empty or 'Sch_date_KST' not in valid.columns or 'Acno' not in valid.columns:
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
        pd.to_datetime(countable['RO_UTC']) - pd.to_datetime(countable['STD_UTC'])
    ).dt.total_seconds() / 60

    records = []
    for idx in countable.index:
        row = countable.loc[idx]
        date_val = countable_dates.loc[idx]
        acno = row['Acno']
        dm = delay_min.loc[idx]
        records.append({
            'date': str(date_val),
            'tof': str(row.get('TOF', '')) if pd.notna(row.get('TOF')) else '',
            'nat': str(row.get('NAT', '')) if pd.notna(row.get('NAT')) else '',
            'icn': (date_val, acno) in icn_pairs,
            'domestic': (date_val, acno) in domestic_pairs,
            'delay_min': round(float(dm), 1) if pd.notna(dm) else None,
        })

    return {'records': records}
