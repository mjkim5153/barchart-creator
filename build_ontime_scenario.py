# -*- coding: utf-8 -*-
"""
비운항 + 정시성 최적화 시나리오 생성 스크립트.

지정한 편(Fltno)들을 비운항 처리한 뒤, 그로 인해 발생한 항공기 연결 오류를
"지연전파 차단(딜레이 방화벽) 스왑"으로 복구하고, 같은 메커니즘을 나머지 스케줄
전체에도 적용해 정시율을 최대한 끌어올린 새 시나리오를 data/scenarios/에 저장한다.

사용 예:
    python build_ontime_scenario.py --cancel 7C115,7C120 --name "7C115_120 비운항 (정시성 최적화)"
    python build_ontime_scenario.py --cancel 7C115,7C120 --name "..." --source <scenario_id>
    python build_ontime_scenario.py --cancel 7C115,7C120 --name "..." --source ./data/flight_schedule_20260316.xlsx
    python build_ontime_scenario.py --cancel 7C115,7C120 --name "..." --exclude-dates 2026-03-02,2026-03-18

--exclude-dates: 지정한 날짜(YYYY-MM-DD, 콤마 구분)는 비운항 자체를 적용하지 않고 원본
스케줄을 그대로 유지한다(스왑/이식 탐색도 건너뜀). 스왑 탐색으로도 신규 연결 오류/curfew
위반을 끝까지 해결하지 못해 저장이 중단되는 날짜가 있을 때, 그 날짜만 비운항에서 제외하고
나머지 날짜는 정상 진행해 저장까지 완료하는 용도로 사용한다.

핵심 알고리즘: 서로 다른 두 기재(Acno)가 같은 공항에 도착하는 지점을 찾아 그 뒤
체인을 통째로 맞바꾼다. Acno가 바뀐 편은 compute_scenario_delay_adjustments()가
새 직전편 RI+MTTT 기준으로 연결지연을 물리적으로 재계산해주므로, 큰 지연을 맞은
기재의 이후 체인을 깨끗한 기재 쪽으로 옮기면 지연 전파를 끊을 수 있다. "문제 지점"은
세 종류다: (1) break — 비운항으로 새로 끊긴 연결(반드시 해결), (2) curfew —
GMP/PUS 23시 이후 이착륙 위반이 이번 조정으로 새로 발생한 지점(반드시 해결), (3) delay —
지연 임계값을 넘는 지점(순개선일 때만 선택 적용).

주의(실제 버그로 검증된 안전장치, 임의로 제거/완화하지 말 것):
  1. 같은 편명이 하루에 여러 번 재사용되는 셔틀 노선이 있으므로, 이동 대상은 반드시
     Fltno + 현재 소속 Acno로 함께 매칭한다(Fltno만으로 매칭하면 엉뚱한 회차가
     같이 끌려간다).
  2. "같은 공항 도착 지점끼리는 항상 안전하게 스왑된다"는 가정은 틀렸다 — 스왑된
     편은 RO_KST(fillna STD_KST) 기준으로 재정렬되므로, 스왑 직후 두 체인을 직접
     재구성해 인접편 연결을 재검증하고 하나라도 끊기면 그 후보는 기각해야 한다.

추가 제약(운항 실무 규칙, .claude/rules/ontime_optimization_rules.md 참고 — 임의로
제거/완화하지 말 것):
  3. Curfew: GMP/PUS는 23시 이후 이착륙 금지. 이번 조정으로 새로 위반이 생기는
     후보는 무조건 기각하고, 비운항 캐스케이드로 새로 생긴 위반은 break와 동일하게
     반드시 해결을 시도한다(원래 실적에 이미 있던 위반은 우리 책임이 아니므로
     경고만 남긴다).
  4. 해외공항(비 KOREAN_AIRPORTS)에서는 기재 조정(스왑/이식)이 이루어지면 안 된다 —
     연결 지점(station)이 국내공항일 때만 후보로 인정한다. 국내공항에서는 국제선간
     연결이어도 조정 가능하다.
  5. 국내선 중 원래 MTTT가 35/60(국제선 연결 여부에 따른 이원화 값)이었던 편은,
     체인이 바뀌면 새 직전편의 국내/국제 성격에 맞춰 MTTT를 다시 35/60으로
     맞춘다(그래야 연결지연 재계산이 실무적으로 유효함).
  6. 지연 몰아주기 방지: 어떤 편이든 실제 실적 대비 +30분을 초과하는 신규 지연을
     만드는 후보는 기각한다. 동률이면 최대 개별 지연이 더 작은(더 분산된) 후보를
     우선한다.
"""
import argparse
import json
import pickle
import re
import sys
import io
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', write_through=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', write_through=True)

import pandas as pd

from data_processor import (
    apply_flight_cancellation,
    apply_scenario_delay_adjustments,
    compute_scenario_delay_adjustments,
    compute_ontime_records,
    get_actype_grade,
    process_dataframe,
    KOREAN_AIRPORTS,
)

SCENARIO_DIR = Path('data/scenarios')
SCENARIO_ID_RE = re.compile(r'^[0-9a-f]{32}$')

CURFEW_AIRPORTS = {'GMP', 'PUS'}
CURFEW_HOUR = 23
DELAY_CAP_EXTRA_MIN = 30.0


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--cancel', required=True, help='비운항 처리할 Fltno 목록(콤마 구분, 예: 7C115,7C120)')
    p.add_argument('--name', required=True, help='저장할 시나리오 이름')
    p.add_argument('--source', default='auto',
                    help="기준 데이터 원본: 'auto'(최신 저장 시나리오, 기본값) / 저장 시나리오 ID(32자리 hex) / 엑셀 파일 경로")
    p.add_argument('--delay-threshold', type=float, default=15.0, help='정시 판정 기준(분), 기본 15')
    p.add_argument('--max-rounds', type=int, default=5, help='날짜별 반복 라운드 수, 기본 5')
    p.add_argument('--exclude-dates', default='',
                    help='비운항을 적용하지 않고 원본 스케줄을 유지할 날짜(YYYY-MM-DD, 콤마 구분)')
    p.add_argument('--auto-skip-unresolved', action='store_true',
                    help='라운드 탐색 후에도 미해결 break/curfew가 남은 날짜는 그 날짜만 자동으로 '
                         '원본 스케줄로 되돌리고(skip) 진행한다. skip 비율이 전체 날짜의 80%를 '
                         '초과하면 저장하지 않고 종료한다.')
    p.add_argument('--no-save', action='store_true', help='결과를 data/scenarios/에 저장하지 않는다(탐색용).')
    p.add_argument('--summary-json', default='',
                    help='정시율 비교 결과를 이 경로에 JSON으로 저장한다(배치 탐색 결과 취합용).')
    return p.parse_args()


