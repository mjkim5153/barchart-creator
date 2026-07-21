# -*- coding: utf-8 -*-
"""
W26 GT(Ground Time) 조정 스케줄을 W25 실적 데이터에 적용해보는 시뮬레이션 스크립트.

W26 시즌에는 스케줄상 GT를 조정해 40분 이상 확보되는 편을 늘렸다. 이 조정이 실제
정시율에 얼마나 도움이 되는지 검증하기 위해, 이미 지나간 W25 실적 데이터에서 편명별
STD/STA를 W26 계획값으로 치환하고, 그로 인한 지연(RO/RI/CNX_DLA/DEP_DLA) 캐스케이드를
재계산한 뒤 정시율을 원본과 비교한다.

사용 예:
    python build_w26_gt_schedule_scenario.py
    python build_w26_gt_schedule_scenario.py --delay-threshold 30 --no-save

캐스케이드 재계산은 data_processor.py::compute_scenario_delay_adjustments()와 동일한
물리 모델(연결지연 하한선, .claude/rules/secured_gt_dep_dla_rule.md의 확보GT 40분 임계
±3분 DEP_DLA 조정)을 쓰지만, 그 함수는 "Acno 연결이 바뀐 편"만 재계산 대상으로 삼아
STD/STA 자체가 바뀌는 이 시나리오에는 맞지 않는다(체인의 첫 편이 STD만 바뀌는 경우를
아예 다루지 않음). 그래서 이 스크립트 안에 별도로 구현한다(data_processor.py는 건드리지
않음 — 실제 서비스가 매일 쓰는 비운항/재배정/드래그 기능과 완전히 분리하기 위함).
"""
import argparse
import io
import json
import pickle
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', write_through=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', write_through=True)

import numpy as np
import pandas as pd

from data_processor import (
    process_dataframe,
    compute_ontime_records,
    SECURED_GT_THRESHOLD_MIN,
    SECURED_GT_DEP_DLA_STEP_MIN,
)

SCENARIO_DIR = Path('data/scenarios')
DEFAULT_SOURCE = r'c:\Users\admin\Downloads\upload_template (W25).xlsx'

