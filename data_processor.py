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

CARGO_NAT = {'CGE', 'CGO', 'CGC'}

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


REQUIRED_COLUMNS = {'Fltno', 'Depstn', 'Arrstn', 'Acno', 'Actype', 'Status', 'Bt_idx'}


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

    # Sch_date_KST 기준으로 STD_KST/STA_KST 날짜 보정
    # STD_KST 날짜가 Sch_date_KST와 다르면 시간은 유지하고 날짜를 Sch_date_KST로 맞춤
    if 'Sch_date_KST' in df.columns and pd.notna(df['STD_KST']).any():
        sch_date = pd.to_datetime(df['Sch_date_KST'])
        std_kst = df['STD_KST']
        sta_kst = df['STA_KST']

        # STD_KST 날짜와 Sch_date_KST 날짜 차이 (일 단위)
        std_date_diff = (std_kst.dt.normalize() - sch_date.dt.normalize()).dt.days
        needs_fix = std_date_diff.notna() & (std_date_diff != 0)

        if needs_fix.any():
            shift = pd.to_timedelta(std_date_diff[needs_fix], unit='D')
            df.loc[needs_fix, 'STD_KST'] = std_kst[needs_fix] - shift
            df.loc[needs_fix, 'STA_KST'] = sta_kst[needs_fix] - shift

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


def filter_for_barchart(df: pd.DataFrame, airline: str, nat_list: list) -> dict:
    """바차트 표출용 데이터 필터링 및 JSON 변환"""
    # 기본 필터: Status != CNL, Bt_idx == Y
    filtered = df[
        (df['Status'] != 'CNL') &
        (df['Bt_idx'] == 'Y')
    ].copy()

    # 여객기만: NAT not in CARGO_NAT
    if 'NAT' in filtered.columns:
        filtered = filtered[~filtered['NAT'].isin(CARGO_NAT)]

    # 항공사 필터
    if airline:
        filtered = filtered[filtered['Airline_Code'] == airline]

    # NAT 필터
    if nat_list and 'NAT' in filtered.columns:
        filtered = filtered[filtered['NAT'].isin(nat_list)]

    result = []

    for acno, group in filtered.groupby('Acno'):
        group = group.sort_values('STD_KST').reset_index(drop=True)
        flights = []
        connection_error_acno = False

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

            # Ground Time
            ground_time_before = None
            if i > group.index[0]:
                prev_idx = group.index[group.index.get_loc(i) - 1]
                prev_sta = group.loc[prev_idx, 'STA_KST']
                curr_std = row['STD_KST']
                if pd.notna(prev_sta) and pd.notna(curr_std):
                    gt_minutes = int((curr_std - prev_sta).total_seconds() / 60)
                    ground_time_before = gt_minutes

            std_kst = row['STD_KST']
            sta_kst = row['STA_KST']

            # #7 domestic_intl 전달
            domestic_intl = str(row.get('Domestic_Intl', ''))

            flights.append({
                'fltno': str(row.get('Fltno', '')),
                'depstn': dep,
                'arrstn': arr,
                'std_kst': std_kst.isoformat() if pd.notna(std_kst) else None,
                'sta_kst': sta_kst.isoformat() if pd.notna(sta_kst) else None,
                'blocktime': int(row.get('Blocktime', 0)) if pd.notna(row.get('Blocktime')) else 0,
                'actype': str(row.get('Actype', '')),
                'actype_grade': str(row.get('Actype_Grade', '')),
                'status': str(row.get('Status', '')),
                'nat': str(row.get('NAT', '')),
                'domestic_intl': domestic_intl,
                'color': color,
                'connection_error': connection_error,
                'ground_time_before': ground_time_before,
            })

        result.append({
            'acno': str(acno),
            'connection_error': connection_error_acno,
            'flights': flights,
        })

    # Acno 알파벳 순 정렬
    result.sort(key=lambda x: x['acno'])

    return {'aircraft': result}


