/**
 * api.js — 백엔드 API 호출 모듈
 */

async function crawlData(startDate, endDate) {
  // "2026-03-16" → "20260316"
  const startStr = startDate.replace(/-/g, '');
  const endStr = endDate.replace(/-/g, '');
  const res = await fetch('/api/crawl', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ start_date: startStr, end_date: endStr }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '크롤링 실패');
  }
  return res.json();
}

async function uploadExcel(file) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch('/api/upload', { method: 'POST', body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '업로드 실패');
  }
  return res.json();
}

async function fetchMetadata() {
  const res = await fetch('/api/metadata');
  if (!res.ok) throw new Error('메타데이터 로드 실패');
  return res.json();
}

async function fetchBarchartData(airline, tofList, date) {
  const params = new URLSearchParams();
  if (airline) params.set('airline', airline);
  if (tofList && tofList.length) params.set('tof', tofList.join(','));
  if (date) params.set('date', date);
  const res = await fetch(`/api/barchart?${params}`);
  if (!res.ok) throw new Error('바차트 데이터 로드 실패');
  return res.json();
}

async function fetchOntimeData() {
  const res = await fetch('/api/ontime');
  if (!res.ok) throw new Error('정시율 데이터 로드 실패');
  return res.json();
}

async function updateAcno(rowId, newAcno) {
  const res = await fetch('/api/update-acno', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ row_id: rowId, new_acno: newAcno }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '기번 변경 실패');
  }
  return res.json();
}

async function applyCancelScenario(fltnos) {
  const res = await fetch('/api/scenario/cancel-flights', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fltnos }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '비운항 시나리오 적용 실패');
  }
  return res.json();
}

async function applyReassignScenario(patterns) {
  const res = await fetch('/api/scenario/reassign-chain', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ patterns }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '스케줄 조정 시나리오 적용 실패');
  }
  return res.json();
}

async function resetScenario() {
  const res = await fetch('/api/scenario/reset', { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '시나리오 초기화 실패');
  }
  return res.json();
}
