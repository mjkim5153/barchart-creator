/**
 * saveload.js — 시나리오 저장/불러오기 모달 제어
 *
 * 저장은 서버의 현재 상태(_original_df/_current_df)를 그대로 로컬 파일(data/scenarios/)에
 * 스냅샷으로 남기고, 불러오기는 그 스냅샷으로 서버 상태를 통째로 교체한다(app.py의
 * /api/scenario-save 계열 참고). 정시율 분석(실적)은 항상 _original_df 기준이므로, 이
 * 파일에서 필터 값만 복원하고 실적 계산 로직에는 관여하지 않는다.
 */

const saveLoadModal = document.getElementById('save-load-modal');

function openSaveLoadModal() {
  saveLoadModal.classList.remove('hidden');
  renderScenarioSaveList();
}

function closeSaveLoadModal() {
  saveLoadModal.classList.add('hidden');
}

document.getElementById('save-load-btn').addEventListener('click', openSaveLoadModal);
document.getElementById('save-load-modal-close').addEventListener('click', closeSaveLoadModal);
saveLoadModal.addEventListener('click', (event) => {
  if (event.target === saveLoadModal) closeSaveLoadModal();
});

// ----- 탭 전환 (scenario-modal의 .modal-tab-btn과 클래스를 분리해 서로 간섭하지 않게 함) -----

document.querySelectorAll('.sl-tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.slTab;
    document.querySelectorAll('.sl-tab-btn').forEach(b => b.classList.toggle('active', b === btn));
    document.querySelectorAll('.sl-tab-panel').forEach(panel => {
      panel.classList.toggle('hidden', panel.dataset.slTabPanel !== tab);
    });
    if (tab === 'load') renderScenarioSaveList();
  });
});

// ----- 저장 -----

document.getElementById('scenario-save-apply-btn').addEventListener('click', async () => {
  const input = document.getElementById('scenario-save-name-input');
  const name = input.value.trim();
  if (!name) {
    showError('저장 이름을 입력하세요.');
    return;
  }
  const filters = {
    date: getQueryDate(),
    airline: getSelectedAirline(),
    tof: getSelectedTofList(),
    aircraft: getSelectedAircraftFilter(),
  };
  try {
    showLoading('저장 중...');
    const result = await saveScenario(name, filters);
    document.getElementById('scenario-save-result').innerHTML =
      `<p>"${result.name}" 저장 완료 (${result.rows}행, ${result.saved_at})</p>`;
    input.value = '';
    hideLoading('저장 완료');
  } catch (e) {
    showError(e.message);
  }
});

// ----- 불러오기 목록 -----

function formatSlRow(item) {
  const dateRange = (item.date_range && item.date_range.length === 2)
    ? `${item.date_range[0]}${item.date_range[0] !== item.date_range[1] ? ' ~ ' + item.date_range[1] : ''}`
    : '-';
  return `<tr>
    <td>${item.name}</td>
    <td>${item.saved_at}</td>
    <td>${dateRange}</td>
    <td>${item.rows}</td>
    <td class="sl-actions">
      <button class="btn-sm" data-sl-load="${item.id}">불러오기</button>
      <button class="btn-sm" data-sl-delete="${item.id}">삭제</button>
    </td>
  </tr>`;
}

async function renderScenarioSaveList() {
  const container = document.getElementById('scenario-save-list');
  try {
    const items = await fetchScenarioSaves();
    if (items.length === 0) {
      container.innerHTML = '<p class="sl-save-empty">저장된 시나리오가 없습니다.</p>';
      return;
    }
    container.innerHTML = `<table>
      <thead><tr><th>이름</th><th>저장시각</th><th>날짜</th><th>행수</th><th>작업</th></tr></thead>
      <tbody>${items.map(formatSlRow).join('')}</tbody>
    </table>`;
    container.querySelectorAll('[data-sl-load]').forEach(btn => {
      btn.addEventListener('click', () => handleLoadScenarioSave(btn.dataset.slLoad));
    });
    container.querySelectorAll('[data-sl-delete]').forEach(btn => {
      btn.addEventListener('click', () => handleDeleteScenarioSave(btn.dataset.slDelete));
    });
  } catch (e) {
    showError(e.message);
  }
}

// ----- 불러오기 적용 -----

async function handleLoadScenarioSave(id) {
  if (!confirm('현재 화면의 바차트/시나리오 상태가 저장 시점으로 교체됩니다. 계속하시겠습니까?')) {
    return;
  }
  try {
    showLoading('불러오는 중...');
    const result = await loadScenarioSave(id);
    closeSaveLoadModal();
    await restoreFiltersAndRefresh(result.filters, result.dates || []);
    hideLoading(`불러오기 완료 (${result.rows}행)`);
  } catch (e) {
    showError(e.message);
  }
}

// 불러온 시나리오의 저장 시점 필터(조회일/항공사/TOF/기재)를 화면에 복원한 뒤 재조회.
// loadChartsAndSummary()가 항공사/TOF 드롭다운을 서버 메타데이터로 다시 채우므로, 그 이후에
// 값을 덮어써야 복원한 선택이 유지된다.
async function restoreFiltersAndRefresh(filters, dates) {
  if (dates.length > 0) {
    const wanted = filters && filters.date && dates.includes(filters.date) ? filters.date : dates[0];
    setQueryDateRestrictedSelect(dates, wanted);
  }

  await loadChartsAndSummary();

  if (filters) {
    const airlineSel = document.getElementById('airline-select');
    if (filters.airline && Array.from(airlineSel.options).some(o => o.value === filters.airline)) {
      airlineSel.value = filters.airline;
    }
    if (Array.isArray(filters.tof)) {
      const tofSet = new Set(filters.tof);
      document.querySelectorAll('#tof-container input[data-tof]').forEach(cb => {
        cb.checked = tofSet.has(cb.dataset.tof);
      });
      const allCb = document.getElementById('tof-all');
      if (allCb) allCb.checked = tofSet.size === 0;
    }
    if (filters.aircraft) {
      document.getElementById('aircraft-filter').value = filters.aircraft;
    }
    await refreshBarchart();
  }
}

// ----- 삭제 -----

async function handleDeleteScenarioSave(id) {
  if (!confirm('이 저장을 삭제하시겠습니까? 되돌릴 수 없습니다.')) return;
  try {
    await deleteScenarioSave(id);
    await renderScenarioSaveList();
  } catch (e) {
    showError(e.message);
  }
}