# 사용자가 제공한 W26 편명별 STD/STA/요일(월화수목금토일=0~6, 1=운항) 표. "+1 " 접두어(다음날
# 도착)는 파싱 시 제거한다 — 날짜 이월은 STA<=STD 여부로 자동 판정하므로 마커가 따로 필요 없다.
W26_TABLE_TEXT = """
7C101 06:25 07:40 1 1 1 1 1 1 1
7C102 07:00 08:15 1 0 1 0 1 0 1
7C104 08:45 10:00 1 1 1 1 1 1 1
7C105 06:50 08:05 1 1 1 1 1 1 1
7C106 09:55 11:10 1 1 1 1 1 1 1
7C107 07:40 08:55 1 1 1 1 1 1 1
7C108 09:50 11:05 1 1 1 1 1 1 1
7C109 08:55 10:10 1 1 1 1 1 1 1
7C110 10:55 12:10 1 1 1 1 1 1 1
7C111 09:05 10:20 1 0 1 0 1 0 1
7C112 11:00 12:15 1 0 1 0 1 0 1
7C113 10:40 11:55 1 1 1 1 1 1 1
7C114 11:40 13:00 1 1 1 1 1 1 1
7C115 11:55 13:10 1 1 1 1 1 1 1
7C117 12:00 13:15 1 1 1 1 1 1 1
7C118 12:25 13:40 1 1 1 1 1 1 1
7C119 12:50 14:05 1 1 1 1 1 1 1
7C120 13:45 15:00 1 1 1 1 1 1 1
7C121 12:55 14:10 1 0 1 0 1 0 1
7C122 14:05 15:20 1 1 1 1 1 1 1
7C123 13:40 14:55 1 1 1 1 1 1 1
7C124 14:45 16:00 1 0 1 0 1 0 1
7C125 14:35 15:50 1 1 1 1 1 1 1
7C126 16:30 17:45 1 1 1 1 1 1 1
7C128 17:15 18:30 1 1 1 1 1 1 1
7C129 15:40 16:55 1 1 1 1 1 1 1
7C130 18:10 19:25 1 1 1 1 1 1 1
7C131 16:00 17:15 1 1 1 1 1 1 1
7C132 18:30 19:45 1 1 1 1 1 1 1
7C1325 08:00 09:40 1 1 1 1 1 1 1
7C1326 10:40 12:40 1 1 1 1 1 1 1
7C1327 13:50 15:30 1 1 1 1 1 1 1
7C1328 16:30 18:30 1 1 1 1 1 1 1
7C133 16:35 17:50 1 0 1 0 1 0 1
7C134 20:15 21:30 1 1 1 1 1 1 1
7C135 18:20 19:35 1 1 1 1 1 1 1
7C1355 10:45 12:10 0 1 0 1 0 1 0
7C1356 13:10 14:45 0 1 0 1 0 1 0
7C137 19:05 20:20 1 1 1 1 1 1 1
7C138 20:55 22:10 1 1 1 1 1 1 1
7C139 19:30 20:45 1 1 1 1 1 1 1
7C140 21:00 22:15 1 1 1 1 1 1 1
7C141 20:25 21:40 1 1 1 1 1 1 1
7C142 21:20 22:35 1 1 1 1 1 1 1
7C151 06:20 07:35 1 1 1 1 1 1 1
7C152 08:25 09:40 1 1 1 1 1 1 1
7C153 10:30 11:45 1 1 1 1 1 1 1
7C154 12:35 13:50 1 1 1 1 1 1 1
7C155 14:20 15:35 1 1 1 1 1 1 1
7C156 16:20 17:35 1 1 1 1 1 1 1
7C157 18:50 20:05 1 1 1 1 1 1 1
7C158 20:45 22:00 1 1 1 1 1 1 1
7C184 19:00 20:15 0 0 1 0 0 0 0
7C185 08:45 10:00 0 0 1 0 1 0 1
7C186 07:25 08:45 0 1 0 0 0 1 0
7C213 11:25 12:35 1 1 1 1 1 1 1
7C214 09:40 10:50 1 1 1 1 1 1 1
7C2151 21:05 00:45 1 1 1 1 1 1 1
7C2152 01:45 06:55 1 1 1 1 1 1 1
7C2252 01:05 07:20 1 1 1 1 1 1 1
7C227 19:15 20:25 1 1 1 1 1 1 1
7C228 17:30 18:40 1 1 1 1 1 1 1
7C301 10:00 11:00 1 1 1 1 1 1 1
7C302 08:20 09:15 1 1 1 1 1 1 1
7C305 18:15 19:10 1 1 1 1 1 1 1
7C306 16:35 17:35 1 1 1 1 1 1 1
7C4505 11:00 13:15 0 1 0 1 0 1 0
7C4506 14:15 18:30 0 1 0 1 0 1 0
7C501 08:10 09:15 1 1 1 1 1 1 1
7C502 08:45 09:45 0 1 0 1 0 1 0
7C503 09:00 10:15 1 1 1 1 1 1 1
7C504 10:50 11:50 1 1 1 1 1 1 1
7C505 12:25 13:25 1 1 1 1 1 1 1
7C506 13:15 14:15 1 1 1 1 1 1 1
7C507 14:55 15:55 1 1 1 1 1 1 1
7C508 14:05 15:05 1 1 1 1 1 1 1
7C509 15:40 16:40 1 1 1 1 1 1 1
7C510 15:35 16:35 1 1 1 1 1 1 1
7C511 16:35 17:50 0 1 0 1 0 1 0
7C512 19:00 20:00 1 1 1 1 1 1 1
7C513 17:20 18:20 1 1 1 1 1 1 1
7C514 19:50 20:55 1 1 1 1 1 1 1
7C6163 22:00 23:50 1 1 1 1 1 1 1
7C702 14:40 15:45 1 1 1 1 1 1 1
7C705 16:25 17:30 1 1 1 1 1 1 1
7C706 17:55 19:05 1 1 1 1 1 1 1
7C711 08:05 09:10 1 1 1 1 1 1 1
7C8135 11:40 13:30 1 0 1 0 1 0 1
7C8316 14:30 17:50 1 0 1 0 1 0 1
7C8351 22:00 23:05 1 1 1 1 1 1 1
7C8352 03:30 06:10 1 1 1 1 1 1 1
7C8363 21:05 22:05 1 1 1 1 1 1 1
7C904 07:10 08:15 1 1 1 1 1 1 1
7C907 20:05 21:15 1 1 1 1 1 1 1
"""


