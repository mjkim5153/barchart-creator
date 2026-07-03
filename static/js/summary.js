/**
 * summary.js — 좌측 요약 패널 렌더링
 */

let _summaryData = null;

function renderSummary(data) {
  _summaryData = data;
  renderOperationSummary(data.operation_summary || {});
  renderGTTable(data.gt_table || {});
}

// 현재 선택된 필터 정보를 문자열로 반환
function getFilterInfoText() {
  const startDate = document.getElementById('start-date-input')?.value || '';
  const endDate = document.getElementById('end-date-input')?.value || '';
  const airline = (typeof getSelectedAirline === 'function') ? getSelectedAirline() : '';
  const natList = (typeof getSelectedNatList === 'function') ? getSelectedNatList() : [];

  const dateStr = startDate === endDate ? startDate : `${startDate}~${endDate}`;
  const airlineStr = airline || '전체';
  const natStr = natList.length > 0 ? natList.join(', ') : '전체';

  return `기간: ${dateStr} | 항공사: ${airlineStr} | NAT: ${natStr}`;
}

// #9 가동률 → 국적사 전체 테이블 + 날짜 필터 + 기재 필터 + 등급 필터 + 가동률 순위
function renderOperationSummary(summary) {
  const container = document.getElementById('operation-rate-table');
  const rowsByType = summary.rows || {};
  const availableDates = summary.available_dates || [];
  const dailyData = summary.daily || {};

  if (!rowsByType.all || !rowsByType.all.length) {
    container.innerHTML = '<p style="color:#94a3b8;font-size:11px">데이터 없음</p>';
    return;
  }

  container.innerHTML = '';

  // 날짜 + 기재 + 등급 필터 드롭다운 (한 행에 나란히)
  const filterDiv = document.createElement('div');
  filterDiv.className = 'op-filter-controls';

  // 날짜 필터
  const dateSel = document.createElement('select');
  dateSel.id = 'op-date-filter';
  const allOpt = document.createElement('option');
  allOpt.value = 'all';
  allOpt.textContent = '전체 기간';
  dateSel.appendChild(allOpt);
  availableDates.forEach(d => {
    const opt = document.createElement('option');
    opt.value = d;
    opt.textContent = d;
    dateSel.appendChild(opt);
  });
  filterDiv.appendChild(dateSel);

  // #신규 기재 필터 (가동률 표 전용, 바차트 상단의 기재 필터와는 무관)
  const aircraftSel = document.createElement('select');
  aircraftSel.id = 'op-aircraft-filter';
  [['all', '전체'], ['icn', '인천기재'], ['domestic', '국내기재']].forEach(([val, label]) => {
    const opt = document.createElement('option');
    opt.value = val;
    opt.textContent = label;
    aircraftSel.appendChild(opt);
  });
  filterDiv.appendChild(aircraftSel);

  // 등급 필터
  const gradeSel = document.createElement('select');
  gradeSel.id = 'op-grade-filter';
  [['전체', '전체'], ['A', 'A (소형)'], ['B', 'B (리저널)'], ['C', 'C (중형)'], ['D', 'D (대형)'], ['E', 'E (초대형)']].forEach(([val, label]) => {
    const opt = document.createElement('option');
    opt.value = val;
    opt.textContent = label;
    gradeSel.appendChild(opt);
  });
  filterDiv.appendChild(gradeSel);

  container.appendChild(filterDiv);

  const tableWrap = document.createElement('div');
  tableWrap.className = 'op-table-wrap';
  container.appendChild(tableWrap);

  let currentRows = [];
  function updateCurrentRows() {
    const baseByType = dateSel.value === 'all' ? rowsByType : (dailyData[dateSel.value] || {});
    currentRows = baseByType[aircraftSel.value] || [];
    renderOpTable(currentRows, tableWrap);
  }

  dateSel.addEventListener('change', updateCurrentRows);
  aircraftSel.addEventListener('change', updateCurrentRows);
  gradeSel.addEventListener('change', () => renderOpTable(currentRows, tableWrap));

  updateCurrentRows();

  // 데이터 출처 안내
  const infoP = document.createElement('p');
  infoP.className = 'data-info-text';
  infoP.textContent = `※ 국적사 여객기, 화물기(CGE/CGO/CGC) 제외 | ${getFilterInfoText()}`;
  container.appendChild(infoP);

  // 등급 미분류 기종 안내
  const ungraded = _summaryData && _summaryData.ungraded_actypes;
  if (ungraded && ungraded.length > 0) {
    const ungradedP = document.createElement('p');
    ungradedP.className = 'data-info-ungraded';
    const list = ungraded.map(u => `${u.Actype}(${u.count}편)`).join(', ');
    ungradedP.textContent = `※ 등급 미분류 기종: ${list} — 등급 매핑 테이블에 미등록`;
    container.appendChild(ungradedP);
  }
}

