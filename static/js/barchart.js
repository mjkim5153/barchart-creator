/**
 * barchart.js — D3.js 기반 운항스케줄 바차트 렌더링
 * 다일 기간 지원, 방향키 스크롤, Ctrl+방향키 줌
 */

const BAR_HEIGHT = 28;
const BAR_PADDING = 10;
const ROW_HEIGHT = BAR_HEIGHT + BAR_PADDING + 16;
const MARGIN = { top: 62, right: 20, bottom: 20, left: 110 };
const DAY_NAMES = ['일', '월', '화', '수', '목', '금', '토'];
const MIN_TEXT_PX = 50;
const KOREAN_AIRPORTS = new Set([
  'ICN', 'GMP', 'PUS', 'CJU', 'KWJ', 'CJJ', 'YNY', 'CNJ', 'MWX',
  'TAE', 'HIN', 'KUV', 'KPO', 'RSU', 'USN', 'WJU', 'CHN', 'JDG', 'JCN'
]);

// JPEG 내보내기 설정
const EXPORT_SCALE = 3;
const EXPORT_MAX_CANVAS_DIM = 16000;
const EXPORT_MAX_CANVAS_PIXELS = 40000000;

let _zoomBehavior = null;
let _currentData = null;
let _keydownHandler = null;
let _dragMoveHandler = null;
let _dragUpHandler = null;
let _wheelHandler = null;

// 줌/스크롤 상태 (renderBarchart 재호출 시에도 유지 — 기번 재배정 후
// refreshBarchartAndOntime()이 다시 그릴 때 사용자가 맞춰둔 배율/위치가 초기화되지 않도록 모듈 전역으로 보관)
let _xZoom = 1;
let _yZoom = 1;
let _scrollY = 0;
let _xOffset = 0;

