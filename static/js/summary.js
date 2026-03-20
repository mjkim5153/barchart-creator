/**
 * summary.js — 좌측 요약 패널 렌더링
 */

let _summaryData = null;

function renderSummary(data) {
  _summaryData = data;
  renderOperationSummary(data.operation_summary || {});
  renderGTTable(data.gt_table || {});
}

// #9 가동률 → 국적사 전체 테이블 + 날짜 필터 + 가동률 순위
function renderOperationSummary(summary) {
  const container = document.getElementById('operation-rate-table');
  const rows = summary.rows || [];
  const availableDates = summary.available_dates || [];
  const dailyData = summary.daily || {};

  if (!rows.length) {
    container.innerHTML = '<p style="color:#94a3b8;font-size:11px">데이터 없음</p>';
    return;
  }

  container.innerHTML = '';

  // 날짜 필터 드롭다운
  if (availableDates.length > 0) {
    const filterDiv = document.createElement('div');
    filterDiv.className = 'op-date-filter';
    const sel = document.createElement('select');
    sel.id = 'op-date-filter';

    const allOpt = document.createElement('option');
    allOpt.value = 'all';
    allOpt.textContent = '전체 기간';
    sel.appendChild(allOpt);

    availableDates.forEach(d => {
      const opt = document.createElement('option');
      opt.value = d;
      opt.textContent = d;
      sel.appendChild(opt);
    });

    sel.addEventListener('change', () => {
      renderOpTable(sel.value === 'all' ? rows : (dailyData[sel.value] || []), container.querySelector('.op-table-wrap'));
    });

    filterDiv.appendChild(sel);
    container.appendChild(filterDiv);
  }

  const tableWrap = document.createElement('div');
  tableWrap.className = 'op-table-wrap';
  container.appendChild(tableWrap);

  renderOpTable(rows, tableWrap);
}

function renderOpTable(rows, wrap) {
  if (!rows.length) {
    wrap.innerHTML = '<p style="color:#94a3b8;font-size:11px">데이터 없음</p>';
    return;
  }

  // 가동시간 오름차순 정렬 (낮은 가동시간 = 높은 순위)
  const sorted = [...rows].sort((a, b) => b.hours_per_aircraft - a.hours_per_aircraft);

  const table = document.createElement('table');
  const thead = table.createTHead();
  const hRow = thead.insertRow();
  ['순위', '국적사', '평균기재수', '계획BT(분)', '가동시간(h)'].forEach(h => {
    const th = document.createElement('th');
    th.textContent = h;
    hRow.appendChild(th);
  });

  const tbody = table.createTBody();
  sorted.forEach((r, idx) => {
    const tr = tbody.insertRow();
    [`${idx + 1}`, r.airline, `${r.operating_aircraft}`, r.planned_bt.toLocaleString(), `${r.hours_per_aircraft}`].forEach(v => {
      const td = tr.insertCell();
      td.textContent = v;
    });
  });

  wrap.innerHTML = '';
  wrap.appendChild(table);
}

// #11 GT 분석 테이블
function renderGTTable(gtTable) {
  const container = document.getElementById('gt-histogram');
  const routeType = document.getElementById('gt-route-type').value;
  const gradeFilter = document.getElementById('gt-grade-filter').value;

  container.innerHTML = '';

  const routeData = gtTable[routeType] || {};
  const airlines = Object.keys(routeData);

  if (!airlines.length) {
    container.innerHTML = '<p style="color:#94a3b8;font-size:11px">데이터 없음</p>';
    return;
  }

  // 구간 헤더
  const binLabels = routeType === 'domestic'
    ? ['<30', '30', '35', '40', '45', '50', '>50']
    : ['<50', '50', '55', '60', '65', '70', '>70'];

  airlines.forEach(al => {
    const alData = routeData[al];
    if (!alData) return;

    const gradeData = alData.grades || alData;
    const gradeFlights = alData.grade_flights || {};

    const selectedGrade = gradeFilter;
    const data = gradeData[selectedGrade];
    if (!data) return;

    // 선택된 등급에 해당하는 운항편수
    const flightCount = gradeFlights[selectedGrade] || 0;

    const block = document.createElement('div');
    block.className = 'gt-table-block';

    const title = document.createElement('h4');
    const gradeLabel = selectedGrade === '전체' ? '전체' : selectedGrade + '급';
    title.textContent = `${al}(${gradeLabel}) - ${flightCount}편`;
    block.appendChild(title);

    const table = document.createElement('table');
    table.className = 'gt-analysis-table';

    // 헤더
    const thead = table.createTHead();
    const hRow = thead.insertRow();
    const thEmpty = document.createElement('th');
    thEmpty.textContent = 'GT구간';
    hRow.appendChild(thEmpty);
    binLabels.forEach(label => {
      const th = document.createElement('th');
      th.textContent = label;
      hRow.appendChild(th);
    });

    // 비중 행
    const tbody = table.createTBody();
    const pctRow = tbody.insertRow();
    const pctLabel = pctRow.insertCell();
    pctLabel.textContent = '비중(%)';
    pctLabel.style.fontWeight = '600';

    binLabels.forEach(bin => {
      const td = pctRow.insertCell();
      const binData = data[bin];
      if (binData) {
        td.textContent = `${binData.pct}%`;
        td.title = `${binData.count}편`;
        td.style.cursor = 'default';
        // 비중 높을수록 진한 배경
        if (binData.pct >= 30) {
          td.style.background = '#fecaca';
        } else if (binData.pct >= 15) {
          td.style.background = '#fef3c7';
        }
      } else {
        td.textContent = '-';
      }
    });

    block.appendChild(table);
    container.appendChild(block);
  });
}

// GT 필터 변경 시 테이블만 다시 렌더링
function refreshGTTable() {
  if (_summaryData && _summaryData.gt_table) {
    renderGTTable(_summaryData.gt_table);
  }
}

// (3) 노선별 BT 통계 검색
function searchRouteStats(route) {
  const container = document.getElementById('route-stats-table');
  if (!_summaryData) {
    container.innerHTML = '<p style="color:#94a3b8;font-size:11px">데이터 없음</p>';
    return;
  }

  const routeStats = _summaryData.route_stats || {};
  const key = route.toUpperCase().trim();
  const match = routeStats[key];

  if (!match) {
    container.innerHTML = `<p style="color:#94a3b8;font-size:11px">"${key}" 노선 없음</p>`;
    return;
  }

  const table = document.createElement('table');
  const thead = table.createTHead();
  const hRow = thead.insertRow();
  ['항공사', '평균BT', '최장BT', '최단BT', '횟수'].forEach(h => {
    const th = document.createElement('th');
    th.textContent = h;
    hRow.appendChild(th);
  });

  const tbody = table.createTBody();
  Object.entries(match).forEach(([al, s]) => {
    const tr = tbody.insertRow();
    [al, `${s.avg}분`, `${s.max}분`, `${s.min}분`, `${s.count}회`].forEach(v => {
      const td = tr.insertCell();
      td.textContent = v;
    });
  });

  container.innerHTML = '';
  container.appendChild(table);
}