def load_original_from_scenario(scenario_id):
    pkl_path = SCENARIO_DIR / f'{scenario_id}.pkl'
    if not pkl_path.exists():
        raise SystemExit(f'[오류] 저장된 시나리오를 찾을 수 없습니다: {scenario_id}')
    with open(pkl_path, 'rb') as f:
        snapshot = pickle.load(f)
    return snapshot['original_df'], scenario_id


def resolve_source(source):
    """(original_df, 출처 설명) 반환. auto/scenario_id/엑셀 파일 경로 세 가지를 지원한다."""
    if source == 'auto':
        json_files = list(SCENARIO_DIR.glob('*.json'))
        if not json_files:
            raise SystemExit('[오류] 저장된 시나리오가 없습니다. --source로 scenario_id 또는 엑셀 파일 경로를 지정하세요.')

        def saved_at(p):
            try:
                return json.loads(p.read_text(encoding='utf-8')).get('saved_at', '')
            except (OSError, ValueError):
                return ''

        latest = max(json_files, key=saved_at)
        original_df, scenario_id = load_original_from_scenario(latest.stem)
        return original_df, f'최신 저장 시나리오({latest.stem}, name="{json.loads(latest.read_text(encoding="utf-8")).get("name","")}")'

    if SCENARIO_ID_RE.match(source):
        original_df, scenario_id = load_original_from_scenario(source)
        return original_df, f'저장 시나리오({scenario_id})'

    path = Path(source)
    if not path.exists():
        raise SystemExit(f'[오류] 파일을 찾을 수 없습니다: {source}')
    raw = pd.read_excel(path)
    original_df = process_dataframe(raw)
    return original_df, f'엑셀 파일({path})'


def valid_mask(d_):
    return (d_['Status'] != 'CNL') & (d_['Bt_idx'] == 'Y') & (d_['Acno'].astype(str).str.strip() != '')


def violates_curfew(row, ro, ri):
    """GMP/PUS는 23시 이후 이착륙 금지. ro/ri가 없으면(NaT) 판정하지 않는다."""
    if row['Depstn'] in CURFEW_AIRPORTS and pd.notna(ro) and ro.hour >= CURFEW_HOUR:
        return True
    if row['Arrstn'] in CURFEW_AIRPORTS and pd.notna(ri) and ri.hour >= CURFEW_HOUR:
        return True
    return False


def day_chain_map(day_df):
    v = day_df[valid_mask(day_df)].copy()
    if v.empty:
        return {}
    v['_sk'] = v['RO_KST'].fillna(v['STD_KST'])
    v = v.sort_values('_sk')
    chains = {}
    for idx, row in v.iterrows():
        chains.setdefault(row['Acno'], []).append((idx, row))
    return chains


def find_errors(day_df, date_str):
    chains = day_chain_map(day_df)
    errors = []
    for acno, chain in chains.items():
        for i in range(1, len(chain)):
            _, prev = chain[i - 1]
            _, cur = chain[i]
            if prev['Arrstn'] != cur['Depstn']:
                errors.append((date_str, acno, prev['Fltno'], prev['Arrstn'], cur['Fltno'], cur['Depstn']))
    return errors


def find_curfew_violations(day_df, day_original_df, date_str):
    """현재 day_df 상태(캐스케이드 재계산 반영)에서 curfew를 위반하는 유효편 목록을
    (idx, date, Acno, Fltno, Depstn, Arrstn) 튜플로 반환한다. idx는 물리적 편
    인스턴스를 스왑과 무관하게 식별하는 안정적인 키(행 인덱스는 Acno 재배정으로도
    바뀌지 않음)이므로, 베이스라인(pre_cancel_curfew_idx) 비교는 항상 idx로 한다."""
    state = flight_state_map_for(day_df, day_original_df)
    valid = day_df[valid_mask(day_df)]
    out = []
    for idx, row in valid.iterrows():
        st = state.get(idx)
        if st is None:
            continue
        if violates_curfew(row, st['ro'], st['ri']):
            out.append((idx, date_str, row['Acno'], row['Fltno'], row['Depstn'], row['Arrstn']))
    return out


def find_bridge_candidates(chains, exclude_acno, required_dep, required_arr):
    """suffix 스왑으로 못 고치는 break를 위한 편도 이식 후보: 정확히 필요한
    (Depstn, Arrstn)을 가진 편을, 자기 원래 위치에서 빼도 그 체인이 안 깨지는
    경우만 후보로 반환한다."""
    candidates = []
    for donor_acno, donor_chain in chains.items():
        if donor_acno == exclude_acno:
            continue
        for pos, (idx, row) in enumerate(donor_chain):
            if row['Depstn'] != required_dep or row['Arrstn'] != required_arr:
                continue
            if pos == 0 or pos == len(donor_chain) - 1:
                removable = True
            else:
                removable = donor_chain[pos - 1][1]['Arrstn'] == donor_chain[pos + 1][1]['Depstn']
            if removable:
                candidates.append((donor_acno, pos))
    return candidates


def chain_connected(rows):
    """rows: [(idx, row), ...] RO_KST(fillna STD_KST) 순 정렬된 한 Acno의 편 목록.
    인접 편끼리 Arrstn==Depstn이 전부 성립하면 True."""
    for i in range(1, len(rows)):
        if rows[i - 1][1]['Arrstn'] != rows[i][1]['Depstn']:
            return False
    return True