def parse_w26_table(text: str) -> dict:
    """W26_TABLE_TEXT를 {Fltno: {'std': (h,m), 'sta': (h,m), 'weekdays': [월..일]}}로 파싱."""
    schedule = {}
    for line in text.strip().splitlines():
        parts = line.split()
        if len(parts) != 10:
            raise ValueError(f'W26 표 파싱 실패(토큰 {len(parts)}개, 10개 예상): {line!r}')
        fltno, std_s, sta_s, *weekday_s = parts
        std_h, std_m = (int(x) for x in std_s.split(':'))
        sta_h, sta_m = (int(x) for x in sta_s.split(':'))
        schedule[fltno] = {
            'std': (std_h, std_m),
            'sta': (sta_h, sta_m),
            'weekdays': [int(x) for x in weekday_s],
        }
    return schedule


W26_SCHEDULE = parse_w26_table(W26_TABLE_TEXT)


def apply_w26_std_sta(df: pd.DataFrame, schedule: dict) -> pd.Series:
    """schedule에 매칭되는 행의 STD_KST/STA_KST/STD_UTC/STA_UTC/Blocktime을 in-place로
    치환하고, 실제로 바뀐 행을 True로 표시하는 불리언 Series를 반환한다.

    새 STD의 날짜는 Sch_date_KST 기준(자정)+표의 시각. 새 STA는 같은 날짜+표의 시각이되,
    STA 시각 <= STD 시각이면 다음날로 이월(자정을 넘는 심야편, 예: 7C2151 21:05->익일 00:45).
    """
    sch_dates = pd.to_datetime(df['Sch_date_KST']).dt.normalize()
    weekday = sch_dates.dt.dayofweek  # 0=월 ... 6=일
    changed = pd.Series(False, index=df.index)

    for fltno, info in schedule.items():
        row_mask = df['Fltno'] == fltno
        if not row_mask.any():
            continue
        weekday_ok = weekday.isin([w for w, flag in enumerate(info['weekdays']) if flag])
        mask = row_mask & weekday_ok
        if not mask.any():
            continue

        base = sch_dates.loc[mask]
        std_h, std_m = info['std']
        sta_h, sta_m = info['sta']
        new_std = base + pd.Timedelta(hours=std_h, minutes=std_m)
        new_sta = base + pd.Timedelta(hours=sta_h, minutes=sta_m)
        rollover = new_sta <= new_std
        new_sta = new_sta.where(~rollover, new_sta + pd.Timedelta(days=1))

        df.loc[mask, 'STD_KST'] = new_std
        df.loc[mask, 'STA_KST'] = new_sta
        df.loc[mask, 'STD_UTC'] = new_std - pd.Timedelta(hours=9)
        df.loc[mask, 'STA_UTC'] = new_sta - pd.Timedelta(hours=9)
        df.loc[mask, 'Blocktime'] = ((new_sta - new_std).dt.total_seconds() / 60).round().astype(int)
        changed |= mask

    return changed


