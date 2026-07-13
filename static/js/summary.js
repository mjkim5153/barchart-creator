/**
 * summary.js — 좌측 통계 패널(정시율 분석) 렌더링
 *
 * 정시율 분석(실적): _original_df(크롤링/업로드 직후 원본) 기준, 시나리오 변경 미반영
 * 정시율 분석(시나리오): _current_df 기준, 비운항/재배정/드래그 등 모든 변경 반영
 * 두 표는 상단 5개 필터(날짜/기재/TOF/NAT/지연기준)를 공유한다.
 */

let _ontimeRecordsActual = [];
let _ontimeRecordsScenario = [];

// /api/ontime 응답을 캐시하고 필터 옵션(날짜/TOF/NAT)을 데이터 기반으로 채운 뒤 두 표를 렌더링
function renderOntimeTable(data) {
  _ontimeRecordsScenario = (data && data.records) || [];
  _ontimeRecordsActual = (data && data.baseline_records) || [];
  populateOntimeFilterOptions();
  recomputeOntimeTable();
}

function populateOntimeFilterOptions() {
  const dateSel = document.getElementById('ontime-date-filter');
  const tofSel = document.getElementById('ontime-tof-filter');
  const natSel = document.getElementById('ontime-nat-filter');

  // 실적(원본) 레코드 기준으로 옵션 산출 — 시나리오에서 비운항 처리되어 해당 편이
  // _ontimeRecordsScenario에서 사라져도 실적 쪽엔 남아있으므로 옵션이 사라지지 않는다.
  const source = _ontimeRecordsActual.length ? _ontimeRecordsActual : _ontimeRecordsScenario;

  const dates = Array.from(new Set(source.map(r => r.date))).sort();
  const tofs = Array.from(new Set(source.map(r => r.tof).filter(v => v))).sort();
  const nats = Array.from(new Set(source.map(r => r.nat).filter(v => v))).sort();

  // preferredDefault: 아직 사용자가 다른 값을 선택하지 않은 상태(현재값 'all')일 때
  // 우선 적용할 기본값 — 목록에 존재할 때만 적용, 없으면 '전체' 유지
  const fillSelect = (sel, values, preferredDefault) => {
    const current = sel.value;
    sel.innerHTML = '<option value="all">전체</option>';
    values.forEach(v => {
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = v;
      sel.appendChild(opt);
    });
    if (current !== 'all' && values.includes(current)) {
      sel.value = current;
    } else if (preferredDefault && values.includes(preferredDefault)) {
      sel.value = preferredDefault;
    } else {
      sel.value = 'all';
    }
  };

  fillSelect(dateSel, dates);
  fillSelect(tofSel, tofs);
  fillSelect(natSel, nats, '여객');
}

// 5개 필터(날짜/기재/TOF/NAT/지연기준) 현재값을 한 번만 읽어 실적/시나리오 두 표를 각각 재계산
// (서버 재조회 없이 클라이언트에서만 처리)
function recomputeOntimeTable() {
  const filters = {
    dateFilter: document.getElementById('ontime-date-filter').value,
    aircraftFilter: document.getElementById('ontime-aircraft-filter').value,
    tofFilter: document.getElementById('ontime-tof-filter').value,
    natFilter: document.getElementById('ontime-nat-filter').value,
    threshold: Number(document.getElementById('ontime-delay-threshold').value),
  };

  _renderOntimeTableInto(_ontimeRecordsActual, 'ontime-table-actual', filters);
  _renderOntimeTableInto(_ontimeRecordsScenario, 'ontime-table-scenario', filters);
}

// records를 filters 기준으로 필터링/집계해 containerId 엘리먼트에 표를 그린다
function _renderOntimeTableInto(records, containerId, filters) {
  const container = document.getElementById(containerId);
  const { dateFilter, aircraftFilter, tofFilter, natFilter, threshold } = filters;

  if (!records.length) {
    container.innerHTML = '<p style="color:#94a3b8;font-size:11px">데이터 없음</p>';
    return;
  }

  const filtered = records.filter(r => {
    if (dateFilter !== 'all' && r.date !== dateFilter) return false;
    if (aircraftFilter === 'icn' && !r.icn) return false;
    if (aircraftFilter === 'domestic' && !r.domestic) return false;
    if (tofFilter !== 'all' && r.tof !== tofFilter) return false;
    if (natFilter !== 'all' && r.nat !== natFilter) return false;
    return true;
  });

  if (!filtered.length) {
    container.innerHTML = '<p style="color:#94a3b8;font-size:11px">데이터 없음</p>';
    return;
  }

  const byDate = {};
  filtered.forEach(r => {
    if (!byDate[r.date]) byDate[r.date] = { total: 0, delayed: 0 };
    byDate[r.date].total += 1;
    if (r.delay_min !== null && r.delay_min > threshold) byDate[r.date].delayed += 1;
  });

  const rows = Object.entries(byDate)
    .map(([date, v]) => ({
      date,
      total: v.total,
      delayed: v.delayed,
      rate: v.total > 0 ? Math.round((1 - v.delayed / v.total) * 1000) / 10 : 0,
    }))
    .sort((a, b) => a.date.localeCompare(b.date));

  // 날짜 필터가 '전체'일 때만 기간 전체 합산 행을 첫 레코드로 추가 (단일 날짜 선택 시엔 중복이라 생략)
  if (dateFilter === 'all' && rows.length > 0) {
    const totalCount = filtered.length;
    const delayedCount = filtered.filter(r => r.delay_min !== null && r.delay_min > threshold).length;
    rows.unshift({
      date: '누적',
      total: totalCount,
      delayed: delayedCount,
      rate: totalCount > 0 ? Math.round((1 - delayedCount / totalCount) * 1000) / 10 : 0,
    });
  }

  const table = document.createElement('table');
  const thead = table.createTHead();
  const hRow = thead.insertRow();
  ['날짜', '운항편수', '지연편수', '정시율'].forEach(h => {
    const th = document.createElement('th');
    th.textContent = h;
    hRow.appendChild(th);
  });

  const tbody = table.createTBody();
  rows.forEach(r => {
    const tr = tbody.insertRow();
    if (r.date === '누적') tr.classList.add('ontime-row-total');
    [r.date, `${r.total}`, `${r.delayed}`, `${r.rate}%`].forEach(v => {
      const td = tr.insertCell();
      td.textContent = v;
    });
  });

  container.innerHTML = '';
  container.appendChild(table);

  const infoP = document.createElement('p');
  infoP.className = 'data-info-text';
  infoP.textContent = `※ Status≠CNL, Bt_idx=Y, RO/RI 존재, D_OPER=Y 편만 집계 | 지연기준: ${threshold}분 초과`;
  container.appendChild(infoP);
}