def acno_chain_rows(temp, acno):
    v = temp[valid_mask(temp) & (temp['Acno'] == acno)]
    if v.empty:
        return []
    sk = v['RO_KST'].fillna(v['STD_KST'])
    order = sk.sort_values().index
    return [(idx, v.loc[idx]) for idx in order]


def sync_dynamic_mttt(df, chains, dual_mode_idx):
    """dual_mode_idx(원래 MTTT가 35/60이었던 국내선)에 대해, 주어진 chains 상 직전
    편의 Domestic_Intl에 맞춰 MTTT를 60(국제선 연결)/35(국내선 연결)로 재설정한다.
    dual_mode_idx에 없는 편(원래 다른 고정 MTTT였던 편)은 절대 건드리지 않는다."""
    for acno, chain in chains.items():
        for i in range(1, len(chain)):
            idx, row = chain[i]
            if idx not in dual_mode_idx:
                continue
            prev_row = chain[i - 1][1]
            new_mttt = 60.0 if prev_row['Domestic_Intl'] == '국제선' else 35.0
            if df.at[idx, 'MTTT'] != new_mttt:
                df.at[idx, 'MTTT'] = new_mttt


def flight_state_map_for(day_df, day_original_df):
    """apply_scenario_delay_adjustments()의 무거운 부가 컬럼 없이
    compute_scenario_delay_adjustments()만 직접 호출해 ro/ri/delay_min만 뽑아낸다
    (후보 탐색에서 수만 번 호출되므로 오버헤드를 최소화). ro/ri는 curfew 판정에,
    delay_min은 지연 문제 탐지 및 지연 캡 판정에 쓰인다."""
    adjustments = compute_scenario_delay_adjustments(day_df, day_original_df)
    valid = day_df[valid_mask(day_df)]
    state = {}
    for idx, row in valid.iterrows():
        adj = adjustments.get(idx)
        ro = adj['ro_kst'] if adj else row['RO_KST']
        ri = adj['ri_kst'] if adj else row['RI_KST']
        std = row['STD_KST']
        delay_min = (ro - std).total_seconds() / 60 if pd.notna(ro) and pd.notna(std) else None
        state[idx] = {'ro': ro, 'ri': ri, 'delay_min': delay_min}
    return state


def simulate_swap(day_df, day_original_df, chains, acno_actype_mode, acno_a, split_a, acno_b, split_b,
                   state_before, delay_threshold, dual_mode_idx, orig_delay_map):
    suffix_a = chains[acno_a][split_a + 1:]
    suffix_b = chains[acno_b][split_b + 1:]
    if not suffix_a or not suffix_b:
        return None
    fltnos_a = {row['Fltno'] for _, row in suffix_a}
    fltnos_b = {row['Fltno'] for _, row in suffix_b}
    idxs_a = [idx for idx, _ in suffix_a]
    idxs_b = [idx for idx, _ in suffix_b]

    temp = day_df.copy()
    # 주의: Fltno만으로 매칭하면 안 된다 — 셔틀 노선은 같은 편명이 하루에 여러 번
    # 재사용되므로, 반드시 현재 소속 Acno까지 함께 걸어야 엉뚱한 회차가 같이
    # 끌려가지 않는다.
    mask_a = temp['Fltno'].isin(fltnos_a) & (temp['Acno'] == acno_a)
    mask_b = temp['Fltno'].isin(fltnos_b) & (temp['Acno'] == acno_b)
    new_actype_b = acno_actype_mode.get(acno_b, '')
    new_actype_a = acno_actype_mode.get(acno_a, '')
    temp.loc[mask_a, 'Acno'] = acno_b
    temp.loc[mask_a, 'Actype'] = new_actype_b
    temp.loc[mask_a, 'Actype_Grade'] = get_actype_grade(new_actype_b)
    temp.loc[mask_b, 'Acno'] = acno_a
    temp.loc[mask_b, 'Actype'] = new_actype_a
    temp.loc[mask_b, 'Actype_Grade'] = get_actype_grade(new_actype_a)

    # 안전장치(핵심): 스왑된 편들은 RO_KST(fillna STD_KST) 기준으로 그 Acno의 기존
    # 편들과 통째로 재정렬되므로, 이식된 suffix가 받는 쪽 체인과 시간대가 겹치면
    # 의도한 접합부가 아닌 곳이 인접해 연결이 끊길 수 있다. 재정렬된 두 체인을 직접
    # 재구성해 인접편 연결을 명시적으로 재검증하고, 하나라도 끊기면 이 후보는
    # 무조건 기각한다.
    chain_a_rows = acno_chain_rows(temp, acno_a)
    chain_b_rows = acno_chain_rows(temp, acno_b)
    if not chain_connected(chain_a_rows) or not chain_connected(chain_b_rows):
        return None

    sync_dynamic_mttt(temp, {acno_a: chain_a_rows, acno_b: chain_b_rows}, dual_mode_idx)

    adjustments = compute_scenario_delay_adjustments(temp, day_original_df)
    affected_idx = idxs_a + idxs_b
    before_total = sum((state_before.get(i) or {}).get('delay_min') or 0.0 for i in affected_idx)
    before_count = sum(1 for i in affected_idx if ((state_before.get(i) or {}).get('delay_min') or 0.0) > delay_threshold)
    after_total = 0.0
    after_count = 0
    after_max = 0.0
    state_after = {}
    for i in affected_idx:
        ro = adjustments[i]['ro_kst'] if i in adjustments else temp.at[i, 'RO_KST']
        ri = adjustments[i]['ri_kst'] if i in adjustments else temp.at[i, 'RI_KST']
        std = temp.at[i, 'STD_KST']
        dm = None
        if pd.notna(ro) and pd.notna(std):
            dm = (ro - std).total_seconds() / 60
            after_total += dm
            after_max = max(after_max, dm)
            if dm > delay_threshold:
                after_count += 1
            # 지연 몰아주기 방지: 실제 실적 대비 +30분을 넘는 신규 지연은 무조건 기각
            orig_delay = orig_delay_map.get(i)
            if orig_delay is not None and dm > orig_delay + DELAY_CAP_EXTRA_MIN:
                return None
        state_after[i] = {'ro': ro, 'ri': ri, 'delay_min': dm}

        # curfew: 이 스왑 전에는 위반이 아니었는데 후에 새로 위반이 되면 무조건 기각
        before_state = state_before.get(i) or {}
        row_i = temp.loc[i]
        if violates_curfew(row_i, ro, ri) and not violates_curfew(row_i, before_state.get('ro'), before_state.get('ri')):
            return None

    improved = (after_count < before_count) or (after_count == before_count and after_total < before_total - 0.5)
    return {
        'acno_a': acno_a, 'acno_b': acno_b,
        'fltnos_a': fltnos_a, 'fltnos_b': fltnos_b,
        'before_count': before_count, 'after_count': after_count,
        'before_total': before_total, 'after_total': after_total,
        'after_max': after_max,
        'improved': improved,
        'state_after': state_after,
    }