def compute_schedule_shift_cascade(current_df: pd.DataFrame, original_df: pd.DataFrame) -> dict:
    """STD/STA가 바뀐 편(과 그로 인해 캐스케이드 영향을 받는 후속편)의 RO/RI/CNX_DLA/DEP_DLA를
    재계산한다. 아무 것도 바뀌지 않은 편은 원본 값을 그대로 유지한다(no-op).

    data_processor.compute_scenario_delay_adjustments()와 동일한 물리 모델(연결지연 하한선,
    확보GT 40분 임계 ±3분 DEP_DLA 조정)을 쓰되, 그 함수가 다루지 않는 "체인의 첫 편 자체의
    STD가 바뀌는 경우"까지 포함해 재계산 대상 조건을 다시 짠 버전이다.

    반환: {row_index: {'ro_kst','ri_kst','cnx_dla','dep_dla'}} (실제로 값이 바뀐 행만)
    """
    adjustments = {}
    if current_df.empty or 'Acno' not in current_df.columns:
        return adjustments

    valid = current_df[
        (current_df['Status'] != 'CNL') & (current_df['Bt_idx'] == 'Y') &
        (current_df['Acno'].astype(str).str.strip() != '') &
        current_df['Sch_date_KST'].notna() & current_df['Acno'].notna()
    ].copy()
    if valid.empty:
        return adjustments

    # 체인 순서는 원본 RO_KST(fillna STD_KST) 기준으로 고정한다 — STD를 바꿔도 실제
    # 운항 순서(체인 구성) 자체는 바뀌지 않는다는 전제(Acno 재배정이 없는 시나리오).
    orig_sort_key = original_df['RO_KST'].reindex(valid.index).fillna(original_df['STD_KST'].reindex(valid.index))
    valid['_sk'] = orig_sort_key
    sv = valid.sort_values(['Sch_date_KST', 'Acno', '_sk'])
    is_first = ~(
        (sv['Sch_date_KST'] == sv['Sch_date_KST'].shift(1)) &
        (sv['Acno'] == sv['Acno'].shift(1))
    )

    idx_list = sv.index.tolist()
    std_list = sv['STD_KST'].tolist()
    mttt_list = pd.to_numeric(sv['MTTT'], errors='coerce').tolist() if 'MTTT' in sv.columns else [np.nan] * len(sv)
    domestic_list = sv['Domestic_Intl'].tolist() if 'Domestic_Intl' in sv.columns else [''] * len(sv)
    first_list = is_first.tolist()

    orig_ro_col = original_df['RO_KST']
    orig_ri_col = original_df['RI_KST']
    orig_std_col = original_df['STD_KST']
    orig_cnx_col = original_df['CNX_DLA'] if 'CNX_DLA' in original_df.columns else None
    orig_dep_col = original_df['DEP_DLA'] if 'DEP_DLA' in original_df.columns else None

    prev_ri_effective = None  # 캐스케이드 반영된 "현재" 직전편 RI
    prev_orig_ri = None       # 그 체인의 원본(베이스라인) 직전편 RI

    for i, idx in enumerate(idx_list):
        std = std_list[i]
        orig_ro = orig_ro_col.at[idx]
        orig_ri = orig_ri_col.at[idx]
        orig_std = orig_std_col.at[idx]
        orig_cnx_raw = orig_cnx_col.at[idx] if orig_cnx_col is not None else np.nan
        orig_cnx = float(orig_cnx_raw) if pd.notna(orig_cnx_raw) else 0.0
        orig_dep_raw = orig_dep_col.at[idx] if orig_dep_col is not None else np.nan
        orig_dep_dla = float(orig_dep_raw) if pd.notna(orig_dep_raw) else np.nan

        own_std_changed = pd.notna(std) and pd.notna(orig_std) and std != orig_std

        if first_list[i]:
            pred_changed = False
        else:
            pred_changed = not (
                (pd.isna(prev_ri_effective) and pd.isna(prev_orig_ri)) or prev_ri_effective == prev_orig_ri
            )

        needs_recompute = own_std_changed or pred_changed
        if not needs_recompute or pd.isna(std) or pd.isna(orig_ro) or pd.isna(orig_ri) or pd.isna(orig_std):
            # 변경 없음(또는 계산에 필요한 값 결측) -> 원본 그대로, 다음 편에는 원본 RI를 전달
            prev_ri_effective = orig_ri if pd.notna(orig_ri) else None
            prev_orig_ri = orig_ri if pd.notna(orig_ri) else None
            continue

        non_cnx_extra = orig_ro - orig_std - pd.Timedelta(minutes=orig_cnx)

        if first_list[i] or prev_ri_effective is None:
            new_cnx = 0.0
            new_secured_gt = np.nan
        else:
            mttt = mttt_list[i]
            if pd.isna(mttt):
                prev_ri_effective = orig_ri if pd.notna(orig_ri) else None
                prev_orig_ri = orig_ri if pd.notna(orig_ri) else None
                continue
            available_slack = (std - prev_ri_effective).total_seconds() / 60 - float(mttt)
            new_cnx = max(0.0, -available_slack)
            new_secured_gt = available_slack + float(mttt)

        dep_dla_delta = 0.0
        domestic_val = domestic_list[i]
        if (
            not first_list[i] and str(domestic_val).strip() == '국내선'
            and pd.notna(prev_orig_ri) and pd.notna(orig_dep_dla) and pd.notna(new_secured_gt)
        ):
            baseline_secured_gt = (orig_std - prev_orig_ri).total_seconds() / 60
            baseline_short = baseline_secured_gt < SECURED_GT_THRESHOLD_MIN
            new_short = new_secured_gt < SECURED_GT_THRESHOLD_MIN
            if baseline_short and not new_short:
                dep_dla_delta = -SECURED_GT_DEP_DLA_STEP_MIN
            elif (not baseline_short) and new_short:
                dep_dla_delta = SECURED_GT_DEP_DLA_STEP_MIN

        new_dep_dla = max(0.0, orig_dep_dla + dep_dla_delta) if pd.notna(orig_dep_dla) else np.nan
        dep_dla_applied_delta = (new_dep_dla - orig_dep_dla) if pd.notna(orig_dep_dla) else 0.0

        new_ro = std + pd.Timedelta(minutes=new_cnx) + non_cnx_extra + pd.Timedelta(minutes=dep_dla_applied_delta)
        new_ri = new_ro + (orig_ri - orig_ro)

        adjustments[idx] = {'ro_kst': new_ro, 'ri_kst': new_ri, 'cnx_dla': new_cnx, 'dep_dla': new_dep_dla}
        prev_ri_effective = new_ri
        prev_orig_ri = orig_ri

    return adjustments


