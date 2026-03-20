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

async function fetchBarchartData(airline, natList) {
  const params = new URLSearchParams();
  if (airline) params.set('airline', airline);
  if (natList && natList.length) params.set('nat', natList.join(','));
  const res = await fetch(`/api/barchart?${params}`);
  if (!res.ok) throw new Error('바차트 데이터 로드 실패');
  return res.json();
}

async function fetchSummaryData(natList, airline) {
  const params = new URLSearchParams();
  if (natList && natList.length) params.set('nat', natList.join(','));
  if (airline) params.set('airline', airline);
  const res = await fetch(`/api/summary?${params}`);
  if (!res.ok) throw new Error('요약 데이터 로드 실패');
  return res.json();
}