function renderBarchart(data) {
  _currentData = data;
  // CANCEL 행: 비운항 시나리오로 Acno=''가 된 실제 편이 있으면(data_processor.py의
  // filter_for_barchart가 acno==''를 하나의 그룹으로 묶어 알파벳순 최상단에 반환) 그
  // flights를 병합해 표시하고, 없으면 빈 껍데기 행만 자리를 마련해둔다. renderBarchart()는
  // 패널 토글/이미지 내보내기 등에서 같은 data 객체로 반복 호출되므로, data.aircraft를
  // 직접 변형(unshift)하지 않고 매번 새 배열을 만들어야 재호출 시 CANCEL 행이 중복
  // 누적되지 않는다.
  const realCancelGroup = (data.aircraft || []).find(a => a.acno === '');
  const restAircraft = (data.aircraft || []).filter(a => a.acno !== '');
  const aircraft = [
    realCancelGroup
      ? { acno: 'CANCEL', flights: realCancelGroup.flights, lane_count: realCancelGroup.lane_count,
          connection_error: realCancelGroup.connection_error, isCancelRow: true }
      : { acno: 'CANCEL', flights: [], lane_count: 1, connection_error: false, isCancelRow: true },
    ...restAircraft
  ];
  const tooltip = document.getElementById('tooltip');

  const container = document.getElementById('barchart-container');
  const containerW = container.clientWidth;
  const containerH = container.clientHeight;

  const totalRows = aircraft.length;
  const chartW = Math.max(containerW, 1400);

  // 줌 상태 (모듈 전역에 보관된 이전 값 이어받기)
  let xZoom = _xZoom;
  let yZoom = _yZoom;
  let scrollY = _scrollY;

  // 기번 재배정 드래그 상태
  let dragState = null;

  // 행별 높이 누적합 (겹치는 편이 있는 Acno는 lane_count배로 행 높이가 늘어나므로,
  // 모든 행이 균일한 높이라는 가정 대신 이 배열 기준으로 y좌표를 계산한다)
  let rowHeights = [];
  let rowOffsets = [];

  // 데이터에서 최소/최대 날짜 산출
  let minDate = null;
  let maxDate = null;
  for (const ac of aircraft) {
    for (const fl of ac.flights) {
      // RO/RI 둘 다 결측이면 STD/STA로 폴백 표출되므로(위 BAR 렌더링 로직과 동일 기준),
      // X축 범위 산출도 같은 기준을 써야 폴백 바가 범위 밖으로 밀려 안 그려지는 것을 막는다.
      const startIso = fl.ro_kst || fl.std_kst;
      const endIso = fl.ri_kst || fl.sta_kst;
      if (startIso) {
        const d = new Date(startIso);
        if (!minDate || d < minDate) minDate = new Date(d);
        if (!maxDate || d > maxDate) maxDate = new Date(d);
      }
      if (endIso) {
        const d = new Date(endIso);
        if (!maxDate || d > maxDate) maxDate = new Date(d);
      }
    }
  }

  if (!minDate) {
    minDate = new Date();
    maxDate = new Date();
  }

  // xStart = 최소 날짜 00:00, xEnd = 최대 날짜 24:00
  const xStart = new Date(minDate);
  xStart.setHours(0, 0, 0, 0);
  const xEnd = new Date(maxDate);
  xEnd.setHours(0, 0, 0, 0);
  xEnd.setDate(xEnd.getDate() + 1); // 다음날 00:00 = 당일 24:00

  // 기간 일수
  const totalDays = Math.max(1, Math.round((xEnd - xStart) / (24 * 60 * 60 * 1000)));

  const acnoList = aircraft.map(d => d.acno);

  function getScaledRowHeight() {
    return ROW_HEIGHT * yZoom;
  }

  const svg = d3.select('#barchart-svg')
    .attr('width', chartW)
    .attr('height', containerH);
  const svgNode = svg.node();

  svg.selectAll('*').remove();

  // 클립 패스
  const defs = svg.append('defs');
  defs.append('clipPath')
    .attr('id', 'chart-clip')
    .append('rect')
    .attr('x', MARGIN.left)
    .attr('y', MARGIN.top)
    .attr('width', chartW - MARGIN.left - MARGIN.right)
    .attr('height', containerH - MARGIN.top - MARGIN.bottom);

  // Y축 클립 패스 (MARGIN.top 아래만 표시, Y축 그룹은 translate(MARGIN.left,0) 적용됨)
  defs.append('clipPath')
    .attr('id', 'yaxis-clip')
    .append('rect')
    .attr('x', -MARGIN.left)
    .attr('y', MARGIN.top)
    .attr('width', MARGIN.left)
    .attr('height', containerH - MARGIN.top - MARGIN.bottom);

  // X축 클립 패스 (MARGIN.left 오른쪽만 표시, 각 그룹의 로컬 좌표에 맞게 별도 생성)
  // xAxisGroup은 translate(0, MARGIN.top) → tick 텍스트는 y<0 영역에 그려짐
  defs.append('clipPath')
    .attr('id', 'xaxis-clip')
    .append('rect')
    .attr('x', MARGIN.left)
    .attr('y', -MARGIN.top)
    .attr('width', chartW - MARGIN.left - MARGIN.right)
    .attr('height', MARGIN.top);

  // dateLabelGroup은 translate(0, MARGIN.top-24)
  defs.append('clipPath')
    .attr('id', 'datelabel-clip')
    .append('rect')
    .attr('x', MARGIN.left)
    .attr('y', -(MARGIN.top - 24))
    .attr('width', chartW - MARGIN.left - MARGIN.right)
    .attr('height', MARGIN.top);

  // 지연 BAR + 메인 BAR 병합용 클립패스 컨테이너 (redrawAll마다 초기화)
  const barClipDefs = defs.append('g').attr('class', 'bar-clip-defs');

  // X축 그룹 (고정, 클립 적용)
  const xAxisGroup = svg.append('g')
    .attr('class', 'x-axis')
    .attr('transform', `translate(0,${MARGIN.top})`)
    .attr('clip-path', 'url(#xaxis-clip)');

  // 날짜 라벨 그룹 (X축 시간 위, 간격 확보, 클립 적용)
  const dateLabelGroup = svg.append('g')
    .attr('class', 'date-labels')
    .attr('transform', `translate(0,${MARGIN.top - 24})`)
    .attr('clip-path', 'url(#datelabel-clip)');

  // Y축 그룹 (클립 적용)
  const yAxisGroup = svg.append('g')
    .attr('class', 'y-axis')
    .attr('transform', `translate(${MARGIN.left},0)`)
    .attr('clip-path', 'url(#yaxis-clip)');

  // 줌 그룹 (클립)
  const zoomGroup = svg.append('g')
    .attr('class', 'zoom-group')
    .attr('clip-path', 'url(#chart-clip)');

  const rowBgGroup = zoomGroup.append('g').attr('class', 'row-backgrounds');
  const gridMinor = zoomGroup.append('g').attr('class', 'x-grid-minor');
  const gridMajor = zoomGroup.append('g').attr('class', 'x-grid-major');
  const rowLines = zoomGroup.append('g').attr('class', 'row-lines');
  const barGroup = zoomGroup.append('g').attr('class', 'bars');

  // 기번 재배정 드래그용 최상위 레이어 (redrawAll이 지우지 않음)
  const dragLayer = svg.append('g').attr('class', 'drag-layer');

  function getCurrentXScale() {
    const totalXWidth = chartW - MARGIN.left - MARGIN.right;
    const scaledWidth = totalXWidth * xZoom;
    return d3.scaleTime()
      .domain([xStart, xEnd])
      .range([MARGIN.left, MARGIN.left + scaledWidth]);
  }

  let xOffset = _xOffset;

  function getClampedXOffset(offset, xScale) {
    const rangeWidth = xScale.range()[1] - xScale.range()[0];
    const viewWidth = chartW - MARGIN.left - MARGIN.right;
    if (rangeWidth <= viewWidth) return 0;
    const minOffset = -(rangeWidth - viewWidth);
    return Math.max(minOffset, Math.min(0, offset));
  }

  function pixelYToRowIdx(svgY) {
    const y = svgY - MARGIN.top + scrollY;
    return d3.bisect(rowOffsets, y) - 1;
  }

  function clientYToSvgY(clientY) {
    return clientY - svgNode.getBoundingClientRect().top;
  }

  function redrawAll() {
    const xScale = getCurrentXScale();
    const clampedOffset = getClampedXOffset(xOffset, xScale);
    xOffset = clampedOffset;

    const scaledRowH = getScaledRowHeight();
    rowHeights = aircraft.map(ac => scaledRowH * (ac.lane_count || 1));
    rowOffsets = [0];
    rowHeights.forEach(h => rowOffsets.push(rowOffsets[rowOffsets.length - 1] + h));
    const totalContentH = MARGIN.top + rowOffsets[totalRows] + MARGIN.bottom;
    const viewH = Math.max(containerH, totalContentH);

    svg.attr('height', viewH);

    svg.select('#chart-clip rect')
      .attr('height', viewH - MARGIN.top - MARGIN.bottom);

    svg.select('#yaxis-clip rect')
      .attr('height', viewH - MARGIN.top - MARGIN.bottom);

    const maxScrollY = Math.max(0, totalContentH - containerH);
    scrollY = Math.max(0, Math.min(scrollY, maxScrollY));

    const showText = scaledRowH >= 30;

    // --- X축 ---
    const shiftedXScale = d3.scaleTime()
      .domain(xScale.domain())
      .range([xScale.range()[0] + xOffset, xScale.range()[1] + xOffset]);

    // 항상 1시간 간격으로 tick 표시
    const tickInterval = d3.timeHour.every(1);

    const xAxis = d3.axisTop(shiftedXScale)
      .ticks(tickInterval)
      .tickFormat(d3.timeFormat('%H'));
    xAxisGroup.call(xAxis);
    xAxisGroup.select('.domain').remove();

    // --- 날짜 라벨 (sticky: 다음 날짜가 올 때까지 왼쪽 고정) ---
    dateLabelGroup.selectAll('*').remove();
    const chartLeft = MARGIN.left;
    const chartRight = chartW - MARGIN.right;

    // 모든 날짜와 px 위치 수집
    const dateEntries = [];
    for (let d = new Date(xStart); d < xEnd; d = new Date(d.getTime() + 24 * 60 * 60 * 1000)) {
      const px = shiftedXScale(d);
      const yyyy = d.getFullYear();
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      const dd = String(d.getDate()).padStart(2, '0');
      const dayName = DAY_NAMES[d.getDay()];
      dateEntries.push({ px, label: `${yyyy}-${mm}-${dd}(${dayName})` });
    }

    for (let i = 0; i < dateEntries.length; i++) {
      const entry = dateEntries[i];
      const nextPx = i + 1 < dateEntries.length ? dateEntries[i + 1].px : Infinity;

      // 이 날짜의 원래 위치가 화면 오른쪽 밖이면 스킵
      if (entry.px > chartRight + 80) continue;
      // 다음 날짜가 화면 왼쪽 안에 있으면 이 날짜는 이미 밀려남
      if (nextPx < chartLeft) continue;

      // sticky: 원래 위치가 왼쪽 밖이면 chartLeft에 고정, 단 다음 날짜에 밀리지 않도록 제한
      let x = Math.max(entry.px + 3, chartLeft + 3);
      // 다음 날짜 라벨과 겹치지 않도록 (라벨 폭 약 130px 고려)
      const labelWidth = 130;
      if (nextPx < x + labelWidth) {
        x = nextPx - labelWidth;
      }
      if (x < chartLeft + 3) x = chartLeft + 3;

      dateLabelGroup.append('text')
        .attr('x', x)
        .attr('y', 0)
        .attr('text-anchor', 'start')
        .attr('fill', '#1e40af')
        .attr('font-size', '10px')
        .attr('font-weight', '700')
        .text(entry.label);
    }

    // --- 그리드 ---
    const minorTicks = d3.timeMinutes(xStart, xEnd, 10);
    const majorTicks = d3.timeHours(xStart, xEnd, 1);

    gridMinor.selectAll('line').data(minorTicks).join('line')
      .attr('x1', d => shiftedXScale(d))
      .attr('x2', d => shiftedXScale(d))
      .attr('y1', MARGIN.top)
      .attr('y2', viewH - MARGIN.bottom)
      .attr('stroke', '#e5e7eb')
      .attr('stroke-width', 0.5);

    gridMajor.selectAll('line').data(majorTicks).join('line')
      .attr('x1', d => shiftedXScale(d))
      .attr('x2', d => shiftedXScale(d))
      .attr('y1', MARGIN.top)
      .attr('y2', viewH - MARGIN.bottom)
      .attr('stroke', '#9ca3af')
      .attr('stroke-width', 1);

    // 날짜 경계선 (다일 시 진한 선)
    if (totalDays > 1) {
      for (let d = new Date(xStart); d <= xEnd; d = new Date(d.getTime() + 24 * 60 * 60 * 1000)) {
        const px = shiftedXScale(d);
        gridMajor.append('line')
          .attr('x1', px).attr('x2', px)
          .attr('y1', MARGIN.top).attr('y2', viewH - MARGIN.bottom)
          .attr('stroke', '#1e40af')
          .attr('stroke-width', 2)
          .attr('stroke-dasharray', '4,2');
      }
    }

    // --- 행 배경 ---
    rowBgGroup.selectAll('rect').data(acnoList).join('rect')
      .attr('x', MARGIN.left)
      .attr('width', chartW - MARGIN.left - MARGIN.right)
      .attr('y', (d, i) => MARGIN.top + rowOffsets[i] - scrollY)
      .attr('height', (d, i) => rowHeights[i])
      .attr('fill', (d, i) => i === 0 ? '#fecaca' : (i - 1) % 2 === 1 ? '#d9d9d9' : 'transparent');

    // --- 행 구분선 ---
    rowLines.selectAll('line').data(acnoList).join('line')
      .attr('x1', MARGIN.left)
      .attr('x2', chartW - MARGIN.right)
      .attr('y1', (d, i) => MARGIN.top + rowOffsets[i + 1] - scrollY)
      .attr('y2', (d, i) => MARGIN.top + rowOffsets[i + 1] - scrollY)
      .attr('stroke', '#e5e7eb')
      .attr('stroke-width', 0.5);

    // --- Y축 ---
    yAxisGroup.selectAll('*').remove();
    acnoList.forEach((acno, idx) => {
      const ac = aircraft.find(a => a.acno === acno);
      const rowH = rowHeights[idx];
      const yPos = MARGIN.top + rowOffsets[idx] - scrollY;
      if (yPos + rowH < MARGIN.top - 20 || yPos > viewH) return;

      // Y축 라벨 영역 배경색 (CANCEL 행은 옅은 붉은색, 나머지는 교대 행)
      if (idx === 0) {
        yAxisGroup.append('rect')
          .attr('x', -MARGIN.left)
          .attr('y', yPos)
          .attr('width', MARGIN.left)
          .attr('height', rowH)
          .attr('fill', '#fecaca');
      } else if ((idx - 1) % 2 === 1) {
        yAxisGroup.append('rect')
          .attr('x', -MARGIN.left)
          .attr('y', yPos)
          .attr('width', MARGIN.left)
          .attr('height', rowH)
          .attr('fill', '#d9d9d9');
      }

      // 번호 + 기번 (좌측 정렬, CANCEL 행은 번호 없이 표시)
      yAxisGroup.append('text')
        .attr('x', -MARGIN.left + 4)
        .attr('y', yPos + rowH / 2)
        .attr('text-anchor', 'start')
        .attr('dominant-baseline', 'middle')
        .attr('fill', ac && ac.connection_error ? '#ef4444' : '#374151')
        .attr('font-weight', ac && ac.connection_error ? '700' : '400')
        .attr('font-size', '11px')
        .text(idx === 0 ? 'CANCEL' : `${idx} ${acno}`);

      // 기종 등급 (우측 정렬)
      const grade = ac && ac.flights.length > 0 ? ac.flights[0].actype_grade : '';
      if (grade) {
        yAxisGroup.append('text')
          .attr('x', -4)
          .attr('y', yPos + rowH / 2)
          .attr('text-anchor', 'end')
          .attr('dominant-baseline', 'middle')
          .attr('fill', '#94a3b8')
          .attr('font-size', '10px')
          .text(`${grade}급`);
      }
    });

    // --- BAR ---
    barGroup.selectAll('*').remove();
    barClipDefs.selectAll('*').remove();

    const clipL = shiftedXScale(xStart);
    const clipR = shiftedXScale(xEnd);

    aircraft.forEach((ac, acIdx) => {
      const yBase = MARGIN.top + rowOffsets[acIdx] - scrollY;
      const rowH = rowHeights[acIdx];
      const scaledBarH = Math.max(4, BAR_HEIGHT * yZoom);

      if (yBase + rowH < MARGIN.top || yBase > viewH) return;

      ac.flights.forEach((fl, idx) => {
        // RO/RI 둘 다 결측이면 STD/STA로 폴백 표출, 하나만 결측이면 기존대로 바를 그리지 않음
        const bothMissing = !fl.ro_kst && !fl.ri_kst;
        if (bothMissing) {
          if (!fl.std_kst || !fl.sta_kst) return;
        } else if (!fl.ro_kst || !fl.ri_kst) {
          return;
        }

        const lane = fl.lane || 0;
        const barY = yBase + lane * scaledRowH + (scaledRowH - scaledBarH) / 2;

        const std = new Date(bothMissing ? fl.std_kst : fl.ro_kst);
        const sta = new Date(bothMissing ? fl.sta_kst : fl.ri_kst);

        // 지연 BAR: STD_KST ~ RO_KST, RO가 STD보다 늦은 경우만 표출
        let delayDrawn = false;
        let dX1 = null, dX2 = null;
        if (fl.std_kst) {
          const plannedStd = new Date(fl.std_kst);
          if (plannedStd < std) {
            const dX1Raw = shiftedXScale(plannedStd);
            const dX2Raw = shiftedXScale(std);
            dX1 = Math.max(dX1Raw, clipL);
            dX2 = Math.min(dX2Raw, clipR);
            if (!(dX2 < clipL || dX1 > clipR)) delayDrawn = true;
          }
        }

        const x1Raw = shiftedXScale(std);
        const x2Raw = shiftedXScale(sta);
        const x1 = Math.max(x1Raw, clipL);
        const x2 = Math.min(x2Raw, clipR);
        if (x2 < clipL || x1 > clipR) return;
        const barW = Math.max(1, x2 - x1);

        const colorClass = fl.color === 'navy' ? 'bar-navy' : fl.color === 'cobalt' ? 'bar-cobalt' : 'bar-gray';

        let barRect;
        if (delayDrawn) {
          // 지연 BAR + 메인 BAR를 하나의 둥근 테두리 안에 합쳐서 표출
          // (둥근 클립패스로 외곽만 둥글게, 내부 두 색 영역은 각지게 그려 이음매를 없앰)
          const outerLeft = dX1;
          const outerW = Math.max(1, x2 - outerLeft);
          const clipId = `bar-clip-${acIdx}-${idx}`;

          barClipDefs.append('clipPath')
            .attr('id', clipId)
            .append('rect')
            .attr('x', outerLeft)
            .attr('y', barY)
            .attr('width', outerW)
            .attr('height', scaledBarH)
            .attr('rx', 3);

          const mergedGroup = barGroup.append('g')
            .attr('clip-path', `url(#${clipId})`);

          mergedGroup.append('rect')
            .attr('class', 'bar-delay')
            .attr('x', dX1)
            .attr('y', barY)
            .attr('width', Math.max(1, dX2 - dX1))
            .attr('height', scaledBarH);

          barRect = mergedGroup.append('rect')
            .attr('class', `bar ${colorClass}`)
            .attr('x', x1)
            .attr('y', barY)
            .attr('width', barW)
            .attr('height', scaledBarH)
            .style('cursor', 'grab');

          if (fl.connection_error) {
            barGroup.append('rect')
              .attr('class', 'bar-error-outline')
              .attr('x', outerLeft)
              .attr('y', barY)
              .attr('width', outerW)
              .attr('height', scaledBarH)
              .attr('rx', 3);
          }
          if (fl.scenario_changed && !fl.connection_error) {
            barGroup.append('rect')
              .attr('class', 'bar-changed-outline')
              .attr('x', outerLeft)
              .attr('y', barY)
              .attr('width', outerW)
              .attr('height', scaledBarH)
              .attr('rx', 3);
          }
        } else {
          barRect = barGroup.append('rect')
            .attr('class', `bar ${colorClass}${fl.connection_error ? ' bar-error' : ''}${bothMissing ? ' bar-planned' : ''}`)
            .attr('x', x1)
            .attr('y', barY)
            .attr('width', barW)
            .attr('height', scaledBarH)
            .attr('rx', 3)
            .style('cursor', 'grab');

          if (fl.scenario_changed && !fl.connection_error) {
            barGroup.append('rect')
              .attr('class', 'bar-changed-outline')
              .attr('x', x1)
              .attr('y', barY)
              .attr('width', barW)
              .attr('height', scaledBarH)
              .attr('rx', 3);
          }
        }

        if (showText && barW >= MIN_TEXT_PX) {
          barGroup.append('text')
            .attr('class', 'bar-text')
            .attr('x', x1 + barW / 2)
            .attr('y', barY + scaledBarH / 2)
            .text(fl.fltno);
        }

        if (showText) {
          barGroup.append('text')
            .attr('class', 'airport-label')
            .attr('x', x1 + 2)
            .attr('y', barY + scaledBarH + 11)
            .attr('text-anchor', 'start')
            .text(fl.depstn);

          barGroup.append('text')
            .attr('class', 'airport-label')
            .attr('x', x1 + barW - 2)
            .attr('y', barY + scaledBarH + 11)
            .attr('text-anchor', 'end')
            .text(fl.arrstn);
        }

        // STA(도착 예정시각) 마커: 노란색 세로선 + 상단 정삼각형
        // (조기도착 시 STA가 RI_KST보다 뒤에 있어 바 바깥에 그려질 수 있음 — 정상 동작)
        if (fl.sta_kst) {
          const plannedSta = new Date(fl.sta_kst);
          const staX = shiftedXScale(plannedSta);
          if (staX >= clipL && staX <= clipR) {
            barGroup.append('line')
              .attr('class', 'sta-line')
              .attr('x1', staX)
              .attr('x2', staX)
              .attr('y1', barY)
              .attr('y2', barY + scaledBarH);

            const triH = scaledBarH * 0.35;
            const triW = triH * 1.15;
            barGroup.append('polygon')
              .attr('class', 'sta-triangle')
              .attr('points', [
                `${staX},${barY}`,
                `${staX - triW / 2},${barY - triH}`,
                `${staX + triW / 2},${barY - triH}`,
              ].join(' '));
          }
        }

        // Ground Time — 실제 GT(ground_time_before) 우선, 이전/현재 편이 RO/RI 결측으로
        // STD/STA 폴백 표출된 경우(실제 GT 계산 불가)에는 계획 GT(planned_gt)로 대체 표출
        if (showText && idx > 0) {
          const prevFl = ac.flights[idx - 1];
          const prevBothMissing = !prevFl.ro_kst && !prevFl.ri_kst;
          const prevEndIso = prevFl.ri_kst || (prevBothMissing ? prevFl.sta_kst : null);
          const gtValue = fl.ground_time_before !== null ? fl.ground_time_before : fl.planned_gt;
          if (prevEndIso && gtValue !== null && gtValue !== undefined) {
            const isPlannedFallback = fl.ground_time_before === null;
            const prevEnd = new Date(prevEndIso);
            const gtX = (shiftedXScale(prevEnd) + shiftedXScale(std)) / 2;
            const isDomestic = KOREAN_AIRPORTS.has((fl.depstn || '').trim().toUpperCase())
                            && KOREAN_AIRPORTS.has((fl.arrstn || '').trim().toUpperCase());
            const isDomWarn = isDomestic && gtValue <= 35;
            barGroup.append('text')
              .attr('class', `gt-label${isPlannedFallback ? ' gt-label-planned' : ''}`)
              .attr('x', gtX)
              .attr('y', barY + scaledBarH / 2)
              .attr('fill', isDomWarn ? '#dc2626' : '#6b7280')
              .attr('font-weight', isDomWarn ? '700' : 'normal')
              .text(`${gtValue}분`);
          }
        }

        // 기번 재배정 드래그 시작
        barRect.on('mousedown', (event) => {
          event.preventDefault();
          tooltip.classList.add('hidden');
          dragState = {
            fl, sourceRowIdx: acIdx,
            x1, barW, barH: scaledBarH,
            targetRowIdx: acIdx, autoScrollDir: 0, rafId: null,
            lastClientY: event.clientY, startClientY: event.clientY,
            moved: false,
          };
        });

        // 툴팁
        barRect.on('mousemove', (event) => {
          if (dragState) return;
          const gtText = fl.ground_time_before !== null ? `${fl.ground_time_before}분` : '-';
          const plannedGtText = fl.planned_gt !== null && fl.planned_gt !== undefined ? `${fl.planned_gt}분` : '-';
          const securedGtText = fl.secured_gt !== null && fl.secured_gt !== undefined ? `${fl.secured_gt}분` : '-';
          const btText = fl.blocktime !== null && fl.blocktime !== undefined ? `${fl.blocktime}분` : '-';
          const dlaText = (v) => (v !== null && v !== undefined) ? `${v}분` : '-';
          const stdDelayText = (roIso) => {
            if (!roIso || !fl.std_kst) return '-';
            const ro = new Date(roIso), std = new Date(fl.std_kst);
            if (ro <= std) return '-';
            return `${Math.round((ro - std) / 60000)}분`;
          };

          // 기존/변경 비교 테이블은 변경 여부와 무관하게 항상 렌더링되므로(기존 행만 있어도
          // 9열 표), tt-wide(넓은 max-width)도 changed 여부와 상관없이 항상 적용해야 한다.
          // changed일 때만 적용하면 변경 없는 편(대다수)에서는 좁은 기본 max-width(240px) 위에
          // 넓은 테이블이 그려져 배경 밖으로 열이 삐져나오는 문제가 있었다.
          const changed = !!fl.scenario_changed;
          tooltip.classList.add('tt-wide');

          // STD/STA/계획GT는 스케줄 변경(W26 적용 등) 시나리오에서만 원본과 달라질 수 있다 —
          // 다를 때만 "(기존 ...)"를 옆에 붙여 보여주고, 같으면 기존과 동일하게 단일 표시.
          const withOrig = (curText, origText) =>
            (origText !== null && origText !== '-' && origText !== curText)
              ? `<span class="tt-new-val">${curText}</span><span class="tt-orig-val">(기존 ${origText})</span>`
              : curText;
          const stdText = withOrig(formatKST(fl.std_kst), fl.std_kst_orig ? formatKST(fl.std_kst_orig) : null);
          const staText = withOrig(formatKST(fl.sta_kst), fl.sta_kst_orig ? formatKST(fl.sta_kst_orig) : null);
          const plannedGtOrigDisplay = (fl.planned_gt_orig !== null && fl.planned_gt_orig !== undefined)
            ? `${fl.planned_gt_orig}분` : null;
          const plannedGtDisplay = withOrig(plannedGtText, plannedGtOrigDisplay);

          const compareRow = (label, predFltno, acno, actype, roIso, riIso, cnx, dep, atc, extraClass) => `
            <tr class="${extraClass || ''}">
              <td class="tt-row-label">${label}</td>
              <td>${predFltno || '-'}</td>
              <td>${acno || '-'}</td>
              <td>${actype || '-'}</td>
              <td>${formatKST(roIso)}</td>
              <td>${formatKST(riIso)}</td>
              <td>${stdDelayText(roIso)}</td>
              <td>${dlaText(cnx)}</td>
              <td>${dlaText(dep)}</td>
              <td>${dlaText(atc)}</td>
            </tr>`;

          const existingRow = compareRow(
            '기존', fl.pred_fltno_orig || fl.pred_fltno, fl.acno_orig || ac.acno, fl.actype_orig || fl.actype,
            fl.ro_kst_orig || fl.ro_kst, fl.ri_kst_orig || fl.ri_kst,
            fl.cnx_dla_orig ?? fl.cnx_dla, fl.dep_dla_orig ?? fl.dep_dla, fl.atc_dla,
          );
          const changedRow = changed
            ? compareRow(
                '변경', fl.pred_fltno, ac.acno, fl.actype, fl.ro_kst, fl.ri_kst,
                fl.cnx_dla, fl.dep_dla, fl.atc_dla, 'tt-changed-row',
              )
            : '';

          tooltip.classList.remove('hidden');
          tooltip.innerHTML = `
            <div class="tt-title">${fl.fltno} (${fl.depstn}→${fl.arrstn})</div>
            <div class="tt-row"><span class="tt-label">STD</span><span>${stdText}</span></div>
            <div class="tt-row"><span class="tt-label">STA</span><span>${staText}</span></div>
            <div class="tt-row"><span class="tt-label">NAT</span><span>${fl.nat || '-'}</span></div>
            <div class="tt-row"><span class="tt-label">MTTT</span><span>${fl.mttt ?? '-'}</span></div>
            <div class="tt-compare-wrap">
              <table class="tt-compare-table">
                <thead>
                  <tr>
                    <th></th><th>연결편정보</th><th>기번</th><th>기종</th><th>RO</th><th>RI</th>
                    <th>지연시간</th><th>연결지연</th><th>출발지연</th><th>관제지연</th>
                  </tr>
                </thead>
                <tbody>${existingRow}${changedRow}</tbody>
              </table>
            </div>
            <div class="tt-row"><span class="tt-label">BT</span><span>${btText}</span></div>
            <div class="tt-row"><span class="tt-label">계획 GT</span><span>${plannedGtDisplay}</span></div>
            <div class="tt-row"><span class="tt-label">확보 GT</span><span>${securedGtText}</span></div>
            <div class="tt-row"><span class="tt-label">실제 GT</span><span>${gtText}</span></div>
            <div class="tt-row"><span class="tt-label">상태</span><span>${fl.status}</span></div>
          `;
          positionTooltip(event, tooltip);
        }).on('mouseleave', () => {
          tooltip.classList.add('hidden');
          tooltip.classList.remove('tt-wide');
        });
      });
    });

    // 다음 renderBarchart() 호출(필터 변경, 기번 재배정 후 재조회 등) 시에도
    // 현재 배율/스크롤 위치가 유지되도록 모듈 전역 상태에 동기화
    _xZoom = xZoom;
    _yZoom = yZoom;
    _scrollY = scrollY;
    _xOffset = xOffset;
  }

  function updateGhost() {
    const svgY = clientYToSvgY(dragState.lastClientY);
    const ghostY = svgY - dragState.barH / 2;

    dragLayer.selectAll('*').remove();
    dragLayer.append('rect')
      .attr('class', 'bar-drag-ghost')
      .attr('x', dragState.x1)
      .attr('y', ghostY)
      .attr('width', dragState.barW)
      .attr('height', dragState.barH)
      .attr('rx', 3);
    dragLayer.append('text')
      .attr('class', 'bar-drag-ghost-text')
      .attr('x', dragState.x1 + dragState.barW / 2)
      .attr('y', ghostY + dragState.barH / 2)
      .text(dragState.fl.fltno);

    const rowIdx = pixelYToRowIdx(svgY);
    dragState.targetRowIdx = (rowIdx >= 0 && rowIdx < totalRows) ? rowIdx : null;
    if (dragState.targetRowIdx !== null) {
      dragLayer.append('rect')
        .attr('class', 'row-drop-highlight')
        .attr('x', MARGIN.left)
        .attr('y', MARGIN.top + rowOffsets[dragState.targetRowIdx] - scrollY)
        .attr('width', chartW - MARGIN.left - MARGIN.right)
        .attr('height', rowHeights[dragState.targetRowIdx]);
    }

    const edgeZone = 40;
    if (svgY < MARGIN.top + edgeZone) dragState.autoScrollDir = -1;
    else if (svgY > containerH - edgeZone) dragState.autoScrollDir = 1;
    else dragState.autoScrollDir = 0;

    if (dragState.autoScrollDir !== 0 && !dragState.rafId) startAutoScroll();
    else if (dragState.autoScrollDir === 0 && dragState.rafId) stopAutoScroll();
  }

  function startAutoScroll() {
    const step = () => {
      if (!dragState || dragState.autoScrollDir === 0) { if (dragState) dragState.rafId = null; return; }
      scrollY += dragState.autoScrollDir * 15;
      const maxScrollY = Math.max(0, MARGIN.top + rowOffsets[totalRows] + MARGIN.bottom - containerH);
      scrollY = Math.max(0, Math.min(scrollY, maxScrollY));
      redrawAll();
      updateGhost();
      dragState.rafId = requestAnimationFrame(step);
    };
    dragState.rafId = requestAnimationFrame(step);
  }

  function stopAutoScroll() {
    if (dragState && dragState.rafId) {
      cancelAnimationFrame(dragState.rafId);
      dragState.rafId = null;
    }
  }

  // 초기 렌더링
  redrawAll();

  // --- 커스텀 휠 핸들러 ---
  // svgNode(#barchart-svg)는 redrawAll()에서 자식만 지워질 뿐 재생성되지 않으므로,
  // renderBarchart() 재호출 시 이전 리스너를 제거하지 않으면 계속 누적되어
  // 휠 이벤트마다 redrawAll()이 중복 호출되며 버퍼링이 점점 심해진다.
  if (_wheelHandler) svgNode.removeEventListener('wheel', _wheelHandler);

  _wheelHandler = (event) => {
    event.preventDefault();

    if (event.ctrlKey || event.metaKey) {
      const zoomFactor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
      xZoom = Math.max(0.3, Math.min(15, xZoom * zoomFactor));
      yZoom = Math.max(0.3, Math.min(5, yZoom * zoomFactor));
      redrawAll();
    } else {
      scrollY += event.deltaY;
      redrawAll();
    }
    if (dragState) updateGhost();
  };

  svgNode.addEventListener('wheel', _wheelHandler, { passive: false });

  // --- 키보드 핸들러 (방향키 스크롤 + Ctrl+방향키 줌) ---
  if (_keydownHandler) {
    document.removeEventListener('keydown', _keydownHandler);
  }

  _keydownHandler = (event) => {
    if (dragState) return;
    const scrollStep = 80;

    if (event.ctrlKey || event.metaKey) {
      switch (event.key) {
        case 'ArrowRight':
          event.preventDefault();
          xZoom = Math.max(0.3, Math.min(15, xZoom * 1.15));
          redrawAll();
          break;
        case 'ArrowLeft':
          event.preventDefault();
          xZoom = Math.max(0.3, Math.min(15, xZoom / 1.15));
          redrawAll();
          break;
        case 'ArrowUp':
          event.preventDefault();
          yZoom = Math.max(0.3, Math.min(5, yZoom * 1.15));
          redrawAll();
          break;
        case 'ArrowDown':
          event.preventDefault();
          yZoom = Math.max(0.3, Math.min(5, yZoom / 1.15));
          redrawAll();
          break;
      }
    } else {
      switch (event.key) {
        case 'ArrowLeft':
          event.preventDefault();
          xOffset += scrollStep;
          redrawAll();
          break;
        case 'ArrowRight':
          event.preventDefault();
          xOffset -= scrollStep;
          redrawAll();
          break;
        case 'ArrowUp':
          event.preventDefault();
          scrollY -= scrollStep;
          redrawAll();
          break;
        case 'ArrowDown':
          event.preventDefault();
          scrollY += scrollStep;
          redrawAll();
          break;
      }
    }
  };

  document.addEventListener('keydown', _keydownHandler);

  // --- 기번 재배정 드래그 (window 레벨 mousemove/mouseup) ---
  if (_dragMoveHandler) window.removeEventListener('mousemove', _dragMoveHandler);
  if (_dragUpHandler) window.removeEventListener('mouseup', _dragUpHandler);

  _dragMoveHandler = (event) => {
    if (!dragState) return;
    dragState.lastClientY = event.clientY;
    if (!dragState.moved && Math.abs(event.clientY - dragState.startClientY) > 4) {
      dragState.moved = true;
      document.body.classList.add('dragging-acno');
    }
    if (dragState.moved) updateGhost();
  };

  _dragUpHandler = () => {
    if (!dragState) return;
    stopAutoScroll();
    const { moved, targetRowIdx, sourceRowIdx, fl } = dragState;
    dragLayer.selectAll('*').remove();
    document.body.classList.remove('dragging-acno');
    dragState = null;
    if (!moved) return;
    if (targetRowIdx === null || targetRowIdx === sourceRowIdx) return;
    const targetAircraft = aircraft[targetRowIdx];
    // CANCEL 행(맨 위, isCancelRow)으로 드롭한 경우 acnoList상 표시값은 'CANCEL'
    // 문자열이지만, 실제로는 비운항 처리(Acno='')를 의미하므로 빈 문자열로 전달한다.
    const targetAcno = targetAircraft.isCancelRow ? '' : targetAircraft.acno;
    if (targetAcno === undefined || targetAcno === null) return;
    reassignAcno(fl.row_id, targetAcno);
  };

  window.addEventListener('mousemove', _dragMoveHandler);
  window.addEventListener('mouseup', _dragUpHandler);
}