def _selfcheck():
    """비운항 로직 없이 빠르게 도는 핵심 회귀 점검 — 실패하면 본 실행 전에 즉시 중단."""
    # 1) 날짜 이월: STA<=STD면 익일, 아니면 당일
    df = pd.DataFrame({
        'Fltno': ['7C2151', '7C2152'],
        'Sch_date_KST': pd.to_datetime(['2026-01-05', '2026-01-05']),
        'STD_KST': pd.to_datetime(['2026-01-05 20:00', '2026-01-05 01:00']),
        'STA_KST': pd.to_datetime(['2026-01-05 21:00', '2026-01-05 05:00']),
        'STD_UTC': pd.to_datetime(['2026-01-05 11:00', '2026-01-04 16:00']),
        'STA_UTC': pd.to_datetime(['2026-01-05 12:00', '2026-01-04 20:00']),
        'Blocktime': [60, 240],
    })
    schedule = {
        '7C2151': {'std': (21, 5), 'sta': (0, 45), 'weekdays': [1] * 7},
        '7C2152': {'std': (1, 45), 'sta': (6, 55), 'weekdays': [1] * 7},
    }
    changed = apply_w26_std_sta(df, schedule)
    assert changed.all()
    assert df.loc[0, 'STA_KST'] == pd.Timestamp('2026-01-06 00:45'), '심야편 STA 익일 이월 실패'
    assert df.loc[1, 'STA_KST'] == pd.Timestamp('2026-01-05 06:55'), '당일 STA가 잘못 이월됨'

    # 2) 캐스케이드: 체인 첫 편 STD가 10분 당겨지면 RO/RI도 10분 당겨지고,
    #    후속편은 확보GT가 늘어나 연결지연이 준다.
    orig = pd.DataFrame({
        'Acno': ['HL0001', 'HL0001'],
        'Fltno': ['T1', 'T2'],
        'Sch_date_KST': pd.to_datetime(['2026-01-05', '2026-01-05']),
        'Status': ['ACT', 'ACT'],
        'Bt_idx': ['Y', 'Y'],
        'Domestic_Intl': ['국내선', '국내선'],
        'STD_KST': pd.to_datetime(['2026-01-05 08:00', '2026-01-05 09:00']),
        'RO_KST': pd.to_datetime(['2026-01-05 08:10', '2026-01-05 09:20']),
        'RI_KST': pd.to_datetime(['2026-01-05 08:50', '2026-01-05 10:00']),
        'CNX_DLA': [0.0, 15.0],
        'DEP_DLA': [10.0, 5.0],
        'MTTT': [35, 35],
    })
    cur = orig.copy()
    cur.loc[0, 'STD_KST'] = pd.Timestamp('2026-01-05 07:30')  # 30분 당김
    adj = compute_schedule_shift_cascade(cur, orig)
    assert 0 in adj and adj[0]['ro_kst'] == pd.Timestamp('2026-01-05 07:40'), '첫 편 RO가 STD 이동분만큼 안 밀림'
    assert 1 in adj, '캐스케이드가 후속편까지 전파되지 않음'
    assert adj[1]['cnx_dla'] == 0.0, f"확보GT가 늘어 연결지연이 0으로 해소돼야 하는데 {adj[1]['cnx_dla']}"

    # 3) 아무 것도 안 바뀌면 no-op
    adj_noop = compute_schedule_shift_cascade(orig.copy(), orig)
    assert adj_noop == {}, '변경 없는데 조정이 발생함(오탐)'


