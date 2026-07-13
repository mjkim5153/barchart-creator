/**
 * main.js — 앱 초기화 및 이벤트 연결
 */

// 기본 날짜: 어제 (자유 입력 모드)
(function setDefaultDates() {
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const yyyy = yesterday.getFullYear();
  const mm = String(yesterday.getMonth() + 1).padStart(2, '0');
  const dd = String(yesterday.getDate()).padStart(2, '0');
  const dateStr = `${yyyy}-${mm}-${dd}`;
  setQueryDateFreeInput(dateStr);
})();

const searchBtn = document.getElementById('search-btn');
const uploadInput = document.getElementById('upload-input');
const spinner = document.getElementById('loading-spinner');
const statusMsg = document.getElementById('status-msg');
const panelToggleBtn = document.getElementById('panel-toggle-btn');
const mainContent = document.getElementById('main-content');

function showLoading(msg) {
  spinner.classList.remove('hidden');
  statusMsg.textContent = msg || '';
}

function hideLoading(msg) {
  spinner.classList.add('hidden');
  statusMsg.textContent = msg || '';
}

function showError(msg) {
  spinner.classList.add('hidden');
  statusMsg.style.color = '#fca5a5';
  statusMsg.textContent = `오류: ${msg}`;
  setTimeout(() => { statusMsg.style.color = ''; }, 3000);
}

// RO_UTC/RI_UTC 결측 편 경고 배너 (STD/STA 폴백 없이 명시적으로 표출)
function renderRoRiWarning(missingList) {
  const banner = document.getElementById('ro-ri-warning');
  if (!missingList || missingList.length === 0) {
    banner.classList.add('hidden');
    return;
  }
  const title = banner.querySelector('.ro-ri-warning-title');
  const list = banner.querySelector('.ro-ri-warning-list');
  title.textContent = `RO/RI 실적 데이터 없음 (${missingList.length}건) — 아래 편은 바차트에 표출되지 않습니다`;
  list.innerHTML = missingList
    .map(m => `<li>${m.fltno} (${m.acno || 'CANCEL'}): ${m.missing} 없음</li>`)
    .join('');
  banner.classList.remove('hidden');
}

// ontime 데이터는 airline/tof/date 필터와 무관하게 항상 동일하므로(서버도 캐싱함,
// app.py::_rebuild_ontime_cache), 데이터셋이 실제로 바뀌는 시점(업로드/크롤링/기번
// 재배정)에만 새로 받아오고, 항공사/TOF/기재 필터·조회일 변경 시에는 이 캐시를
// 재사용해 불필요한 서버 재요청(및 서버측 재계산)을 피한다.
let cachedOntimeData = null;
let cachedBarchartData = null;

// 캐시된 barchartData에 기재 필터만 다시 적용해 렌더링 (서버 재요청 없음)
function rerenderFromCache() {
  if (!cachedBarchartData) return;
  const aircraftFilter = getSelectedAircraftFilter();
  const filteredData = filterAircraftByType(cachedBarchartData, aircraftFilter);
  renderBarchart(filteredData);
  renderRoRiWarning(filteredData.missing_ro_ri);
  hideLoading(`항공기 ${filteredData.aircraft.length}대 표출`);
}

// 메타데이터 로드 후 필터 UI 갱신 + 차트/요약 렌더링 (데이터셋 변경: barchart+ontime 모두 재조회)
async function loadChartsAndSummary() {
  try {
    const [meta] = await Promise.all([fetchMetadata()]);
    populateAirlineSelect(meta.airlines);
    populateTofCheckboxes(meta.tof);
    populateScenarioFltnoList(meta.fltnos || []);

    const airline = getSelectedAirline();
    const tofList = getSelectedTofList();
    const date = getQueryDate();

    showLoading('차트 로딩 중...');
    const [barchartData, ontimeData] = await Promise.all([
      fetchBarchartData(airline, tofList, date),
      fetchOntimeData(),
    ]);
    cachedBarchartData = barchartData;
    cachedOntimeData = ontimeData;

    renderOntimeTable(cachedOntimeData);
    rerenderFromCache();
  } catch (e) {
    showError(e.message);
  }
}

// 항공사/TOF/조회일 필터만 변경 시 — barchart만 재조회, ontime은 캐시 재사용
async function refreshBarchart() {
  const airline = getSelectedAirline();
  const tofList = getSelectedTofList();
  const date = getQueryDate();
  try {
    showLoading('필터 적용 중...');
    cachedBarchartData = await fetchBarchartData(airline, tofList, date);
    rerenderFromCache();
  } catch (e) {
    showError(e.message);
  }
}

// 기번 재배정 등, 항공사/TOF 목록(메타데이터) 자체는 안 바뀌지만 barchart+ontime
// 내용이 바뀌는 경우 — 메타데이터는 재조회하지 않아 현재 필터 선택을 유지한다.
async function refreshBarchartAndOntime() {
  const airline = getSelectedAirline();
  const tofList = getSelectedTofList();
  const date = getQueryDate();
  try {
    showLoading('데이터 갱신 중...');
    const [barchartData, ontimeData] = await Promise.all([
      fetchBarchartData(airline, tofList, date),
      fetchOntimeData(),
    ]);
    cachedBarchartData = barchartData;
    cachedOntimeData = ontimeData;
    renderOntimeTable(cachedOntimeData);
    rerenderFromCache();
  } catch (e) {
    showError(e.message);
  }
}

