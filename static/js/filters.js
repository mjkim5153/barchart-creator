/**
 * filters.js — 필터 드롭다운 UI 관리
 */

const KOREAN_AIRPORTS_JS = new Set([
  'ICN', 'GMP', 'PUS', 'CJU', 'KWJ', 'CJJ', 'YNY', 'CNJ', 'MWX',
  'TAE', 'HIN', 'KUV', 'KPO', 'RSU', 'USN', 'WJU', 'CHN', 'JDG', 'JCN'
]);

// 대한항공(KAL) ICN 국제선 연결용 지선(피더) 공항 — 현재 KAL만 해당 확인됨, 향후 타사/타 공항 확인 시 확장
const KAL_FEEDER_AIRPORTS_JS = new Set(['PUS', 'TAE']);

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
 * - domestic: 국내기재 (항공편 중 1개라도 양쪽 모두 한국공항이면서 ICN만이 아닌 경우,
 *   또는 그날 ICN을 전혀 경유하지 않으면서 국내 비-ICN 공항 기점 국제선을 운항하는 경우)
 *
 * 예외 1: KAL 지선편(PUS/TAE↔ICN, NAT=PAX) 이후 같은 기재의 나머지 모든 편이
 * 국제선이면(ICN 경유 여부 무관 — PUS/TAE발 국제선도 포함), 그 지선편은 국내기재
 * 판정에서 제외한다 (data_processor.py의 _aircraft_type_acno_sets와 동일 규칙).
 *
 * 예외 2: 그날 ICN을 전혀 경유하지 않는 기재가 국내 비-ICN 공항(GMP/PUS 등)을
 * 기점/종점으로 국제선을 운항하면(예: GMP-KIX, PUS-PVG), 그 기재는 국내기재로
 * 분류한다 — ICN 기반이 아니라 지방공항을 거점으로 하는 기재이기 때문.
 */
function isKalFeederFlight(fl) {
  const airlineCode = fl.fltno.slice(0, 3);
  const isFeederRoute =
    (fl.depstn === 'ICN' && KAL_FEEDER_AIRPORTS_JS.has(fl.arrstn)) ||
    (fl.arrstn === 'ICN' && KAL_FEEDER_AIRPORTS_JS.has(fl.depstn));
  return airlineCode === 'KAL' && isFeederRoute && fl.nat === 'PAX';
}

function touchesICN(fl) {
  return fl.depstn === 'ICN' || fl.arrstn === 'ICN';
}

function isDomesticTypeFlight(fl, allFlights) {
  const depKR = KOREAN_AIRPORTS_JS.has(fl.depstn);
  const arrKR = KOREAN_AIRPORTS_JS.has(fl.arrstn);
  const isICNOnly = (fl.depstn === 'ICN' && fl.arrstn === 'ICN');

  if (depKR && arrKR && !isICNOnly) {
    if (isKalFeederFlight(fl)) {
      // 같은 기재의 지선편을 전부 제외한 나머지 편이 모두 국제선이면 예외 적용
      const others = allFlights.filter(o => !isKalFeederFlight(o));
      if (others.length > 0 && others.every(o => o.domestic_intl === '국제선')) {
        return false;
      }
    }
    return true;
  }

  // 지방공항 기반 국제선: 그날 ICN을 전혀 경유하지 않는 기재의 국내 비-ICN 공항 기점 국제선
  const noIcnAcno = !allFlights.some(touchesICN);
  if (noIcnAcno) {
    const depKRnonICN = depKR && fl.depstn !== 'ICN';
    const arrKRnonICN = arrKR && fl.arrstn !== 'ICN';
    if ((depKRnonICN && !arrKR) || (arrKRnonICN && !depKR)) {
      return true;
    }
  }

  return false;
}

function filterAircraftByType(data, filterType) {
  if (filterType === 'all') return data;

  const filtered = data.aircraft.filter(ac => {
    if (filterType === 'icn') {
      return ac.flights.some(fl =>
        fl.depstn === 'ICN' || fl.arrstn === 'ICN'
      );
    }
    if (filterType === 'domestic') {
      return ac.flights.some(fl => isDomesticTypeFlight(fl, ac.flights));
    }
    return true;
  });

  return { aircraft: filtered };
}
