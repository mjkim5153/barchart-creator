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

let _zoomBehavior = null;
let _currentData = null;
let _keydownHandler = null;

function renderBarchart(data) {
  _currentData = data;
  const aircraft = data.aircraft || [];
  const tooltip = document.getElementById('tooltip');

  const container = document.getElementById('barchart-container');
  const containerW = container.clientWidth;
  const containerH = container.clientHeight;

  const totalRows = aircraft.length;
  const chartW = Math.max(containerW, 1400);

  // 줌 상태
  let xZoom = 1;
  let yZoom = 1;
  let scrollY = 0;

  // 데이터에서 최소/최대 날짜 산출
  let minDate = null;
  let maxDate = null;
  for (const ac of aircraft) {
    for (const fl of ac.flights) {
      if (fl.std_kst) {
        const d = new Date(fl.std_kst);
        if (!minDate || d < minDate) minDate = new Date(d);
        if (!maxDate || d > maxDate) maxDate = new Date(d);
      }
      if (fl.sta_kst) {
        const d = new Date(fl.sta_kst);
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

  function getCurrentXScale() {
    const totalXWidth = chartW - MARGIN.left - MARGIN.right;
    const scaledWidth = totalXWidth * xZoom;
    return d3.scaleTime()
      .domain([xStart, xEnd])
      .range([MARGIN.left, MARGIN.left + scaledWidth]);
  }

  let xOffset = 0;

  function getClampedXOffset(offset, xScale) {
    const rangeWidth = xScale.range()[1] - xScale.range()[0];
    const viewWidth = chartW - MARGIN.left - MARGIN.right;
    if (rangeWidth <= viewWidth) return 0;
    const minOffset = -(rangeWidth - viewWidth);
    return Math.max(minOffset, Math.min(0, offset));
  }

  function redrawAll() {
    const xScale = getCurrentXScale();
    const clampedOffset = getClampedXOffset(xOffset, xScale);
    xOffset = clampedOffset;

    const scaledRowH = getScaledRowHeight();
    const totalContentH = MARGIN.top + totalRows * scaledRowH + MARGIN.bottom;
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
      .attr('y', (d, i) => MARGIN.top + i * scaledRowH - scrollY)
      .attr('height', scaledRowH)
      .attr('fill', (d, i) => i % 2 === 1 ? '#d9d9d9' : 'transparent');

    // --- 행 구분선 ---
    rowLines.selectAll('line').data(acnoList).join('line')
      .attr('x1', MARGIN.left)
      .attr('x2', chartW - MARGIN.right)
      .attr('y1', (d, i) => MARGIN.top + (i + 1) * scaledRowH - scrollY)
      .attr('y2', (d, i) => MARGIN.top + (i + 1) * scaledRowH - scrollY)
      .attr('stroke', '#e5e7eb')
      .attr('stroke-width', 0.5);

    // --- Y축 ---
    yAxisGroup.selectAll('*').remove();
    acnoList.forEach((acno, idx) => {
      const ac = aircraft.find(a => a.acno === acno);
      const yPos = MARGIN.top + idx * scaledRowH - scrollY;
      if (yPos + scaledRowH < MARGIN.top - 20 || yPos > viewH) return;

      // Y축 라벨 영역 배경색 (교대 행)
      if (idx % 2 === 1) {
        yAxisGroup.append('rect')
          .attr('x', -MARGIN.left)
          .attr('y', yPos)
          .attr('width', MARGIN.left)
          .attr('height', scaledRowH)
          .attr('fill', '#d9d9d9');
      }

      yAxisGroup.append('text')
        .attr('x', -6)
        .attr('y', yPos + scaledRowH / 2)
        .attr('text-anchor', 'end')
        .attr('dominant-baseline', 'middle')
        .attr('fill', ac && ac.connection_error ? '#ef4444' : '#374151')
        .attr('font-weight', ac && ac.connection_error ? '700' : '400')
        .attr('font-size', '11px')
        .text(`${idx + 1} ${acno}`);
    });

    // --- BAR ---
    barGroup.selectAll('*').remove();

    const clipL = shiftedXScale(xStart);
    const clipR = shiftedXScale(xEnd);

    aircraft.forEach((ac, acIdx) => {
      const yBase = MARGIN.top + acIdx * scaledRowH - scrollY;
      const barY = yBase + (scaledRowH - BAR_HEIGHT * yZoom) / 2;
      const scaledBarH = Math.max(4, BAR_HEIGHT * yZoom);

      if (yBase + scaledRowH < MARGIN.top || yBase > viewH) return;

      ac.flights.forEach((fl, idx) => {
        if (!fl.std_kst || !fl.sta_kst) return;

        const std = new Date(fl.std_kst);
        const sta = new Date(fl.sta_kst);

        const x1Raw = shiftedXScale(std);
        const x2Raw = shiftedXScale(sta);
        const x1 = Math.max(x1Raw, clipL);
        const x2 = Math.min(x2Raw, clipR);
        if (x2 < clipL || x1 > clipR) return;
        const barW = Math.max(1, x2 - x1);

        const colorClass = fl.color === 'blue' ? 'bar-blue' : 'bar-orange';

        const barRect = barGroup.append('rect')
          .attr('class', `bar ${colorClass}${fl.connection_error ? ' bar-error' : ''}`)
          .attr('x', x1)
          .attr('y', barY)
          .attr('width', barW)
          .attr('height', scaledBarH)
          .attr('rx', 3)
          .style('cursor', 'pointer');

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

        // Ground Time
        if (showText && idx > 0 && fl.ground_time_before !== null) {
          const prevFl = ac.flights[idx - 1];
          if (prevFl.sta_kst) {
            const prevSta = new Date(prevFl.sta_kst);
            const gtX = (shiftedXScale(prevSta) + shiftedXScale(std)) / 2;
            barGroup.append('text')
              .attr('class', 'gt-label')
              .attr('x', gtX)
              .attr('y', barY + scaledBarH / 2)
              .text(`${fl.ground_time_before}분`);
          }
        }

        // 툴팁
        barRect.on('mousemove', (event) => {
          const gtText = fl.ground_time_before !== null ? `${fl.ground_time_before}분` : '-';
          tooltip.classList.remove('hidden');
          tooltip.innerHTML = `
            <div class="tt-title">${fl.fltno}</div>
            <div class="tt-row"><span class="tt-label">기번</span><span>${ac.acno}</span></div>
            <div class="tt-row"><span class="tt-label">출발</span><span>${fl.depstn}</span></div>
            <div class="tt-row"><span class="tt-label">도착</span><span>${fl.arrstn}</span></div>
            <div class="tt-row"><span class="tt-label">STD</span><span>${formatKST(fl.std_kst)}</span></div>
            <div class="tt-row"><span class="tt-label">STA</span><span>${formatKST(fl.sta_kst)}</span></div>
            <div class="tt-row"><span class="tt-label">BT</span><span>${fl.blocktime}분</span></div>
            <div class="tt-row"><span class="tt-label">GT</span><span>${gtText}</span></div>
            <div class="tt-row"><span class="tt-label">기종</span><span>${fl.actype}</span></div>
            <div class="tt-row"><span class="tt-label">상태</span><span>${fl.status}</span></div>
          `;
          positionTooltip(event, tooltip);
        }).on('mouseleave', () => {
          tooltip.classList.add('hidden');
        });
      });
    });
  }

  // 초기 렌더링
  redrawAll();

  // --- 커스텀 휠 핸들러 ---
  const svgNode = svg.node();
  svgNode.addEventListener('wheel', (event) => {
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
  }, { passive: false });

  // --- 키보드 핸들러 (방향키 스크롤 + Ctrl+방향키 줌) ---
  if (_keydownHandler) {
    document.removeEventListener('keydown', _keydownHandler);
  }

  _keydownHandler = (event) => {
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
}

function formatKST(isoStr) {
  if (!isoStr) return '-';
  const d = new Date(isoStr);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${d.getMonth()+1}/${d.getDate()} ${hh}:${mm}`;
}

function positionTooltip(event, tooltip) {
  const tw = tooltip.offsetWidth || 200;
  const th = tooltip.offsetHeight || 120;
  let left = event.clientX + 12;
  let top = event.clientY + 12;
  if (left + tw > window.innerWidth - 10) left = event.clientX - tw - 12;
  if (top + th > window.innerHeight - 10) top = event.clientY - th - 12;
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}
