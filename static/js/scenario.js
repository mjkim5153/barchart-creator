/**
 * scenario.js — 시나리오 모달(비운항/스케줄 조정) 제어
 */

const scenarioModal = document.getElementById('scenario-modal');
const scenarioFltnoSearch = document.getElementById('scenario-fltno-search');
const scenarioFltnoList = document.getElementById('scenario-fltno-list');

let _allScenarioFltnos = [];

function populateScenarioFltnoList(fltnos) {
  _allScenarioFltnos = fltnos || [];
  renderScenarioFltnoList(_allScenarioFltnos);
}

function renderScenarioFltnoList(fltnos) {
  const checkedSet = getSelectedScenarioFltnos();
  scenarioFltnoList.innerHTML = '';
  fltnos.forEach(fltno => {
    const label = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.dataset.fltno = fltno;
    cb.checked = checkedSet.has(fltno);
    label.appendChild(cb);
    label.appendChild(document.createTextNode(fltno));
    scenarioFltnoList.appendChild(label);
  });
}

function getSelectedScenarioFltnos() {
  const checked = new Set();
  scenarioFltnoList.querySelectorAll('input[data-fltno]:checked').forEach(cb => {
    checked.add(cb.dataset.fltno);
  });
  return checked;
}

scenarioFltnoSearch.addEventListener('input', () => {
  const keyword = scenarioFltnoSearch.value.trim().toUpperCase();
  const filtered = keyword
    ? _allScenarioFltnos.filter(f => f.toUpperCase().includes(keyword))
    : _allScenarioFltnos;
  renderScenarioFltnoList(filtered);
});

// ----- 모달 열기/닫기/탭 전환 -----

function openScenarioModal() {
  scenarioModal.classList.remove('hidden');
}

function closeScenarioModal() {
  scenarioModal.classList.add('hidden');
}

document.getElementById('scenario-btn').addEventListener('click', openScenarioModal);
document.getElementById('scenario-modal-close').addEventListener('click', closeScenarioModal);
scenarioModal.addEventListener('click', (event) => {
  if (event.target === scenarioModal) closeScenarioModal();
});

document.querySelectorAll('.modal-tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.modal-tab-btn').forEach(b => b.classList.toggle('active', b === btn));
    document.querySelectorAll('.modal-tab-panel').forEach(panel => {
      panel.classList.toggle('hidden', panel.dataset.tabPanel !== tab);
    });
  });
});

// ----- 패턴 텍스트 파싱 -----

function parsePatternInput(text) {
  const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
  const patterns = [];
  const errors = [];
  lines.forEach(line => {
    const parts = line.split('-').map(p => p.trim()).filter(p => p.length > 0);
    if (parts.length !== 2) {
      errors.push(line);
      return;
    }
    patterns.push({ front_fltno: parts[0], back_fltno: parts[1] });
  });
  return { patterns, errors };
}

// ----- 결과 렌더링 -----

function renderCancelResult(result) {
  const el = document.getElementById('scenario-cancel-result');
  let html = `<p>적용 완료: 편명 ${result.affected_fltnos.length}개, 총 ${result.affected_rows}행 비운항 처리됨</p>`;
  if (result.not_found_fltnos && result.not_found_fltnos.length > 0) {
    html += `<p class="sr-skipped">유효편이 없어 영향 없음: ${result.not_found_fltnos.join(', ')}</p>`;
  }
  el.innerHTML = html;
}

function renderReassignResult(results) {
  const el = document.getElementById('scenario-reassign-result');
  let html = '<table><thead><tr><th>패턴</th><th>적용</th><th>변경없음</th><th>스킵</th></tr></thead><tbody>';
  results.forEach(r => {
    if (r.error) {
      html += `<tr><td>${r.pattern}</td><td colspan="3" class="sr-error">${r.error}</td></tr>`;
      return;
    }
    const fmt = (dates, cls) => {
      if (dates.length === 0) return '0';
      return `<details><summary class="${cls}">${dates.length}</summary>${dates.join(', ')}</details>`;
    };
    html += `<tr>
      <td>${r.pattern}</td>
      <td>${fmt(r.applied_dates, 'sr-applied')}</td>
      <td>${fmt(r.no_change_dates, 'sr-nochange')}</td>
      <td>${fmt(r.skipped_dates, 'sr-skipped')}</td>
    </tr>`;
  });
  html += '</tbody></table>';
  el.innerHTML = html;
}

// ----- 적용/초기화 버튼 -----

document.getElementById('scenario-cancel-apply-btn').addEventListener('click', async () => {
  const fltnos = Array.from(getSelectedScenarioFltnos());
  if (fltnos.length === 0) {
    showError('비운항 처리할 편명을 하나 이상 선택하세요.');
    return;
  }
  try {
    showLoading('비운항 시나리오 적용 중...');
    const result = await applyCancelScenario(fltnos);
    renderCancelResult(result);
    await refreshBarchartAndOntime();
    hideLoading('비운항 시나리오 적용 완료');
  } catch (e) {
    showError(e.message);
  }
});

document.getElementById('scenario-reassign-apply-btn').addEventListener('click', async () => {
  const text = document.getElementById('scenario-pattern-input').value;
  const { patterns, errors } = parsePatternInput(text);
  if (patterns.length === 0) {
    showError('"앞편-뒤편" 형식으로 최소 1개 이상 입력하세요.');
    return;
  }
  try {
    showLoading('스케줄 조정 시나리오 적용 중...');
    const response = await applyReassignScenario(patterns);
    renderReassignResult(response.results);
    if (errors.length > 0) {
      const el = document.getElementById('scenario-reassign-result');
      el.innerHTML = `<p class="sr-error">형식 오류로 제외된 줄: ${errors.join(' / ')}</p>` + el.innerHTML;
    }
    await refreshBarchartAndOntime();
    hideLoading('스케줄 조정 시나리오 적용 완료');
  } catch (e) {
    showError(e.message);
  }
});

document.getElementById('scenario-reset-btn').addEventListener('click', async () => {
  if (!confirm('모든 시나리오 변경(기번 드래그 재배정 포함)이 취소되고 원본 데이터로 복원됩니다. 계속하시겠습니까?')) {
    return;
  }
  try {
    showLoading('시나리오 초기화 중...');
    await resetScenario();
    document.getElementById('scenario-cancel-result').innerHTML = '';
    document.getElementById('scenario-reassign-result').innerHTML = '';
    await refreshBarchartAndOntime();
    hideLoading('시나리오 초기화 완료: 원본 데이터로 복원됨');
  } catch (e) {
    showError(e.message);
  }
});