function renderOpTable(rows, wrap) {
  const gradeFilter = document.getElementById('op-grade-filter')?.value || '전체';

  // 선택된 등급에 따라 표시 데이터 결정
  const displayRows = rows.map(r => {
    if (!r.by_grade) {
      // by_grade 없는 구버전 데이터 호환
      return {
        airline: r.airline,
        aircraft_count: r.operating_aircraft,
        aircraft_ratio: null,
        planned_bt: r.planned_bt,
        hours_per_aircraft: r.hours_per_aircraft,
      };
    }
    const gd = r.by_grade[gradeFilter];
    if (!gd) return null;
    return {
      airline: r.airline,
      aircraft_count: gd.aircraft_count,
      aircraft_ratio: gradeFilter === '전체' ? null : gd.aircraft_ratio,
      planned_bt: gd.planned_bt,
      hours_per_aircraft: gd.hours_per_aircraft,
    };
  }).filter(r => r && r.aircraft_count > 0);

  if (!displayRows.length) {
    wrap.innerHTML = '<p style="color:#94a3b8;font-size:11px">데이터 없음</p>';
    return;
  }

  // 가동시간 내림차순 정렬
  const sorted = [...displayRows].sort((a, b) => b.hours_per_aircraft - a.hours_per_aircraft);

  const table = document.createElement('table');
  const thead = table.createTHead();
  const hRow = thead.insertRow();
  ['순위', '국적사', '기재수', '계획BT(분)', '가동시간(h)'].forEach(h => {
    const th = document.createElement('th');
    th.textContent = h;
    hRow.appendChild(th);
  });

  const tbody = table.createTBody();
  sorted.forEach((r, idx) => {
    const tr = tbody.insertRow();
    const acText = r.aircraft_ratio !== null
      ? `${r.aircraft_count}(${r.aircraft_ratio}%)`
      : `${r.aircraft_count}`;
    [`${idx + 1}`, r.airline, acText, r.planned_bt.toLocaleString(), `${r.hours_per_aircraft}`].forEach(v => {
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

    // 헤더 (총계 열 추가)
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
    const thTotal = document.createElement('th');
    thTotal.textContent = '총계';
    hRow.appendChild(thTotal);

    const tbody = table.createTBody();

    // 운항편 행 (툴팁 대신 명시적 행으로)
    const countRow = tbody.insertRow();
    const countLabel = countRow.insertCell();
    countLabel.textContent = '운항편';
    countLabel.style.fontWeight = '600';
    let totalCount = 0;
    binLabels.forEach(bin => {
      const td = countRow.insertCell();
      const binData = data[bin];
      const cnt = binData ? binData.count : 0;
      totalCount += cnt;
      td.textContent = cnt;
    });
    const countTotalCell = countRow.insertCell();
    countTotalCell.textContent = totalCount;
    countTotalCell.style.fontWeight = '700';

    // 비중(%) 행
    const pctRow = tbody.insertRow();
    const pctLabel = pctRow.insertCell();
    pctLabel.textContent = '비중(%)';
    pctLabel.style.fontWeight = '600';

    binLabels.forEach(bin => {
      const td = pctRow.insertCell();
      const binData = data[bin];
      if (binData) {
        td.textContent = `${binData.pct}%`;
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
    const pctTotalCell = pctRow.insertCell();
    pctTotalCell.textContent = '100%';
    pctTotalCell.style.fontWeight = '700';

    block.appendChild(table);
    container.appendChild(block);
  });

  // 데이터 출처 안내
  const infoP = document.createElement('p');
  infoP.className = 'data-info-text';
  infoP.textContent = `※ 국적사 여객기, Status≠CNL, Bt_idx=Y | ${getFilterInfoText()} | 첫편(연결편 없음)은 최대 GT구간에 포함`;
  container.appendChild(infoP);

  // 등급 미분류 기종 안내
  const ungraded = _summaryData && _summaryData.ungraded_actypes;
  if (ungraded && ungraded.length > 0) {
    const ungradedP = document.createElement('p');
    ungradedP.className = 'data-info-ungraded';
    const list = ungraded.map(u => `${u.Actype}(${u.count}편)`).join(', ');
    ungradedP.textContent = `※ 등급 미분류 기종: ${list} — 등급 매핑 테이블에 미등록`;
    container.appendChild(ungradedP);
  }
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

  // 데이터 출처 안내
  const infoP = document.createElement('p');
  infoP.className = 'data-info-text';
  infoP.textContent = `※ 국적사 전체, Status≠CNL, Bt_idx=Y | ${getFilterInfoText()}`;
  container.appendChild(infoP);
}