def _compute_op_rows(df_subset: pd.DataFrame) -> list:
    """국적사 항공사별 가동률 계산 (일별 운영기재수 합산 방식, 등급별 세부 포함)"""
    rows = []
    for al_code in sorted(DOMESTIC_AIRLINES):
        al_df = df_subset[df_subset['Airline_Code'] == al_code]
        if al_df.empty:
            continue
        pl_bt = int(al_df['Blocktime'].fillna(0).sum())

        if 'Sch_date_KST' in al_df.columns:
            daily_counts = al_df.groupby(
                pd.to_datetime(al_df['Sch_date_KST']).dt.date
            )['Acno'].nunique()
            total_daily_aircraft = int(daily_counts.sum())
            num_days = len(daily_counts)
            avg_aircraft = round(total_daily_aircraft / num_days, 1) if num_days > 0 else 0.0
        else:
            total_daily_aircraft = al_df['Acno'].nunique()
            avg_aircraft = float(total_daily_aircraft)

        hours_per = round(pl_bt / total_daily_aircraft / 60, 1) if total_daily_aircraft > 0 else 0.0

        by_grade = {}
        for grade in ['전체', 'A', 'B', 'C', 'D', 'E']:
            if grade == '전체':
                g_df = al_df
            elif 'Actype_Grade' in al_df.columns:
                g_df = al_df[al_df['Actype_Grade'] == grade]
            else:
                by_grade[grade] = None
                continue
            if g_df.empty:
                by_grade[grade] = None
                continue
            g_pl_bt = int(g_df['Blocktime'].fillna(0).sum())
            if 'Sch_date_KST' in g_df.columns:
                g_daily = g_df.groupby(pd.to_datetime(g_df['Sch_date_KST']).dt.date)['Acno'].nunique()
                g_total_ac = int(g_daily.sum())
                g_num_days = len(g_daily)
                g_avg_ac = round(g_total_ac / g_num_days, 1) if g_num_days > 0 else 0.0
            else:
                g_total_ac = g_df['Acno'].nunique()
                g_avg_ac = float(g_total_ac)
            ratio = round(g_total_ac / total_daily_aircraft * 100, 1) if total_daily_aircraft > 0 else 0.0
            g_hours = round(g_pl_bt / g_total_ac / 60, 1) if g_total_ac > 0 else 0.0
            by_grade[grade] = {
                'aircraft_count': g_avg_ac,
                'aircraft_ratio': ratio,
                'planned_bt': g_pl_bt,
                'hours_per_aircraft': g_hours,
            }

        rows.append({
            'airline': al_code,
            'operating_aircraft': avg_aircraft,
            'planned_bt': pl_bt,
            'hours_per_aircraft': hours_per,
            'by_grade': by_grade,
        })
    return rows