function getCurrentBarchartData() {
  return _currentData;
}

function formatKST(isoStr) {
  if (!isoStr) return '-';
  const d = new Date(isoStr);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${d.getMonth()+1}/${d.getDate()} ${hh}:${mm}`;
}

// 바차트 SVG를 전체 범위(줌/스크롤 리셋) 상태로 JPEG 이미지로 저장한다.
// settle 콜백은 성공/실패/조기종료 모든 경로에서 정확히 한 번 호출된다(버튼 상태 복원용).
function exportBarchartAsJpeg(settle) {
  const done = typeof settle === 'function' ? settle : () => {};

  if (!_currentData || !_currentData.aircraft || !_currentData.aircraft.length) {
    if (typeof showError === 'function') showError('표출할 기재가 없습니다');
    done();
    return;
  }

  const origXZoom = _xZoom, origYZoom = _yZoom, origScrollY = _scrollY, origXOffset = _xOffset;
  const svgNode = document.getElementById('barchart-svg');
  const container = document.getElementById('barchart-container');
  const origContainerWidth = container.style.width;
  let svgString, width, height;

  try {
    // 세로(Y)는 항상 전체 기재 행이 스크롤 없이 다 들어가도록 yZoom=1로 고정한다(요청 사항).
    // 가로(X)는 사용자가 Ctrl+방향키/휠로 맞춰둔 배율(xZoom)의 막대 폭(픽셀 밀도)을 그대로
    // 유지하되, 가로 스크롤 없이 전체 시간축이 다 보이도록 컨테이너 폭 자체를 그 배율만큼
    // 넓힌다 — 그래야 편명이 잘리지 않으면서도 전체 범위를 담을 수 있다.
    const baseChartW = Math.max(container.clientWidth, 1400);
    const baseTotalXWidth = baseChartW - MARGIN.left - MARGIN.right;
    const exportContainerWidth = baseTotalXWidth * origXZoom + MARGIN.left + MARGIN.right;
    container.style.width = `${exportContainerWidth}px`;

    _xZoom = 1; _yZoom = 1; _scrollY = 0; _xOffset = 0;
    renderBarchart(_currentData);

    width = parseFloat(svgNode.getAttribute('width'));
    height = parseFloat(svgNode.getAttribute('height'));

    const clonedSvg = svgNode.cloneNode(true);
    clonedSvg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');

    // 외부 stylesheet(style.css) 클래스에만 의존하는 스타일은 canvas 래스터화 시 적용되지 않으므로
    // 실제 화면(reset 렌더링 직후)의 계산된 값을 샘플링해 <style>로 주입한다.
    const styleEl = document.createElementNS('http://www.w3.org/2000/svg', 'style');
    styleEl.textContent = buildExportStyleText(svgNode);
    const defs = clonedSvg.querySelector('defs');
    defs.appendChild(styleEl);

    // 배경색(현재 화면과 동일) — JPEG는 투명을 지원하지 않으므로 명시적 rect로 채운다.
    const bgColor = getComputedStyle(document.getElementById('barchart-area')).backgroundColor || '#f8fafc';
    const bgRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    bgRect.setAttribute('x', '0');
    bgRect.setAttribute('y', '0');
    bgRect.setAttribute('width', String(width));
    bgRect.setAttribute('height', String(height));
    bgRect.setAttribute('fill', bgColor);
    clonedSvg.insertBefore(bgRect, clonedSvg.firstChild);

    svgString = new XMLSerializer().serializeToString(clonedSvg);
  } finally {
    // renderBarchart() 재호출 사이에 await/setTimeout이 없어 브라우저가 리셋된 중간 상태를
    // 화면에 페인트할 기회가 없으므로, 원래 줌/스크롤/컨테이너 폭으로 복원해도 시각적
    // flash가 발생하지 않는다.
    container.style.width = origContainerWidth;
    _xZoom = origXZoom; _yZoom = origYZoom; _scrollY = origScrollY; _xOffset = origXOffset;
    renderBarchart(_currentData);
  }

  downloadSvgAsJpeg(svgString, width, height, done);
}

// 인라인 attr로 지정되지 않고 style.css 클래스 규칙에만 의존하는 스타일 목록.
// 각 selector에 해당하는 요소가 현재 데이터에 없으면(예: 연결 오류 없음) fallback 값을 사용한다.
function buildExportStyleText(liveSvg) {
  const rules = [
    { selector: '.bar-navy', props: { fill: '#1d4ed8' } },
    { selector: '.bar-cobalt', props: { fill: '#3b82f6' } },
    { selector: '.bar-gray', props: { fill: '#6b7280' } },
    { selector: '.bar-error', props: { stroke: '#ef4444', 'stroke-width': '2.5px' } },
    { selector: '.bar-error-outline', props: { fill: 'none', stroke: '#ef4444', 'stroke-width': '2.5px' } },
    { selector: '.bar-changed-outline', props: { fill: 'none', stroke: '#84cc16', 'stroke-width': '2.5px' } },
    { selector: '.bar-delay', props: { fill: '#ef4444' } },
    { selector: '.bar-text', props: { fill: '#ffffff', 'font-size': '11px', 'font-weight': '600', 'text-anchor': 'middle', 'dominant-baseline': 'middle' } },
    { selector: '.airport-label', props: { fill: '#374151', 'font-size': '10px' } },
    { selector: '.gt-label', props: { 'font-size': '10px', 'text-anchor': 'middle' } },
    { selector: '.x-axis text', props: { fill: '#6b7280', 'font-size': '10px' } },
  ];

  let css = `text { font-family: ${getComputedStyle(document.body).fontFamily || "'Segoe UI', sans-serif"}; }\n`;
  for (const rule of rules) {
    const el = liveSvg.querySelector(rule.selector);
    const decls = [];
    for (const prop of Object.keys(rule.props)) {
      let value = rule.props[prop];
      if (el) {
        const computed = getComputedStyle(el).getPropertyValue(prop);
        if (computed) value = computed;
      }
      decls.push(`${prop}:${value}`);
    }
    css += `${rule.selector} { ${decls.join(';')} }\n`;
  }
  return css;
}

// SVG 문자열을 고해상도 캔버스에 그려 JPEG로 다운로드한다.
function downloadSvgAsJpeg(svgString, width, height, done) {
  const svgBlob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
  const svgUrl = URL.createObjectURL(svgBlob);
  const img = new Image();

  img.onload = () => {
    URL.revokeObjectURL(svgUrl);

    // 세로로 긴 대량 기재 데이터(예: 수백 대)에서도 가로/세로 배율이 항상 동일하게 유지되도록
    // (한쪽만 클램프되면 이미지가 찌그러짐) 두 축과 총 픽셀수 제약을 모두 만족할 때까지 균일하게 줄인다.
    let scale = EXPORT_SCALE;
    while (scale > 0.1 && (
      width * scale > EXPORT_MAX_CANVAS_DIM ||
      height * scale > EXPORT_MAX_CANVAS_DIM ||
      width * height * scale * scale > EXPORT_MAX_CANVAS_PIXELS
    )) {
      scale -= 0.1;
    }

    const canvas = document.createElement('canvas');
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);

    const ctx = canvas.getContext('2d');
    ctx.scale(canvas.width / width, canvas.height / height);
    ctx.drawImage(img, 0, 0, width, height);

    canvas.toBlob((blob) => {
      if (!blob) { done(); return; }
      const jpegUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const now = new Date();
      const stamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`
        + `${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`;
      const dateVal = (document.getElementById('query-date-input') || {}).value || '';
      a.href = jpegUrl;
      a.download = `바차트_${dateVal}_${stamp}.jpg`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(jpegUrl);
      done();
    }, 'image/jpeg', 0.92);
  };

  img.onerror = () => {
    URL.revokeObjectURL(svgUrl);
    if (typeof showError === 'function') showError('이미지 생성에 실패했습니다');
    done();
  };

  img.src = svgUrl;
}

function positionTooltip(event, tooltip) {
  const tw = tooltip.offsetWidth || 200;
  const th = tooltip.offsetHeight || 120;
  let left = event.clientX + 12;
  let top = event.clientY + 12;
  if (left + tw > window.innerWidth - 10) left = event.clientX - tw - 12;
  if (top + th > window.innerHeight - 10) top = event.clientY - th - 12;
  // 창 폭보다 툴팁이 넓거나(작은 창) 마우스가 가장자리 가까이 있으면 반전만으로는
  // 화면 밖으로 나갈 수 있으므로, 좌/우 뒤집기 후에도 항상 뷰포트 안쪽으로 고정한다.
  left = Math.max(10, Math.min(left, window.innerWidth - tw - 10));
  top = Math.max(10, Math.min(top, window.innerHeight - th - 10));
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}