def simulate_insert(day_df, day_original_df, chains, acno_actype_mode, acno_a, donor_acno, donor_pos,
                     state_before, delay_threshold, dual_mode_idx, orig_delay_map):
    """suffix 스왑으로 해결되지 않는 break를 위한 폴백: 다른 기재의 '빼도 되는' 편
    하나(정확히 필요한 Depstn/Arrstn를 가진 편)만 acno_a로 옮겨 끊긴 지점을 메운다
    (양방향 스왑이 아니라 편도 이식 — donor 쪽은 그 편이 빠져도 자기 체인이 깨지지
    않는 위치일 때만 후보가 된다)."""
    donor_idx, donor_row = chains[donor_acno][donor_pos]
    fltno = donor_row['Fltno']

    temp = day_df.copy()
    mask = temp['Fltno'].isin([fltno]) & (temp['Acno'] == donor_acno)
    new_actype = acno_actype_mode.get(acno_a, '')
    temp.loc[mask, 'Acno'] = acno_a
    temp.loc[mask, 'Actype'] = new_actype
    temp.loc[mask, 'Actype_Grade'] = get_actype_grade(new_actype)

    chain_a_rows = acno_chain_rows(temp, acno_a)
    chain_donor_rows = acno_chain_rows(temp, donor_acno)
    if not chain_connected(chain_a_rows) or not chain_connected(chain_donor_rows):
        return None

    sync_dynamic_mttt(temp, {acno_a: chain_a_rows, donor_acno: chain_donor_rows}, dual_mode_idx)

    adjustments = compute_scenario_delay_adjustments(temp, day_original_df)
    ro = adjustments[donor_idx]['ro_kst'] if donor_idx in adjustments else temp.at[donor_idx, 'RO_KST']
    ri = adjustments[donor_idx]['ri_kst'] if donor_idx in adjustments else temp.at[donor_idx, 'RI_KST']
    std = temp.at[donor_idx, 'STD_KST']
    before_state = state_before.get(donor_idx) or {}
    before_total = before_state.get('delay_min') or 0.0
    before_count = 1 if before_total > delay_threshold else 0
    if pd.notna(ro) and pd.notna(std):
        after_total = (ro - std).total_seconds() / 60
    else:
        after_total = before_total
    after_count = 1 if after_total > delay_threshold else 0

    orig_delay = orig_delay_map.get(donor_idx)
    if orig_delay is not None and after_total > orig_delay + DELAY_CAP_EXTRA_MIN:
        return None

    row_donor = temp.loc[donor_idx]
    if violates_curfew(row_donor, ro, ri) and not violates_curfew(row_donor, before_state.get('ro'), before_state.get('ri')):
        return None

    return {
        'acno_a': acno_a, 'acno_b': donor_acno,
        'fltnos_a': set(), 'fltnos_b': {fltno},
        'before_count': before_count, 'after_count': after_count,
        'before_total': before_total, 'after_total': after_total,
        'after_max': after_total,
        'improved': after_total <= before_total,
    }


def apply_swap_to_df(df, date_mask, acno_actype_mode, result):
    mask_a = date_mask & df['Fltno'].isin(result['fltnos_a']) & (df['Acno'] == result['acno_a'])
    mask_b = date_mask & df['Fltno'].isin(result['fltnos_b']) & (df['Acno'] == result['acno_b'])
    new_actype_b = acno_actype_mode.get(result['acno_b'], '')
    new_actype_a = acno_actype_mode.get(result['acno_a'], '')
    df.loc[mask_a, 'Acno'] = result['acno_b']
    df.loc[mask_a, 'Actype'] = new_actype_b
    df.loc[mask_a, 'Actype_Grade'] = get_actype_grade(new_actype_b)
    df.loc[mask_b, 'Acno'] = result['acno_a']
    df.loc[mask_b, 'Actype'] = new_actype_a
    df.loc[mask_b, 'Actype_Grade'] = get_actype_grade(new_actype_a)


