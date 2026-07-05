/**
 * main.js — 앱 초기화 및 이벤트 연결
 */

// 기본 날짜: 어제
(function setDefaultDates() {
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const yyyy = yesterday.getFullYear();
  const mm = String(yesterday.getMonth() + 1).padStart(2, '0');
  const dd = String(yesterday.getDate()).padStart(2, '0');
  const dateStr = `${yyyy}-${mm}-${dd}`;
  document.getElementById('start-date-input').value = dateStr;
  document.getElementById('end-date-input').value = dateStr;
})();

const searchBtn = document.getElementById('search-btn');
const uploadInput = document.getElementById('upload-input');
const spinner = document.getElementById('loading-spinner');
const statusMsg = document.getElementById('status-msg');
const routeSearchBtn = document.getElementById('route-search-btn');
const routeInput = document.getElementById('route-input');
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

// 메타데이터 로드 후 필터 UI 갱신 + 차트/요약 렌더링
async function loadChartsAndSummary() {
  try {
    const [meta] = await Promise.all([fetchMetadata()]);
    populateAirlineSelect(meta.airlines);
    populateNatCheckboxes(meta.nat);

    const airline = getSelectedAirline();
    const natList = getSelectedNatList();

    showLoading('차트 로딩 중...');
    const [barchartData, summaryData] = await Promise.all([
      fetchBarchartData(airline, natList),
      fetchSummaryData(natList, airline),
    ]);

    // #7 기재 필터 적용
    const aircraftFilter = getSelectedAircraftFilter();
    const filteredData = filterAircraftByType(barchartData, aircraftFilter);

    renderBarchart(filteredData);
    renderSummary(summaryData);
    hideLoading(`항공기 ${filteredData.aircraft.length}대 표출`);
  } catch (e) {
    showError(e.message);
  }
}

// 필터만 변경 시 (재크롤링 없이 재조회)
async function refreshCharts() {
  const airline = getSelectedAirline();
  const natList = getSelectedNatList();
  try {
    showLoading('필터 적용 중...');
    const [barchartData, summaryData] = await Promise.all([
      fetchBarchartData(airline, natList),
      fetchSummaryData(natList, airline),
    ]);

    // #7 기재 필터 적용
    const aircraftFilter = getSelectedAircraftFilter();
    const filteredData = filterAircraftByType(barchartData, aircraftFilter);

    renderBarchart(filteredData);
    renderSummary(summaryData);
    hideLoading(`항공기 ${filteredData.aircraft.length}대 표출`);
  } catch (e) {
    showError(e.message);
  }
}

// 기번(Acno) 드래그 재배정 — barchart.js에서 드롭 시 호출
async function reassignAcno(rowId, newAcno) {
  try {
    showLoading('기번 변경 적용 중...');
    const result = await updateAcno(rowId, newAcno);
    hideLoading(`기번 변경 완료: ${result.old_acno} → ${result.new_acno}`);
    await refreshCharts();
  } catch (e) {
    showError(e.message);
  }
}

// 검색 (크롤링)
searchBtn.addEventListener('click', async () => {
  const startDate = document.getElementById('start-date-input').value;
  const endDate = document.getElementById('end-date-input').value;
  if (!startDate || !endDate) { showError('시작일과 종료일을 선택하세요.'); return; }
  if (startDate > endDate) { showError('시작일이 종료일보다 늦습니다.'); return; }
  try {
    showLoading('데이터 수집 중... (수 분 소요될 수 있음)');
    await crawlData(startDate, endDate);
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
    hideLoading(`업로드 완료 (${result.rows}행)`);
    await loadChartsAndSummary();
  } catch (e) {
    showError(e.message);
  }
  uploadInput.value = '';
});

// 항공사 필터 변경
document.getElementById('airline-select').addEventListener('change', refreshCharts);

// NAT 필터 변경 (이벤트 위임)
document.getElementById('nat-container').addEventListener('change', refreshCharts);

// #7 기재 필터 변경 (요약에는 영향 없이 바차트만 갱신)
document.getElementById('aircraft-filter').addEventListener('change', refreshCharts);

// #11 GT 필터 변경
document.getElementById('gt-route-type').addEventListener('change', refreshGTTable);
document.getElementById('gt-grade-filter').addEventListener('change', refreshGTTable);

// 노선 BT 검색
routeSearchBtn.addEventListener('click', () => {
  searchRouteStats(routeInput.value);
});
routeInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') searchRouteStats(routeInput.value);
});

// 엑셀 다운로드
document.getElementById('download-btn').addEventListener('click', () => {
  const airline = getSelectedAirline();
  const natList = getSelectedNatList();
  const params = new URLSearchParams();
  if (airline) params.set('airline', airline);
  if (natList.length) params.set('nat', natList.join(','));
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
