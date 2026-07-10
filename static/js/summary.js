/**
 * summary.js — 좌측 통계 패널(정시율 분석) 렌더링
 */

let _ontimeRecords = [];

// /api/ontime 응답을 캐시하고 필터 옵션(날짜/TOF/NAT)을 데이터 기반으로 채운 뒤 렌더링
function renderOntimeTable(data) {
  _ontimeRecords = (data && data.records) || [];
  populateOntimeFilterOptions();
  recomputeOntimeTable();
}

function populateOntimeFilterOptions() {
  const dateSel = document.getElementById('ontime-date-filter');
  const tofSel = document.getElementById('ontime-tof-filter');
  const natSel = document.getElementById('ontime-nat-filter');

  const dates = Array.from(new Set(_ontimeRecords.map(r => r.date))).sort();
  const tofs = Array.from(new Set(_ontimeRecords.map(r => r.tof).filter(v => v))).sort();
  const nats = Array.from(new Set(_ontimeRecords.map(r => r.nat).filter(v => v))).sort();

  const fillSelect = (sel, values) => {
    const current = sel.value;
    sel.innerHTML = '<option value="all">전체</option>';
    values.forEach(v => {
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = v;
      sel.appendChild(opt);
    });
    sel.value = (current === 'all' || values.includes(current)) ? current : 'all';
  };

  fillSelect(dateSel, dates);
  fillSelect(tofSel, tofs);
  fillSelect(natSel, nats);
}

// 5개 필터(날짜/기재/TOF/NAT/지연기준) 현재값으로 _ontimeRecords를 재계산해 표 렌더링
// (서버 재조회 없이 클라이언트에서만 처리)
function recomputeOntimeTable() {
  const container = document.getElementById('ontime-table');

  if (!_ontimeRecords.length) {
    container.innerHTML = '<p style="color:#94a3b8;font-size:11px">데이터 없음</p>';
    return;
  }

  const dateFilter = document.getElementById('ontime-date-filter').value;
  const aircraftFilter = document.getElementById('ontime-aircraft-filter').value;
  const tofFilter = document.getElementById('ontime-tof-filter').value;
  const natFilter = document.getElementById('ontime-nat-filter').value;
  const threshold = Number(document.getElementById('ontime-delay-threshold').value);

  const filtered = _ontimeRecords.filter(r => {
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