def overall_rate(recs, threshold):
    n = len(recs)
    delayed = sum(1 for r in recs if r['delay_min'] is not None and r['delay_min'] > threshold)
    return n, delayed, round((1 - delayed / n) * 100, 1) if n else None


def per_date_rate(recs, threshold):
    dfr = pd.DataFrame(recs)
    g = dfr.groupby('date').apply(
        lambda x: pd.Series({'n': len(x), 'delayed': (x['delay_min'] > threshold).sum()}),
        include_groups=False,
    )
    g['ontime_pct'] = (1 - g['delayed'] / g['n']) * 100
    return g


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--source', default=DEFAULT_SOURCE, help='W25 실적 엑셀 경로')
    p.add_argument('--name', default='W26 GT조정 스케줄 적용 (W25 실적 시뮬레이션)', help='저장할 시나리오 이름')
    p.add_argument('--delay-threshold', type=float, default=15.0, help='정시 판정 기준(분), 기본 15')
    p.add_argument('--no-save', action='store_true', help='결과를 data/scenarios/에 저장하지 않는다')
    p.add_argument('--report-md', default='w26_gt_schedule_scenario_report.md', help='정시율 비교 리포트 저장 경로')
    args = p.parse_args()

    t0 = time.time()
    _selfcheck()
    print('[자체 점검 통과]')

    src_path = Path(args.source)
    if not src_path.exists():
        raise SystemExit(f'[오류] 파일을 찾을 수 없습니다: {src_path}')
    raw = pd.read_excel(src_path)
    original_df = process_dataframe(raw)
    print(f'원본 로드: {src_path} ({len(original_df)}행, '
          f'{original_df["Sch_date_KST"].min()} ~ {original_df["Sch_date_KST"].max()})')

    matched_fltnos = sorted(set(W26_SCHEDULE) & set(original_df['Fltno'].unique()))
    unmatched_fltnos = sorted(set(W26_SCHEDULE) - set(original_df['Fltno'].unique()))
    print(f'W26 표 {len(W26_SCHEDULE)}개 편명 중 데이터에 존재: {len(matched_fltnos)}개, '
          f'미존재(자동 SKIP): {len(unmatched_fltnos)}개 {unmatched_fltnos}')

    current_df = original_df.copy()
    changed = apply_w26_std_sta(current_df, W26_SCHEDULE)
    print(f'STD/STA 치환 대상: {int(changed.sum())}행 (요일 불일치/편명 미존재는 자동 SKIP)')

    adjustments = compute_schedule_shift_cascade(current_df, original_df)
    for idx, adj in adjustments.items():
        current_df.at[idx, 'RO_KST'] = adj['ro_kst']
        current_df.at[idx, 'RI_KST'] = adj['ri_kst']
        current_df.at[idx, 'CNX_DLA'] = adj['cnx_dla']
        current_df.at[idx, 'DEP_DLA'] = adj['dep_dla']
    print(f'캐스케이드 재계산으로 RO/RI/지연이 바뀐 행: {len(adjustments)}행')

    threshold = args.delay_threshold
    recs_orig = compute_ontime_records(original_df)['records']
    recs_new = compute_ontime_records(current_df)['records']

    lines = []
    lines.append(f'# W26 GT조정 스케줄 적용 시뮬레이션 (정시 임계값 {threshold}분)\n')
    lines.append(f'- 원본: `{src_path}` ({len(original_df)}행)')
    lines.append(f'- STD/STA 치환 행수: {int(changed.sum())}')
    lines.append(f'- 캐스케이드 영향 행수: {len(adjustments)}')
    lines.append(f'- W26 표 편명 중 W25 데이터 미존재: {unmatched_fltnos}\n')

    ov_before = overall_rate(recs_orig, threshold)
    ov_after = overall_rate(recs_new, threshold)
    lines.append('## 전체 정시율 비교 (국내선+국제선)')
    lines.append(f'- 실적(W25 원본): 운항 {ov_before[0]}편, 지연 {ov_before[1]}편, 정시율 {ov_before[2]}%')
    lines.append(f'- W26 스케줄 적용: 운항 {ov_after[0]}편, 지연 {ov_after[1]}편, 정시율 {ov_after[2]}%')
    if ov_before[2] is not None and ov_after[2] is not None:
        lines.append(f'- 개선폭: {round(ov_after[2] - ov_before[2], 2)}%p\n')

    dom_orig_df = original_df[original_df['Domestic_Intl'] == '국내선']
    dom_new_df = current_df[current_df['Domestic_Intl'] == '국내선']
    dom_before = overall_rate(compute_ontime_records(dom_orig_df)['records'], threshold)
    dom_after = overall_rate(compute_ontime_records(dom_new_df)['records'], threshold)
    lines.append('## 국내선 한정 정시율 비교')
    lines.append(f'- 실적(W25 원본): 운항 {dom_before[0]}편, 지연 {dom_before[1]}편, 정시율 {dom_before[2]}%')
    lines.append(f'- W26 스케줄 적용: 운항 {dom_after[0]}편, 지연 {dom_after[1]}편, 정시율 {dom_after[2]}%')
    if dom_before[2] is not None and dom_after[2] is not None:
        lines.append(f'- 개선폭: {round(dom_after[2] - dom_before[2], 2)}%p\n')

    g_before = per_date_rate(recs_orig, threshold)
    g_after = per_date_rate(recs_new, threshold)
    cmp_df = g_before[['ontime_pct']].rename(columns={'ontime_pct': 'before'}).join(
        g_after[['ontime_pct']].rename(columns={'ontime_pct': 'after'})
    )
    cmp_df['delta'] = cmp_df['after'] - cmp_df['before']
    lines.append('## 개선폭 상위 15일')
    lines.append(cmp_df.sort_values('delta', ascending=False).head(15).to_markdown())
    lines.append('\n## 개선폭 하위 15일')
    lines.append(cmp_df.sort_values('delta').head(15).to_markdown())

    report_text = '\n'.join(str(x) for x in lines)
    print('\n' + report_text)
    Path(args.report_md).write_text(report_text, encoding='utf-8')
    print(f'\n리포트 저장: {args.report_md}')

    if args.no_save:
        print('\n[--no-save] 저장을 건너뜁니다.')
        return

    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    new_id = uuid.uuid4().hex
    pkl_path = SCENARIO_DIR / f'{new_id}.pkl'
    json_path = SCENARIO_DIR / f'{new_id}.json'
    with open(pkl_path, 'wb') as f:
        pickle.dump({'original_df': original_df, 'current_df': current_df}, f)

    dates_series = pd.to_datetime(current_df['Sch_date_KST']).dt.date
    meta = {
        'name': args.name,
        'saved_at': datetime.now().isoformat(timespec='seconds'),
        'rows': len(current_df),
        'date_range': [str(dates_series.min()), str(dates_series.max())],
        'filters': {'date': '', 'airline': '', 'tof': [], 'aircraft': 'all'},
    }
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)

    print(f'\n저장 완료: id={new_id}')
    print(meta)
    print(f'\n총 소요시간: {time.time() - t0:.1f}s')


if __name__ == '__main__':
    main()
