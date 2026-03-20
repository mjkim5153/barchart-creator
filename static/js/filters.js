/**
 * filters.js — 필터 드롭다운 UI 관리
 */

const KOREAN_AIRPORTS_JS = new Set([
  'ICN', 'GMP', 'PUS', 'CJU', 'KWJ', 'CJJ', 'YNY', 'CNJ', 'MWX',
  'TAE', 'HIN', 'KUV', 'KPO', 'RSU', 'USN', 'WJU', 'CHN', 'JDG', 'JCN'
]);

function populateAirlineSelect(airlines) {
  const sel = document.getElementById('airline-select');
  const current = sel.value;
  sel.innerHTML = '<option value="">전체</option>';
  airlines.forEach(code => {
    const opt = document.createElement('option');
    opt.value = code;
    opt.textContent = code;
    sel.appendChild(opt);
  });
  if (airlines.includes(current)) sel.value = current;
}

function populateNatCheckboxes(natValues) {
  const container = document.getElementById('nat-container');
  const checkedSet = getCheckedNat();
  container.innerHTML = '';

  // 전체 선택 체크박스
  const allLabel = document.createElement('label');
  const allCb = document.createElement('input');
  allCb.type = 'checkbox';
  allCb.id = 'nat-all';
  allCb.checked = checkedSet.size === 0;
  allCb.addEventListener('change', () => {
    if (allCb.checked) {
      container.querySelectorAll('input[data-nat]').forEach(cb => { cb.checked = false; });
    }
  });
  allLabel.appendChild(allCb);
  allLabel.appendChild(document.createTextNode('전체'));
  container.appendChild(allLabel);

  natValues.forEach(nat => {
    const label = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.dataset.nat = nat;
    cb.checked = checkedSet.has(nat);
    cb.addEventListener('change', () => {
      const allCheck = document.getElementById('nat-all');
      if (allCheck) allCheck.checked = false;
    });
    label.appendChild(cb);
    label.appendChild(document.createTextNode(nat));
    container.appendChild(label);
  });
}

function getSelectedAirline() {
  return document.getElementById('airline-select').value;
}

function getCheckedNat() {
  const checked = new Set();
  document.querySelectorAll('#nat-container input[data-nat]:checked').forEach(cb => {
    checked.add(cb.dataset.nat);
  });
  return checked;
}

function getSelectedNatList() {
  const s = getCheckedNat();
  return s.size > 0 ? Array.from(s) : [];
}

function getSelectedAircraftFilter() {
  return document.getElementById('aircraft-filter').value;
}

/**
 * #7 기재 필터: 바차트 데이터를 기재 유형별로 필터링
 * - all: 전체
 * - icn: 인천기재 (항공편 중 1개라도 Depstn/Arrstn에 ICN 포함)
 * - domestic: 국내기재 (항공편 중 1개라도 양쪽 모두 한국공항이면서 ICN만이 아닌 경우)
 */
function filterAircraftByType(data, filterType) {
  if (filterType === 'all') return data;

  const filtered = data.aircraft.filter(ac => {
    if (filterType === 'icn') {
      return ac.flights.some(fl =>
        fl.depstn === 'ICN' || fl.arrstn === 'ICN'
      );
    }
    if (filterType === 'domestic') {
      return ac.flights.some(fl => {
        const depKR = KOREAN_AIRPORTS_JS.has(fl.depstn);
        const arrKR = KOREAN_AIRPORTS_JS.has(fl.arrstn);
        const isICNOnly = (fl.depstn === 'ICN' && fl.arrstn === 'ICN');
        return depKR && arrKR && !isICNOnly;
      });
    }
    return true;
  });

  return { aircraft: filtered };
}