def main():
    args = parse_args()
    cancel_fltnos = [f.strip() for f in args.cancel.split(',') if f.strip()]
    if not cancel_fltnos:
        raise SystemExit('[오류] --cancel에 유효한 Fltno가 없습니다.')
    exclude_dates = {d.strip() for d in args.exclude_dates.split(',') if d.strip()}

    delay_threshold = args.delay_threshold
    max_rounds = args.max_rounds

    t0 = time.time()

    original_df, source_desc = resolve_source(args.source)
    print(f"기준 데이터: {source_desc} ({len(original_df)}행)")
    print(f"비운항 대상: {cancel_fltnos}")

    # ----- 비운항 전 오류 기준선(우리 책임이 아닌 기존 오류) -----
    orig_ext = original_df.copy()
    orig_ext['_date_str'] = pd.to_datetime(orig_ext['Sch_date_KST']).dt.date.astype(str)
    all_dates = sorted(orig_ext['_date_str'].unique())

    import os
    _limit = os.environ.get('LIMIT_DATES')  # 내부 스모크테스트용(문서화 안 함) — 지정 시 앞 N일만 처리
    if _limit:
        all_dates = all_dates[:int(_limit)]
        print(f"[TEST MODE] 날짜 {len(all_dates)}개로 제한")

    print(f"전체 날짜 수: {len(all_dates)}")

    pre_cancel_errors = set()
    for date in all_dates:
        day = orig_ext[orig_ext['_date_str'] == date]
        pre_cancel_errors.update(find_errors(day, date))
    print(f"비운항 전 기존 오류(무관, 우리 책임 아님): {len(pre_cancel_errors)}건")

    # curfew 베이스라인: 원래 실적(비운항 전)에 이미 있던 위반은 우리 책임이 아니다.
    # idx로 식별해야 한다 — Acno가 스왑으로 바뀌어도 물리적으로 같은 편 인스턴스임을
    # 놓치지 않기 위함(행 인덱스는 Acno/Actype/MTTT를 in-place로 바꿔도 그대로 유지됨).
    orig_valid = orig_ext[valid_mask(orig_ext)]
    _ro = orig_valid['RO_KST']
    _ri = orig_valid['RI_KST']
    _dep_curfew = orig_valid['Depstn'].isin(CURFEW_AIRPORTS) & _ro.notna() & (_ro.dt.hour >= CURFEW_HOUR)
    _arr_curfew = orig_valid['Arrstn'].isin(CURFEW_AIRPORTS) & _ri.notna() & (_ri.dt.hour >= CURFEW_HOUR)
    pre_cancel_curfew_idx = set(orig_valid.index[_dep_curfew | _arr_curfew])
    print(f"비운항 전 기존 curfew 위반(무관, 우리 책임 아님): {len(pre_cancel_curfew_idx)}건")

    # MTTT 이원화(35/60) 대상: 원래 국내선이면서 MTTT가 35 또는 60이었던 편만 동적 재계산 대상.
    mttt_numeric = pd.to_numeric(original_df['MTTT'], errors='coerce')
    dual_mode_idx = set(original_df.index[(original_df['Domestic_Intl'] == '국내선') & mttt_numeric.isin([35.0, 60.0])])
    print(f"MTTT 동적 재계산(35↔60) 대상 국내선: {len(dual_mode_idx)}건")

    # ----- 비운항 적용 -----
    df = original_df.copy()
    df['_date_str'] = pd.to_datetime(df['Sch_date_KST']).dt.date.astype(str)
    apply_flight_cancellation(df, cancel_fltnos)
    if exclude_dates:
        unknown = exclude_dates - set(all_dates)
        if unknown:
            print(f"[경고] --exclude-dates 중 데이터에 없는 날짜: {sorted(unknown)}")
        revert_mask = df['_date_str'].isin(exclude_dates)
        df.loc[revert_mask, 'Acno'] = original_df.loc[revert_mask, 'Acno']
        df.loc[revert_mask, 'D_OPER'] = original_df.loc[revert_mask, 'D_OPER']
        print(f"제외 날짜(비운항 미적용, 원본 스케줄 유지): {sorted(exclude_dates)} ({int(revert_mask.sum())}행 원복)")

    # 성능 핵심: compute_scenario_delay_adjustments()는 넘겨받은 original_df 전체를
    # 기준으로 예측 맵을 매번 재계산하므로, 하루~수만 번 호출되는 후보 탐색에서
    # 매번 전체 데이터셋을 스캔하면 극도로 느려진다. original_df를 날짜별로 미리
    # 잘라 그 날짜 서브셋만 넘긴다(캐스케이드 로직은 (Sch_date_KST, Acno) 그룹
    # 내에서만 작동하므로 날짜 서브셋으로 좁혀도 결과는 동일하다).
    original_by_date = {dt: orig_ext[orig_ext['_date_str'] == dt].drop(columns=['_date_str']) for dt in all_dates}

    # 지연 몰아주기 방지용 실제 실적(비운항 전) 지연 베이스라인 — 날짜별로 미리 계산.
    orig_delay_by_date = {}
    for dt in all_dates:
        day_orig = original_by_date[dt]
        v = day_orig[valid_mask(day_orig)]
        ro, std = v['RO_KST'], v['STD_KST']
        ok = ro.notna() & std.notna()
        dm = ((ro - std).dt.total_seconds() / 60)[ok]
        orig_delay_by_date[dt] = dm.to_dict()

    acno_actype_mode = (
        original_df.dropna(subset=['Acno', 'Actype'])
        .groupby('Acno')['Actype']
        .agg(lambda s: s.mode().iat[0] if not s.mode().empty else '')
        .to_dict()
    )

    swap_log = []
    unresolved_breaks = {}
    unresolved_curfew = {}
    auto_skipped_dates = set()

    for di, date in enumerate(all_dates):
        date_mask = (df['_date_str'] == date)
        day_original_df = original_by_date[date]
        orig_delay_map = orig_delay_by_date[date]

        if date in exclude_dates:
            # 비운항 자체를 적용하지 않은 날짜 — 스왑 탐색/MTTT 동기화 없이 원본 그대로 유지
            continue

        for round_num in range(max_rounds):
            day_df = df[date_mask]
            chains = day_chain_map(day_df)
            sync_dynamic_mttt(df, chains, dual_mode_idx)
            day_df = df[date_mask]  # MTTT 갱신 반영해 재슬라이스
            chains = day_chain_map(day_df)
            state_before = flight_state_map_for(day_df, day_original_df)

            # ----- 문제 지점 세 종류 -----
            problems = []  # (ptype, acno_a, split_a, key)

            for acno, chain in chains.items():
                for i in range(1, len(chain)):
                    _, prev = chain[i - 1]
                    _, cur = chain[i]
                    if prev['Arrstn'] != cur['Depstn']:
                        key = (date, acno, prev['Fltno'], prev['Arrstn'], cur['Fltno'], cur['Depstn'])
                        if key not in pre_cancel_errors:
                            problems.append(('break', acno, i - 1, key))

            for acno, chain in chains.items():
                for p, (idx, row) in enumerate(chain):
                    if p == 0:
                        continue
                    st = state_before.get(idx)
                    if st is None:
                        continue
                    if violates_curfew(row, st['ro'], st['ri']) and idx not in pre_cancel_curfew_idx:
                        problems.append(('curfew', acno, p - 1, idx))

            for acno, chain in chains.items():
                onset = None
                for p, (idx, row) in enumerate(chain):
                    dm = (state_before.get(idx) or {}).get('delay_min')
                    if dm is not None and dm > delay_threshold:
                        onset = p
                        break
                if onset is None or onset == 0:
                    continue
                problems.append(('delay', acno, onset - 1, None))

            if not problems:
                break

            # 해외공항(비 KOREAN_AIRPORTS)에서는 기재 조정이 이루어지면 안 된다 —
            # 연결 지점(station)이 국내공항인 경우만 후보 인덱스에 등록한다. 이 필터
            # 하나로 break/curfew/delay 스왑 탐색 전부에 동일하게 적용된다(station_index
            # 조회에서 자연히 후보가 0개가 됨).
            station_index = {}
            for acno, chain in chains.items():
                for p in range(len(chain) - 1):
                    _, row = chain[p]
                    if row['Arrstn'] not in KOREAN_AIRPORTS:
                        continue
                    station_index.setdefault(row['Arrstn'], []).append((acno, p))

            break_options = {}  # (acno_a, split_a, key) -> [(mode, acno_b, split_b, r), ...]
            curfew_options = {}
            delay_candidates = []  # (acno_a, split_a, acno_b, split_b, r)
            seen_pairs = set()

            for ptype, acno_a, split_a, key in problems:
                station = chains[acno_a][split_a][1]['Arrstn']
                for acno_b, split_b in station_index.get(station, []):
                    if acno_b == acno_a:
                        continue
                    pair_key = (ptype, acno_a, split_a, acno_b, split_b)
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)
                    r = simulate_swap(day_df, day_original_df, chains, acno_actype_mode,
                                       acno_a, split_a, acno_b, split_b, state_before, delay_threshold,
                                       dual_mode_idx, orig_delay_map)
                    if r is None:
                        continue
                    if ptype == 'break':
                        break_options.setdefault((acno_a, split_a, key), []).append(('swap', acno_b, split_b, r))
                    elif ptype == 'curfew':
                        # 스왑이 실제로 해당 편의 curfew를 해소하는지까지 확인한 후보만 채택
                        onset_idx = chains[acno_a][split_a + 1][0]
                        onset_row = chains[acno_a][split_a + 1][1]
                        st_after = r['state_after'].get(onset_idx)
                        if st_after and not violates_curfew(onset_row, st_after['ro'], st_after['ri']):
                            curfew_options.setdefault((acno_a, split_a, key), []).append(('swap', acno_b, split_b, r))
                    elif r['improved']:
                        delay_candidates.append((acno_a, split_a, acno_b, split_b, r))

            # break 문제는 suffix 스왑만으로 안 풀리는 경우가 많다(받는 쪽 체인
            # 전체를 재정렬하면서 다른 곳이 또 끊기기 쉬움) — 편도 이식(정확히 필요한
            # Depstn/Arrstn를 가진 편 하나만 옮기는 방식) 폴백을 항상 함께 시도한다.
            # 편입 지점(required_dep)이 해외공항이면 이식 자체를 시도하지 않는다.
            for ptype, acno_a, split_a, key in problems:
                if ptype != 'break':
                    continue
                required_dep = chains[acno_a][split_a][1]['Arrstn']
                if required_dep not in KOREAN_AIRPORTS:
                    continue
                required_arr = chains[acno_a][split_a + 1][1]['Depstn']
                for donor_acno, donor_pos in find_bridge_candidates(chains, acno_a, required_dep, required_arr):
                    r = simulate_insert(day_df, day_original_df, chains, acno_actype_mode,
                                         acno_a, donor_acno, donor_pos, state_before, delay_threshold,
                                         dual_mode_idx, orig_delay_map)
                    if r is None:
                        continue
                    break_options.setdefault((acno_a, split_a, key), []).append(('insert', donor_acno, donor_pos, r))

            used = set()
            applied = 0

            # break 문제는 해결 가능한 후보가 있으면 반드시(지연 영향 최소인 것을,
            # suffix 스왑이든 편도 이식이든 관계없이) 적용한다.
            break_chosen = []
            for (acno_a, split_a, key), opts in break_options.items():
                opts.sort(key=lambda o: (o[3]['after_count'], o[3]['after_total'], o[3]['after_max']))
                _, _, _, r = opts[0]
                break_chosen.append((r, key))
            break_chosen.sort(key=lambda t: t[0]['after_total'])

            for r, key in break_chosen:
                if r['acno_a'] in used or r['acno_b'] in used:
                    continue
                apply_swap_to_df(df, date_mask, acno_actype_mode, r)
                used.add(r['acno_a'])
                used.add(r['acno_b'])
                swap_log.append({
                    'date': date, 'round': round_num + 1, 'type': 'break',
                    'acno_a': r['acno_a'], 'acno_b': r['acno_b'],
                    'fltnos_a': sorted(r['fltnos_a']), 'fltnos_b': sorted(r['fltnos_b']),
                    'before_total': round(r['before_total'], 1), 'after_total': round(r['after_total'], 1),
                })
                applied += 1

            # curfew 문제도 break와 동일 우선순위로, 해결(해소 확인된) 후보가 있으면 반드시 적용한다.
            curfew_chosen = []
            for (acno_a, split_a, key), opts in curfew_options.items():
                opts.sort(key=lambda o: (o[3]['after_count'], o[3]['after_total'], o[3]['after_max']))
                _, _, _, r = opts[0]
                curfew_chosen.append((r, key))
            curfew_chosen.sort(key=lambda t: t[0]['after_total'])

            for r, key in curfew_chosen:
                if r['acno_a'] in used or r['acno_b'] in used:
                    continue
                apply_swap_to_df(df, date_mask, acno_actype_mode, r)
                used.add(r['acno_a'])
                used.add(r['acno_b'])
                swap_log.append({
                    'date': date, 'round': round_num + 1, 'type': 'curfew',
                    'acno_a': r['acno_a'], 'acno_b': r['acno_b'],
                    'fltnos_a': sorted(r['fltnos_a']), 'fltnos_b': sorted(r['fltnos_b']),
                    'before_total': round(r['before_total'], 1), 'after_total': round(r['after_total'], 1),
                })
                applied += 1

            # delay 문제는 순개선일 때만 선택 적용(지연편수 감소 우선, 총 지연분 감소
            # 차선, 최대 개별 지연이 작은=더 분산된 후보 3순위)
            delay_candidates = [c for c in delay_candidates if c[4]['acno_a'] not in used and c[4]['acno_b'] not in used]
            delay_candidates.sort(key=lambda c: (
                -(c[4]['before_count'] - c[4]['after_count']),
                c[4]['after_total'] - c[4]['before_total'],
                c[4]['after_max'],
            ))
            for acno_a, split_a, acno_b, split_b, r in delay_candidates:
                if r['acno_a'] in used or r['acno_b'] in used:
                    continue
                apply_swap_to_df(df, date_mask, acno_actype_mode, r)
                used.add(r['acno_a'])
                used.add(r['acno_b'])
                swap_log.append({
                    'date': date, 'round': round_num + 1, 'type': 'delay',
                    'acno_a': r['acno_a'], 'acno_b': r['acno_b'],
                    'fltnos_a': sorted(r['fltnos_a']), 'fltnos_b': sorted(r['fltnos_b']),
                    'before_count': r['before_count'], 'after_count': r['after_count'],
                    'before_total': round(r['before_total'], 1), 'after_total': round(r['after_total'], 1),
                })
                applied += 1

            if applied == 0:
                break

        # 이 날짜의 라운드 종료 후, MTTT를 최종 체인 상태로 한 번 더 동기화하고
        # (max_rounds 소진으로 루프가 끝난 경우에도 반영되도록) 여전히 남은 문제
        # (우리 책임)를 최종 기록한다.
        final_day_df = df[date_mask]
        sync_dynamic_mttt(df, day_chain_map(final_day_df), dual_mode_idx)
        final_day_df = df[date_mask]

        final_errors = find_errors(final_day_df, date)
        remaining = [e for e in final_errors if e not in pre_cancel_errors]

        final_curfew = find_curfew_violations(final_day_df, day_original_df, date)
        remaining_curfew = [c for c in final_curfew if c[0] not in pre_cancel_curfew_idx]

        if (remaining or remaining_curfew) and args.auto_skip_unresolved:
            # 이 날짜만 원본 스케줄로 되돌린다(--exclude-dates와 동일 패턴) — 라운드
            # 탐색 도중 스왑으로 바뀔 수 있는 Actype/Actype_Grade/MTTT까지 함께 복원해야
            # 부분 적용된 스왑 흔적이 남지 않는다.
            revert_cols = ['Acno', 'D_OPER', 'Actype', 'Actype_Grade', 'MTTT']
            df.loc[date_mask, revert_cols] = original_df.loc[date_mask, revert_cols]
            auto_skipped_dates.add(date)
            swap_log[:] = [s for s in swap_log if s['date'] != date]
        else:
            if remaining:
                unresolved_breaks[date] = remaining
            if remaining_curfew:
                unresolved_curfew[date] = remaining_curfew

        if (di + 1) % 10 == 0 or di == len(all_dates) - 1:
            elapsed = time.time() - t0
            print(f"  진행: {di+1}/{len(all_dates)}일({date}) 처리, 누적 스왑 {len(swap_log)}건, "
                  f"자동 skip {len(auto_skipped_dates)}건, "
                  f"미해결 break {sum(len(v) for v in unresolved_breaks.values())}건, "
                  f"미해결 curfew {sum(len(v) for v in unresolved_curfew.values())}건, 경과 {elapsed:.1f}s")

    print(f"\n스왑 탐색/적용 완료. 총 스왑 {len(swap_log)}건, 경과 {time.time()-t0:.1f}s")

    # ----- 전체 재검증 -----
    df_noext = df.drop(columns=['_date_str'])
    all_errors = []
    all_curfew = []
    for date in all_dates:
        day_df = df[df['_date_str'] == date]
        all_errors.extend(find_errors(day_df, date))
        all_curfew.extend(find_curfew_violations(day_df, original_by_date[date], date))

    new_errors = [e for e in all_errors if e not in pre_cancel_errors]
    print(f"\n전체 {len(all_dates)}일 재검증: 전체 연결 오류 {len(all_errors)}건 "
          f"(비운항 전 기존 오류 {len(pre_cancel_errors)}건 포함)")
    print(f"비운항으로 인한 신규 오류(미해결): {len(new_errors)}건")
    for e in new_errors:
        print("  ", e)

    new_curfew = [c for c in all_curfew if c[0] not in pre_cancel_curfew_idx]
    pre_existing_curfew = len(all_curfew) - len(new_curfew)
    print(f"\n전체 {len(all_dates)}일 재검증: curfew(23시 이후 GMP/PUS 이착륙) 위반 {len(all_curfew)}건 "
          f"(원래 실적에도 있던 위반 {pre_existing_curfew}건 포함)")
    print(f"비운항/스왑으로 인한 신규 curfew 위반(미해결): {len(new_curfew)}건")
    for c in new_curfew:
        print("  ", c[1:])

    # 참고용 진단: 같은 노선(Depstn-Arrstn) 내 STD 순서와 최종 RO 순서 역전 사례
    # (저장을 막지 않음 — 지연 몰아주기 방지 캡/분산 tie-break가 최대한 줄이지만,
    # suffix 단위 스왑 구조상 완전한 보장은 아님)
    inversions = []
    for date in all_dates:
        day_df = df[df['_date_str'] == date]
        valid = day_df[valid_mask(day_df)]
        for (dep, arr), grp in valid.groupby(['Depstn', 'Arrstn']):
            g = grp.dropna(subset=['STD_KST', 'RO_KST']).sort_values('STD_KST')
            rows = list(g[['Fltno', 'Acno', 'STD_KST', 'RO_KST']].itertuples(index=False))
            for i in range(1, len(rows)):
                if rows[i].RO_KST < rows[i - 1].RO_KST - pd.Timedelta(minutes=1):
                    inversions.append((date, dep, arr, rows[i - 1].Fltno, str(rows[i - 1].RO_KST),
                                        rows[i].Fltno, str(rows[i].RO_KST)))
    print(f"\n=== 동일 노선 STD-RO 순서 역전 진단(참고용, 저장 차단 없음): {len(inversions)}건 ===")
    for x in inversions[:15]:
        print("  ", x)

    # ----- 정시율 비교 -----
    df_after_cancel_only = original_df.copy()
    apply_flight_cancellation(df_after_cancel_only, cancel_fltnos)
    adj_cancel_only = apply_scenario_delay_adjustments(df_after_cancel_only, original_df)
    adj_final = apply_scenario_delay_adjustments(df_noext, original_df)

    recs_orig = compute_ontime_records(original_df)['records']
    recs_cancel_only = compute_ontime_records(adj_cancel_only)['records']
    recs_final = compute_ontime_records(adj_final)['records']

    def overall_rate(recs):
        n = len(recs)
        delayed = sum(1 for r in recs if r['delay_min'] is not None and r['delay_min'] > delay_threshold)
        return n, delayed, round((1 - delayed / n) * 100, 1) if n else None

    print("\n=== 전체 정시율 비교(국내선+국제선) ===")
    print("실적(비운항 전):", overall_rate(recs_orig))
    print("비운항 직후(스왑 전):", overall_rate(recs_cancel_only))
    print("최종(스왑 후):", overall_rate(recs_final))

    def domestic_rate(df_):
        d = df_[df_['Domestic_Intl'] == '국내선']
        return overall_rate(compute_ontime_records(d)['records'])

    dom_orig = domestic_rate(original_df)
    dom_cancel_only = domestic_rate(adj_cancel_only)
    dom_final = domestic_rate(adj_final)
    print("\n=== 국내선 한정 정시율 비교 ===")
    print("실적(비운항 전):", dom_orig)
    print("비운항 직후(스왑 전):", dom_cancel_only)
    print("최종(스왑 후):", dom_final)

    def per_date_rate(recs):
        dfr = pd.DataFrame(recs)
        g = dfr.groupby('date').apply(
            lambda x: pd.Series({'n': len(x), 'delayed': (x['delay_min'] > delay_threshold).sum()}),
            include_groups=False,
        )
        g['ontime_pct'] = (1 - g['delayed'] / g['n']) * 100
        return g

    g_before = per_date_rate(recs_cancel_only)
    g_after = per_date_rate(recs_final)
    cmp_df = g_before[['ontime_pct']].rename(columns={'ontime_pct': 'before'}).join(
        g_after[['ontime_pct']].rename(columns={'ontime_pct': 'after'})
    )
    cmp_df['delta'] = cmp_df['after'] - cmp_df['before']
    print("\n=== 정시율 개선폭 상위 15일 ===")
    print(cmp_df.sort_values('delta', ascending=False).head(15))
    print("\n=== 최저 15일 개선 현황 ===")
    print(cmp_df.sort_values('before').head(15))

    # ----- 자동 skip 비율 게이트 -----
    skip_pct = len(auto_skipped_dates) / len(all_dates) if all_dates else 0.0
    feasible = skip_pct <= 0.8
    if args.auto_skip_unresolved:
        print(f"\n자동 skip 일자: {len(auto_skipped_dates)}/{len(all_dates)}일 ({skip_pct*100:.1f}%)")
        if not feasible:
            print("[채택 불가] 자동 skip 비율이 80%를 초과했습니다 — 이 편명 조합은 채택하지 않습니다.")

    # ----- 요약 JSON (배치 탐색 결과 취합용, 저장 성공 여부와 무관하게 항상 기록) -----
    if args.summary_json:
        summary = {
            'cancel': cancel_fltnos,
            'total_dates': len(all_dates),
            'auto_skipped_dates': len(auto_skipped_dates),
            'skip_pct': round(skip_pct, 4),
            'feasible': feasible,
            'domestic_before_rate': dom_orig[2],
            'domestic_after_rate': dom_final[2],
            'domestic_delta_pp': (
                round(dom_final[2] - dom_orig[2], 2)
                if dom_orig[2] is not None and dom_final[2] is not None else None
            ),
            'domestic_before_n': dom_orig[0],
            'domestic_after_n': dom_final[0],
            'new_errors_remaining': len(new_errors),
            'new_curfew_remaining': len(new_curfew),
            'elapsed_sec': round(time.time() - t0, 1),
        }
        summary_path = Path(args.summary_json)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"\n요약 JSON 저장: {summary_path}")

    # ----- 저장 (안전장치: 비운항으로 생긴 신규 오류/curfew 위반이 남아있으면 절대 저장하지 않는다) -----
    if new_errors or new_curfew:
        print(f"\n[중단] 비운항으로 인한 신규 연결 오류 {len(new_errors)}건, 신규 curfew 위반 "
              f"{len(new_curfew)}건이 해결되지 않았습니다 — 저장하지 않습니다. 위 목록을 확인해 수동 조정이 필요합니다.")
        sys.exit(1)

    if not feasible:
        sys.exit(1)

    if args.no_save:
        print("\n[--no-save] 저장을 건너뜁니다(탐색 모드).")
        return

    new_id = uuid.uuid4().hex
    pkl_path = SCENARIO_DIR / f'{new_id}.pkl'
    json_path = SCENARIO_DIR / f'{new_id}.json'

    with open(pkl_path, 'wb') as f:
        pickle.dump({'original_df': original_df, 'current_df': df_noext}, f)

    dates_series = pd.to_datetime(df_noext['Sch_date_KST']).dt.date
    meta = {
        'name': args.name,
        'saved_at': datetime.now().isoformat(timespec='seconds'),
        'rows': len(df_noext),
        'date_range': [str(dates_series.min()), str(dates_series.max())],
        'filters': {'date': '', 'airline': '', 'tof': [], 'aircraft': 'domestic'},
    }
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)

    print(f"\n저장 완료: id={new_id}")
    print(meta)
    print(f"\n총 소요시간: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