def _aircraft_type_acno_sets(df: pd.DataFrame) -> dict:
    """Acno별 인천기재/국내기재 판정 (filters.js의 filterAircraftByType과 동일 규칙)

    해당 Acno가 가진 항공편 중 하나라도 조건에 맞으면 그 기재 유형에 포함시킨다.
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

    return {
        'icn': set(df.loc[icn_mask, 'Acno'].unique()),
        'domestic': set(df.loc[domestic_mask, 'Acno'].unique()),
    }


def _op_rows_by_aircraft_type(df_subset: pd.DataFrame) -> dict:
    """전체/인천기재/국내기재 3종 가동률 rows 반환"""
    acno_sets = _aircraft_type_acno_sets(df_subset)
    return {
        'all': _compute_op_rows(df_subset),
        'icn': _compute_op_rows(df_subset[df_subset['Acno'].isin(acno_sets['icn'])]),
        'domestic': _compute_op_rows(df_subset[df_subset['Acno'].isin(acno_sets['domestic'])]),
    }


def compute_summary(df: pd.DataFrame, nat_list: list, airline: str = '') -> dict:
    """좌측 요약 패널용 집계"""
    # 국적사만
    domestic = df[df['Carrier_Type'] == '국적사'].copy()

    # NAT 필터
    if nat_list and 'NAT' in domestic.columns:
        domestic = domestic[domestic['NAT'].isin(nat_list)]

    # Bt_idx == Y, Status != CNL
    valid = domestic[
        (domestic['Bt_idx'] == 'Y') &
        (domestic['Status'] != 'CNL')
    ]

    # #9 가동률: 국적사 전체 (항공사 필터 무관)
    # 화물기 제외
    if 'NAT' in valid.columns:
        all_pax = valid[~valid['NAT'].isin(CARGO_NAT)]
    else:
        all_pax = valid

    # 날짜 목록 산출
    available_dates = []
    if 'Sch_date_KST' in all_pax.columns:
        available_dates = sorted(
            pd.to_datetime(all_pax['Sch_date_KST']).dt.date.dropna().unique().tolist()
        )
    available_dates_str = [str(d) for d in available_dates]

    # #12 전체 기간 가동률 (기재 필터 3종: 전체/인천기재/국내기재)
    op_rows = _op_rows_by_aircraft_type(all_pax)

    # 일별 가동률 (날짜 필터용, 기재 필터 3종 포함)
    daily_op = {}
    for date_val in available_dates:
        day_pax = all_pax[pd.to_datetime(all_pax['Sch_date_KST']).dt.date == date_val]
        daily_op[str(date_val)] = _op_rows_by_aircraft_type(day_pax)

    operation_summary = {
        'rows': op_rows,
        'available_dates': available_dates_str,
        'daily': daily_op,
    }

    # (2) Ground Time 히스토그램 (기존 유지)
    gt_data = {}
    for airline_code in sorted(DOMESTIC_AIRLINES):
        al_df = valid[valid['Airline_Code'] == airline_code].copy()
        if al_df.empty:
            continue

        gt_values = []
        for acno, group in al_df.groupby('Acno'):
            group = group.sort_values('STD_KST').reset_index(drop=True)
            for i in range(1, len(group)):
                prev_sta = group.loc[i - 1, 'STA_KST']
                curr_std = group.loc[i, 'STD_KST']
                if pd.notna(prev_sta) and pd.notna(curr_std):
                    gt_min = int((curr_std - prev_sta).total_seconds() / 60)
                    if gt_min >= 0:
                        gt_values.append(gt_min)

        if gt_values:
            gt_data[airline_code] = gt_values

    # (3) 노선별 BT 통계
    route_stats = {}
    for _, row in valid.iterrows():
        dep = str(row.get('Depstn', ''))
        arr = str(row.get('Arrstn', ''))
        airline_code = str(row.get('Airline_Code', ''))
        bt = row.get('Blocktime', 0)
        if pd.isna(bt):
            bt = 0
        bt = int(bt)
        route_key = f"{dep}-{arr}"
        if route_key not in route_stats:
            route_stats[route_key] = {}
        if airline_code not in route_stats[route_key]:
            route_stats[route_key][airline_code] = []
        route_stats[route_key][airline_code].append(bt)

    route_summary = {}
    for route, airlines in route_stats.items():
        route_summary[route] = {}
        for al, bt_list in airlines.items():
            route_summary[route][al] = {
                'avg': round(sum(bt_list) / len(bt_list), 1),
                'max': max(bt_list),
                'min': min(bt_list),
                'count': len(bt_list),
            }

    # #11 GT 테이블 데이터
    gt_table = _compute_gt_table(valid)

    # 등급 미분류 기종 정보 (국적사 여객기 중 Actype_Grade == '')
    ungraded_actypes = []
    if 'Actype_Grade' in valid.columns and 'NAT' in valid.columns:
        pax_valid = valid[~valid['NAT'].isin(CARGO_NAT)]
        ungraded = pax_valid[pax_valid['Actype_Grade'] == '']
        if not ungraded.empty:
            counts = ungraded.groupby('Actype').size().reset_index(name='count')
            ungraded_actypes = counts.sort_values('count', ascending=False).to_dict('records')

    return {
        'operation_summary': operation_summary,
        'ground_time_histogram': gt_data,
        'route_stats': route_summary,
        'gt_table': gt_table,
        'ungraded_actypes': ungraded_actypes,
    }


def _compute_gt_table(valid: pd.DataFrame) -> dict:
    """#11 GT 분석 테이블: 항공사별 x 등급별 GT 구간 빈도"""
    # 국내선 구간: <30, 30, 35, 40, 45, 50, >50
    domestic_bins = [('<30', lambda x: x < 30), ('30', lambda x: x == 30),
                     ('35', lambda x: x == 35), ('40', lambda x: x == 40),
                     ('45', lambda x: x == 45), ('50', lambda x: x == 50),
                     ('>50', lambda x: x > 50)]
    # 국제선 구간: <50, 50, 55, 60, 65, 70, >70
    intl_bins = [('<50', lambda x: x < 50), ('50', lambda x: x == 50),
                 ('55', lambda x: x == 55), ('60', lambda x: x == 60),
                 ('65', lambda x: x == 65), ('70', lambda x: x == 70),
                 ('>70', lambda x: x > 70)]

    results = {'domestic': {}, 'international': {}}

    for airline_code in sorted(DOMESTIC_AIRLINES):
        al_df = valid[valid['Airline_Code'] == airline_code].copy()
        if al_df.empty:
            continue

        # GT 값 수집 (노선유형, 등급 포함)
        # 연결편 없는 첫 번째 편은 가장 큰 구간에 포함
        gt_records = []
        total_flights_by_route = {'국내선': 0, '국제선': 0}

        for acno, group in al_df.groupby('Acno'):
            group = group.sort_values('STD_KST').reset_index(drop=True)
            for i in range(len(group)):
                route_type = group.loc[i, 'Domestic_Intl'] if 'Domestic_Intl' in group.columns else '국제선'
                grade = str(group.loc[i, 'Actype_Grade']) if 'Actype_Grade' in group.columns else ''
                total_flights_by_route[route_type] = total_flights_by_route.get(route_type, 0) + 1

                if i == 0:
                    # 첫 번째 편: 연결편 없음 → 가장 큰 구간에 포함
                    gt_records.append({
                        'gt': None,  # None = 연결편 없음
                        'route_type': route_type,
                        'grade': grade,
                    })
                else:
                    prev_sta = group.loc[i - 1, 'STA_KST']
                    curr_std = group.loc[i, 'STD_KST']
                    if pd.notna(prev_sta) and pd.notna(curr_std):
                        gt_min = int((curr_std - prev_sta).total_seconds() / 60)
                        # 음수 GT도 포함 (최소 구간에 자동 분류됨)
                        gt_records.append({
                            'gt': gt_min,
                            'route_type': route_type,
                            'grade': grade,
                        })
                    else:
                        # 시간 데이터 누락 → GT 파악 불가, 최대 구간에 포함
                        gt_records.append({
                            'gt': None,
                            'route_type': route_type,
                            'grade': grade,
                        })

        if not gt_records:
            continue

        gt_df = pd.DataFrame(gt_records)

        for route_type, bins, key in [('국내선', domestic_bins, 'domestic'), ('국제선', intl_bins, 'international')]:
            rt_df = gt_df[gt_df['route_type'] == route_type]
            if rt_df.empty:
                continue

            total_flight_count = total_flights_by_route.get(route_type, 0)
            last_bin_name = bins[-1][0]  # 가장 큰 구간 이름

            grades = sorted(rt_df['grade'].unique().tolist())
            if '' in grades:
                grades.remove('')
                grades.append('')

            grade_data = {}
            grade_flights = {'전체': total_flight_count}
            for grade in ['전체'] + grades:
                if grade == '전체':
                    gdf = rt_df
                else:
                    gdf = rt_df[rt_df['grade'] == grade]
                if gdf.empty:
                    continue

                total = len(gdf)
                if grade != '전체':
                    grade_flights[grade] = total

                # 연결편 없는 편수 (gt == None)
                no_conn_count = int(gdf['gt'].isna().sum())
                has_gt = gdf[gdf['gt'].notna()]

                bin_counts = {}
                for bin_name, bin_fn in bins:
                    count = int(has_gt['gt'].apply(bin_fn).sum())
                    # 가장 큰 구간에 연결편 없는 편 추가
                    if bin_name == last_bin_name:
                        count += no_conn_count
                    pct = round(count / total * 100, 1) if total > 0 else 0.0
                    bin_counts[bin_name] = {'count': count, 'pct': pct}
                grade_data[grade] = bin_counts

            if grade_data:
                if airline_code not in results[key]:
                    results[key][airline_code] = {}
                results[key][airline_code] = {
                    'grades': grade_data,
                    'grade_flights': grade_flights,
                }

    return results