// 기번(Acno) 드래그 재배정 — barchart.js에서 드롭 시 호출 (데이터셋 변경: barchart+ontime 모두 재조회)
async function reassignAcno(rowId, newAcno) {
  try {
    showLoading('기번 변경 적용 중...');
    const result = await updateAcno(rowId, newAcno);
    hideLoading(`기번 변경 완료: ${result.old_acno} → ${result.new_acno}`);
    await refreshBarchartAndOntime();
  } catch (e) {
    showError(e.message);
  }
}

// 검색 (크롤링)
searchBtn.addEventListener('click', async () => {
  const queryDate = document.getElementById('query-date-input').value;
  if (!queryDate) { showError('조회일을 선택하세요.'); return; }
  try {
    showLoading('데이터 수집 중... (수 분 소요될 수 있음)');
    await crawlData(queryDate, queryDate);
    // 크롤링 데이터는 항상 단일 날짜이므로 업로드로 인한 제한(select) 모드를 해제하고
    // 다음 조회를 위해 자유 입력 상태로 되돌린다.
    setQueryDateFreeInput(queryDate);
    hideLoading('수집 완료');
    await loadChartsAndSummary();
  } catch (e) {
    showError(e.message);
  }
});

// 엑셀 업로드
uploadInput.addEventListener('change', async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    showLoading(`"${file.name}" 업로드 중...`);
    const result = await uploadExcel(file);
    const dates = result.dates || [];
    if (dates.length > 0) {
      // 백엔드가 오름차순 정렬해서 내려주므로 dates[0]이 가장 이른 날짜
      setQueryDateRestrictedSelect(dates, dates[0]);
      if (dates.length > 1) {
        hideLoading(`업로드 완료 (${result.rows}행) — 여러 날짜 포함, 가장 이른 날짜(${dates[0]})로 조회`);
      } else {
        hideLoading(`업로드 완료 (${result.rows}행)`);
      }
    } else {
      hideLoading(`업로드 완료 (${result.rows}행)`);
    }
    await loadChartsAndSummary();
  } catch (e) {
    showError(e.message);
  }
  uploadInput.value = '';
});

// 항공사 필터 변경
document.getElementById('airline-select').addEventListener('change', refreshBarchart);

// TOF 필터 변경 (이벤트 위임)
document.getElementById('tof-container').addEventListener('change', refreshBarchart);

// #7 기재 필터 변경 (서버 재요청 없이 캐시된 barchart 데이터에 클라이언트 필터만 재적용)
document.getElementById('aircraft-filter').addEventListener('change', rerenderFromCache);

// 조회일 change 리스너는 setQueryDateFreeInput/setQueryDateRestrictedSelect가 교체할 때마다
// 새 엘리먼트에 직접 재바인딩하므로(filters.js), 여기서 별도로 붙이지 않는다(중복 바인딩 방지).

// 업로드로 제한(select)된 조회일을 자유 입력으로 되돌리기 (새 날짜 크롤링 등)
document.getElementById('query-date-free-btn').addEventListener('click', () => {
  setQueryDateFreeInput(getQueryDate());
});

// 정시율 분석 필터 변경 (서버 재조회 없이 클라이언트에서 재계산)
['ontime-date-filter', 'ontime-aircraft-filter', 'ontime-tof-filter', 'ontime-nat-filter', 'ontime-delay-threshold']
  .forEach(id => document.getElementById(id).addEventListener('change', recomputeOntimeTable));

// 엑셀 다운로드
document.getElementById('download-btn').addEventListener('click', () => {
  const airline = getSelectedAirline();
  const tofList = getSelectedTofList();
  const date = getQueryDate();
  const params = new URLSearchParams();
  if (airline) params.set('airline', airline);
  if (tofList.length) params.set('tof', tofList.join(','));
  if (date) params.set('date', date);
  window.location.href = `/api/download?${params}`;
});

// 바차트 이미지(JPEG) 저장
const exportJpegBtn = document.getElementById('export-jpeg-btn');
exportJpegBtn.addEventListener('click', () => {
  exportJpegBtn.disabled = true;
  showLoading('이미지 생성 중...');
  exportBarchartAsJpeg(() => {
    exportJpegBtn.disabled = false;
    hideLoading();
  });
});

// 통계 패널 표시/숨기기
const SUMMARY_PANEL_STORAGE_KEY = 'summaryPanelCollapsed';

function applyPanelState(collapsed) {
  mainContent.classList.toggle('summary-collapsed', collapsed);
  panelToggleBtn.textContent = collapsed ? '통계 패널 보이기' : '통계 패널 숨기기';
}

applyPanelState(localStorage.getItem(SUMMARY_PANEL_STORAGE_KEY) === '1');

panelToggleBtn.addEventListener('click', () => {
  const collapsed = !mainContent.classList.contains('summary-collapsed');
  applyPanelState(collapsed);
  localStorage.setItem(SUMMARY_PANEL_STORAGE_KEY, collapsed ? '1' : '0');

  // 패널 토글로 바차트 컨테이너 폭이 바뀌므로 마지막 데이터로 재렌더링
  const data = getCurrentBarchartData();
  if (data) renderBarchart(data);
});

// 초기 안내
hideLoading('날짜 선택 후 "검색" 또는 엑셀 업로드로 시작하세요.');
