const unitToggle = document.querySelector('#unitToggle');
let mmol = false;
window.latestGlucose = 112;
let signalHistoryData = {};
let currentSignal = null;
let currentHistoryRange = 'today';
const signalInfo = {
  glucose: { title: 'Glucose', kind: 'line', unit: 'mg/dL' },
  heart_rate: { title: 'Heart rate', kind: 'line', unit: 'bpm' },
  skin_response: { title: 'Skin response', kind: 'line', unit: 'μS' },
  movement: { title: 'Movement', kind: 'bar', unit: 'steps' },
  sleep: { title: 'Sleep', kind: 'bar', unit: 'hours' }
};
const mealStorageKey = 'wearables-meal-times-v1';
let mealLogs = loadMealLogs();

document.querySelector('#today').textContent = new Intl.DateTimeFormat(undefined, {
  weekday: 'long', month: 'long', day: 'numeric'
}).format(new Date()).toUpperCase();

const chart = {
  width: 340,
  height: 114,
  min: 40,
  max: 250,
  hours: 6,
  low: 70,
  high: 180
};
const svgNS = 'http://www.w3.org/2000/svg';
const targetBand = document.querySelector('#targetBand');
const chartY = value => ((chart.max - value) / (chart.max - chart.min)) * chart.height;
targetBand.setAttribute('d', `M0 ${chartY(chart.high)} H${chart.width} V${chartY(chart.low)} H0Z`);
let glucoseHistory = [];
let demoSample = null;
let glucoseChartEnd = null;

function updateUnits() {
  const label = mmol ? 'mmol/L' : 'mg/dL';
  unitToggle.innerHTML = `${label} <span>⌄</span>`;
  document.querySelector('#settingsUnitToggle').innerHTML = `${label} <span>⌄</span>`;
  document.querySelector('#unit').textContent = label;
  document.querySelector('#signalsUnit').textContent = label;
  const value = window.latestGlucose;
  const display = Number.isFinite(value) ? (mmol ? (value / 18.016).toFixed(1) : Math.round(value)) : '—';
  document.querySelector('#glucose').textContent = display;
  document.querySelector('#signalsGlucose').textContent = display;
  document.querySelector('#rangeLegend').innerHTML = mmol
    ? 'Low &lt;3.9 mmol/L <span>·</span> High &gt;10.0 mmol/L'
    : 'Low &lt;70 mg/dL <span>·</span> High &gt;180 mg/dL';
  if (currentSignal) renderSignalChart();
  if (mealLogs.length) renderMealResponse();
}

function renderSignal(value, unit, digits, ...selectors) {
  const reading = Number.isFinite(value) ? `${value.toFixed(digits)} <small>${unit}</small>` : 'No data';
  for (const selector of selectors) {
    document.querySelector(selector).innerHTML = reading;
  }
}

const summaryLabels = new Map([
  ['ok', 'Good data'],
  ['low_confidence', 'Low confidence'],
  ['suppressed', 'Insight withheld']
]);

function renderHomeInsight(label, description, source) {
  document.querySelector('#homeInsightStatus').textContent = label;
  document.querySelector('#homeInsightCopy').textContent = description;
  document.querySelector('#homeInsightTime').textContent = source;
}

function renderGlucoseHistory(history, chartEnd) {
  if (Array.isArray(history)) glucoseHistory = history;
  if (Number.isFinite(chartEnd)) glucoseChartEnd = chartEnd;
  const fallback = demoSample && glucoseHistory.length < 2
    ? [
        { t: demoSample.t - 5 * 3600, mgdl: 116, quality: 1 },
        { t: demoSample.t + 23 * 60, mgdl: 112, quality: 1 }
      ]
    : glucoseHistory;
  const source = demoSample ? [...fallback, demoSample].sort((a, b) => a.t - b.t) : glucoseHistory;
  const now = glucoseChartEnd ?? Date.now() / 1000;
  const span = chart.hours * 3600;
  const samples = source
    .filter(sample => Number.isFinite(sample.t) && Number.isFinite(sample.mgdl)
      && (sample.quality == null || sample.quality >= 0.5)
      && sample.t >= now - span && sample.t <= now)
    .sort((a, b) => a.t - b.t);
  if (samples.length < 2) {
    document.querySelector('#glucoseLine').setAttribute('d', '');
    document.querySelector('#glucoseArea').setAttribute('d', '');
    document.querySelector('#latestDot').setAttribute('visibility', 'hidden');
    document.querySelector('#glucoseFlags').replaceChildren();
    document.querySelector('#flagSummary').textContent = 'Not enough readings to draw a glucose trend.';
    return;
  }

  const axisLabels = document.querySelectorAll('.chart-times span');
  [6, 4.5, 3, 1.5, 0].forEach((hoursAgo, index) => {
    const labelTime = new Date((now - hoursAgo * 3600) * 1000);
    axisLabels[index].textContent = index === 4 ? 'LATEST' : labelTime.toLocaleTimeString([], { hour: 'numeric' });
  });

  const points = samples.map(sample => ({
    sample,
    x: Math.max(0, Math.min(chart.width, ((sample.t - (now - span)) / span) * chart.width)),
    y: Math.max(0, Math.min(chart.height, chartY(sample.mgdl)))
  }));
  const line = points.map((point, i) => `${i ? 'L' : 'M'}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ');
  document.querySelector('#glucoseLine').setAttribute('d', line);
  document.querySelector('#glucoseArea').setAttribute(
    'd', `${line} L${points.at(-1).x.toFixed(1)} ${chart.height} L${points[0].x.toFixed(1)} ${chart.height} Z`
  );
  const latest = points.at(-1);
  document.querySelector('#latestDot').setAttribute('visibility', 'visible');
  document.querySelector('#latestDot').setAttribute('cx', latest.x.toFixed(1));
  document.querySelector('#latestDot').setAttribute('cy', latest.y.toFixed(1));

  const flags = document.querySelector('#glucoseFlags');
  flags.replaceChildren();
  let previousFlag = null;
  let highCount = 0;
  let lowCount = 0;
  for (const point of points) {
    const flag = point.sample.mgdl < chart.low ? 'low' : point.sample.mgdl > chart.high ? 'high' : null;
    if (!flag) {
      previousFlag = null;
      continue;
    }
    if (flag === 'low') lowCount++;
    else highCount++;

    const marker = document.createElementNS(svgNS, 'circle');
    marker.setAttribute('cx', point.x.toFixed(1));
    marker.setAttribute('cy', point.y.toFixed(1));
    marker.setAttribute('r', '4.5');
    marker.setAttribute('class', `flag-marker ${flag}`);
    const time = new Date(point.sample.t * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    const title = document.createElementNS(svgNS, 'title');
    title.textContent = point.sample.demo
      ? `Simulated ${flag} preview: ${Math.round(point.sample.mgdl)} mg/dL at ${time}. Not sensor data.`
      : `${flag === 'low' ? 'Low' : 'High'} glucose: ${Math.round(point.sample.mgdl)} mg/dL at ${time}`;
    marker.append(title);
    flags.append(marker);

    if (flag !== previousFlag) {
      const label = document.createElementNS(svgNS, 'text');
      label.setAttribute('x', Math.max(18, Math.min(chart.width - 18, point.x)).toFixed(1));
      label.setAttribute('y', (point.y < 22 ? point.y + 17 : point.y - 9).toFixed(1));
      label.setAttribute('text-anchor', 'middle');
      label.setAttribute('class', `flag-label ${flag}`);
      label.textContent = flag === 'low' ? 'LOW' : 'HIGH';
      flags.append(label);
    }
    previousFlag = flag;
  }
  const summary = highCount || lowCount
    ? `${highCount} high and ${lowCount} low readings in the displayed window.`
    : 'No displayed readings below 70 or above 180 mg/dL.';
  document.querySelector('#flagSummary').textContent = demoSample ? `${summary} Includes a simulated preview only; it is not sensor data and is not saved.` : summary;
  document.querySelector('.chart').setAttribute(
    'aria-label', `Six-hour glucose trend. ${summary} Readings below 70 mg/dL are marked Low; readings above 180 mg/dL are marked High.`
  );
}

function previewFlag(level) {
  demoSample = {
    t: Date.now() / 1000 - 23 * 60,
    mgdl: level === 'low' ? 65 : 190,
    quality: 1,
    demo: true
  };
  document.querySelector('#previewNote').hidden = false;
  document.querySelector('#clearPreview').hidden = false;
  document.querySelector('#previewLow').setAttribute('aria-pressed', String(level === 'low'));
  document.querySelector('#previewHigh').setAttribute('aria-pressed', String(level === 'high'));
  renderGlucoseHistory();
}

function clearPreview() {
  demoSample = null;
  document.querySelector('#previewNote').hidden = true;
  document.querySelector('#clearPreview').hidden = true;
  document.querySelector('#previewLow').setAttribute('aria-pressed', 'false');
  document.querySelector('#previewHigh').setAttribute('aria-pressed', 'false');
  renderGlucoseHistory();
}

unitToggle.addEventListener('click', () => { mmol = !mmol; updateUnits(); });
document.querySelector('#settingsUnitToggle').addEventListener('click', () => { mmol = !mmol; updateUnits(); });
document.querySelector('#previewLow').addEventListener('click', () => previewFlag('low'));
document.querySelector('#previewHigh').addEventListener('click', () => previewFlag('high'));
document.querySelector('#clearPreview').addEventListener('click', clearPreview);

const toast = document.querySelector('#toast');
let timer;
function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(timer);
  timer = setTimeout(() => toast.classList.remove('show'), 2300);
}

function renderPatternList(patterns) {
  const list = document.querySelector('#patternList');
  const count = document.querySelector('#patternCount');
  list.replaceChildren();
  const sorted = Array.isArray(patterns)
    ? [...patterns].filter(item => Number.isFinite(item.timestamp)).sort((a, b) => b.timestamp - a.timestamp)
    : [];
  count.textContent = `${sorted.length} observed pattern${sorted.length === 1 ? '' : 's'}`;
  if (!sorted.length) {
    const empty = document.createElement('li');
    empty.className = 'pattern-empty';
    empty.textContent = 'No classifiable glucose patterns are available in this data window.';
    list.append(empty);
    return;
  }

  for (const item of sorted) {
    const entry = document.createElement('li');
    entry.className = 'pattern-row';
    const content = document.createElement('div');
    const description = document.createElement('p');
    description.className = 'pattern-description';
    description.textContent = item.description;
    const glucose = document.createElement('div');
    glucose.className = 'pattern-reading';
    const mgdl = Number(item.mgdl);
    glucose.textContent = Number.isFinite(mgdl)
      ? `${mmol ? (mgdl / 18.016).toFixed(1) : Math.round(mgdl)} ${mmol ? 'mmol/L' : 'mg/dL'}`
      : 'Reading unavailable';
    content.append(description, glucose);

    const meta = document.createElement('div');
    meta.className = 'pattern-meta';
    const status = document.createElement('span');
    const label = String(item.status || 'Observed');
    status.className = `pattern-status ${label.toLowerCase()}`;
    status.textContent = label;
    const sourceTime = item.timestamp_original || new Date(item.timestamp * 1000).toISOString();
    const instant = new Date(sourceTime);
    const time = document.createElement('time');
    time.dateTime = sourceTime;
    if (Number.isNaN(instant.getTime())) {
      time.textContent = sourceTime;
    } else {
      const date = document.createElement('span');
      date.textContent = instant.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
      const clock = document.createElement('span');
      clock.textContent = instant.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' });
      time.append(date, clock);
    }
    meta.append(status, time);
    entry.append(content, meta);
    list.append(entry);
  }
}

function createAnalyticsCard(item) {
  const card = document.createElement('article');
  card.className = 'analytics-card';
  const top = document.createElement('div');
  top.className = 'analytics-card-top';
  const title = document.createElement('h2');
  title.textContent = item.title || 'Glucose insight';
  const category = document.createElement('span');
  category.className = 'analytics-category';
  category.textContent = String(item.category || 'insight').replaceAll('_', ' ');
  top.append(title, category);
  const message = document.createElement('p');
  message.textContent = item.message || '';
  card.append(top, message);
  if (Number.isFinite(item.sample_count)) {
    const sampleMeta = document.createElement('small');
    sampleMeta.className = 'analytics-meta';
    sampleMeta.textContent = `Based on ${item.sample_count} available readings`;
    card.append(sampleMeta);
  }
  return card;
}

function appendInsightGroup(list, label, entries) {
  if (!entries.length) return;
  const group = document.createElement('details');
  group.className = 'insight-group';
  const summary = document.createElement('summary');
  summary.textContent = `${label} (${entries.length})`;
  const content = document.createElement('div');
  content.className = 'insight-group-content';
  entries.forEach(item => content.append(createAnalyticsCard(item)));
  group.append(summary, content);
  list.append(group);
}

function renderInsightList(insights) {
  const list = document.querySelector('#insightList');
  list.replaceChildren();
  const entries = Array.isArray(insights) ? insights : [];
  if (!entries.length) {
    const empty = document.createElement('p');
    empty.className = 'pattern-empty';
    empty.textContent = 'No additional insight is available yet. Trend events need a recent 30-minute window; recurring patterns and daily comparisons need readings across multiple dates.';
    list.append(empty);
    return;
  }

  const featuredCategories = ['trend', 'time_in_range', 'daily_comparison', 'variability'];
  const featured = featuredCategories
    .map(category => entries.find(item => String(item.category || '').toLowerCase() === category))
    .filter(Boolean);
  const featuredSet = new Set(featured);
  featured.forEach(item => list.append(createAnalyticsCard(item)));

  const remaining = entries.filter(item => !featuredSet.has(item));
  const changeEvents = remaining.filter(item =>
    String(item.category || '').toLowerCase() === 'event' || /significant glucose change/i.test(item.title || '')
  );
  const eventSet = new Set(changeEvents);
  const otherInsights = remaining.filter(item => !eventSet.has(item));
  appendInsightGroup(list, 'More summaries', otherInsights);
  appendInsightGroup(list, 'Glucose changes', changeEvents);
}

function loadMealLogs() {
  try {
    const saved = JSON.parse(localStorage.getItem(mealStorageKey) || '[]');
    return Array.isArray(saved) ? saved.filter(item => item && Number.isFinite(item.t) && typeof item.type === 'string') : [];
  } catch (_) {
    return [];
  }
}

function saveMealLogs() {
  try {
    localStorage.setItem(mealStorageKey, JSON.stringify(mealLogs.slice(-100)));
  } catch (_) {
    showToast('Meal times could not be saved in this browser.');
  }
}

function formatGlucose(value) {
  return `${mmol ? (value / 18.016).toFixed(1) : Math.round(value)} ${mmol ? 'mmol/L' : 'mg/dL'}`;
}

function mealObservations() {
  const binSeconds = 5 * 60;
  const windowBins = 24;
  const minCoveredBins = 22;
  const now = Date.now() / 1000;
  const glucose = (signalHistoryData.glucose || [])
    .filter(point => point && Number.isFinite(point.t) && Number.isFinite(point.value)
      && (point.quality == null || point.quality >= 0.5))
    .sort((a, b) => a.t - b.t);
  return mealLogs.map(meal => {
    const end = meal.t + windowBins * binSeconds;
    if (now < end) return { meal, message: 'Collecting readings' };
    const baseline = glucose.filter(point => point.t < meal.t && point.t >= meal.t - 30 * 60).at(-1);
    const after = glucose.filter(point => point.t >= meal.t && point.t < end);
    const coveredBins = new Set(after.map(point => Math.floor((point.t - meal.t) / binSeconds))).size;
    const coverage = `${coveredBins} of ${windowBins} intervals`;
    if (!baseline) return { meal, message: `Insufficient data: no pre-meal reading · ${coverage}` };
    if (coveredBins < minCoveredBins) return { meal, message: `Insufficient data · ${coverage}` };
    const peak = after.reduce((best, point) => point.value > best.value ? point : best, after[0]);
    const change = peak.value - baseline.value;
    const sign = change >= 0 ? '+' : '−';
    return { meal, rise: change, minutesToPeak: (peak.t - meal.t) / 60,
      message: `Highest observed: ${formatGlucose(peak.value)} (${sign}${formatGlucose(Math.abs(change))}) · ${coverage}` };
  }).sort((a, b) => b.meal.t - a.meal.t);
}

function renderMealResponse() {
  const summary = document.querySelector('#mealResponseSummary');
  const list = document.querySelector('#mealLogList');
  if (!summary || !list) return;
  list.replaceChildren();
  if (!mealLogs.length) {
    summary.textContent = 'Log meal times to compare the pre-meal glucose reading with the highest reading in the following two hours.';
    return;
  }
  const observations = mealObservations();
  const complete = observations.filter(item => Number.isFinite(item.rise));
  if (complete.length) {
    const averageRise = complete.reduce((total, item) => total + item.rise, 0) / complete.length;
    const averageMinutes = complete.reduce((total, item) => total + item.minutesToPeak, 0) / complete.length;
    const sign = averageRise >= 0 ? '+' : '−';
    const shownRise = mmol ? Math.abs(averageRise / 18.016).toFixed(1) : Math.round(Math.abs(averageRise));
    summary.textContent = `Across ${complete.length} meal${complete.length === 1 ? '' : 's'} with enough data, the highest observed glucose averaged ${sign}${shownRise} ${mmol ? 'mmol/L' : 'mg/dL'} from baseline. It occurred an average of ${Math.round(averageMinutes)} minutes after the meal.`;
  } else {
    summary.textContent = 'A comparison needs a pre-meal reading and data in at least 22 of the next 24 five-minute intervals.';
  }
  for (const item of observations) {
    const row = document.createElement('li');
    const mealDate = new Date(item.meal.t * 1000);
    const mealTime = mealDate.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    const description = document.createElement('span');
    description.textContent = `${item.meal.type} · ${mealTime} — ${item.message}`;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'meal-remove';
    remove.textContent = 'Remove';
    remove.setAttribute('aria-label', `Remove ${item.meal.type} at ${mealTime}`);
    remove.addEventListener('click', () => {
      mealLogs = mealLogs.filter(meal => meal !== item.meal);
      saveMealLogs();
      renderMealResponse();
    });
    row.append(description, remove);
    list.append(row);
  }
}

function historyRangeStart(range) {
  const now = new Date();
  if (range === 'today') {
    now.setHours(0, 0, 0, 0);
    return now.getTime() / 1000;
  }
  return Date.now() / 1000 - (range === 'week' ? 7 : 30) * 86400;
}

function renderSignalChart() {
  const panel = document.querySelector('#signalChartPanel');
  if (!panel || !currentSignal) return;
  const info = signalInfo[currentSignal];
  const chart = document.querySelector('#signalChartSvg');
  const plot = document.querySelector('#signalChartPlot');
  const labels = document.querySelector('#signalChartLabels');
  const note = document.querySelector('#signalChartNote');
  document.querySelector('#signalChartTitle').textContent = info.title;
  document.querySelector('#signalChartKind').textContent = info.kind === 'line' ? 'LINE CHART' : 'BAR CHART';
  chart.setAttribute('aria-label', `${info.title} history, ${currentHistoryRange === 'today' ? 'today' : currentHistoryRange === 'week' ? 'one week' : 'one month'}`);
  document.querySelectorAll('.range-pills button').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.range === currentHistoryRange)));
  plot.replaceChildren();
  labels.replaceChildren();
  const now = Date.now() / 1000;
  let requestedStart = historyRangeStart(currentHistoryRange);
  if (currentSignal === 'sleep' && currentHistoryRange === 'today') {
    const lastNight = new Date();
    lastNight.setHours(18, 0, 0, 0);
    if (lastNight.getTime() / 1000 > now) lastNight.setDate(lastNight.getDate() - 1);
    requestedStart = lastNight.getTime() / 1000;
  }
  const points = (signalHistoryData[currentSignal] || [])
    .filter(point => Number.isFinite(point.t) && Number.isFinite(point.value) && point.t >= requestedStart && point.t <= now)
    .sort((a, b) => a.t - b.t);
  if (!points.length) {
    chart.hidden = true;
    note.textContent = `${info.title} history is not available for this time range.`;
    return;
  }
  chart.hidden = false;
  const first = points[0].t;
  if (first > requestedStart + 3600) {
    note.textContent = `Showing available readings since ${new Date(first * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' })}. Older history is not stored in this demo.`;
  } else {
    note.textContent = `Showing ${points.length} available readings. These charts describe the data and are not treatment guidance.`;
  }
  const grid = document.createElementNS(svgNS, 'path');
  grid.setAttribute('d', 'M10 20H330 M10 75H330 M10 130H330');
  grid.setAttribute('class', 'signal-chart-grid');
  plot.append(grid);
  if (info.kind === 'line') {
    const values = points.map(point => point.value);
    let low = Math.min(...values), high = Math.max(...values);
    if (low === high) { low -= 1; high += 1; }
    const pad = (high - low) * 0.08;
    low -= pad; high += pad;
    const timeSpan = Math.max(1, now - requestedStart);
    const coords = points.map(point => ({
      x: 10 + Math.max(0, Math.min(1, (point.t - requestedStart) / timeSpan)) * 320,
      y: 130 - (point.value - low) * 110 / (high - low)
    }));
    const line = document.createElementNS(svgNS, 'path');
    line.setAttribute('d', coords.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' '));
    line.setAttribute('class', `signal-line ${currentSignal}`);
    plot.append(line);
    const unitLabel = currentSignal === 'glucose' ? (mmol ? 'mmol/L' : 'mg/dL') : info.unit;
    note.textContent = `${Math.round(low)}–${Math.round(high)} ${unitLabel} displayed · ${points.length} readings. ` + note.textContent;
  } else {
    const groups = new Map();
    for (const point of points) {
      const date = new Date(point.t * 1000);
      const key = currentHistoryRange === 'today'
        ? `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}-${date.getHours()}`
        : `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
      if (!groups.has(key)) groups.set(key, { date, total: 0, count: 0 });
      const group = groups.get(key);
      group.total += currentSignal === 'sleep' ? point.value * 5 / 60 : point.value;
      group.count += 1;
    }
    const buckets = [...groups.values()];
    const values = buckets.map(item => item.total);
    const max = Math.max(...values, 1);
    const width = Math.max(3, 260 / buckets.length - 3);
    buckets.forEach((bucket, index) => {
      const rect = document.createElementNS(svgNS, 'rect');
      const barHeight = 105 * bucket.total / max;
      rect.setAttribute('x', (20 + index * 300 / buckets.length).toFixed(1));
      rect.setAttribute('y', (130 - barHeight).toFixed(1));
      rect.setAttribute('width', width.toFixed(1));
      rect.setAttribute('height', Math.max(1, barHeight).toFixed(1));
      rect.setAttribute('rx', '3');
      rect.setAttribute('class', `signal-bar ${currentSignal}`);
      const title = document.createElementNS(svgNS, 'title');
      title.textContent = `${bucket.date.toLocaleDateString([], { month: 'short', day: 'numeric', hour: currentHistoryRange === 'today' ? 'numeric' : undefined })}: ${currentSignal === 'sleep' ? bucket.total.toFixed(1) : Math.round(bucket.total)} ${info.unit}`;
      rect.append(title);
      plot.append(rect);
    });
    note.textContent = `${currentSignal === 'sleep' ? 'Sleep hours' : 'Steps'} by ${currentHistoryRange === 'today' ? 'hour' : 'day'} from available readings. ` + note.textContent;
  }
  const firstLabel = document.createElement('span');
  const labelOptions = currentHistoryRange === 'today'
    ? { hour: 'numeric', minute: '2-digit' }
    : { month: 'short', day: 'numeric' };
  firstLabel.textContent = new Date(points[0].t * 1000).toLocaleString([], labelOptions);
  const lastLabel = document.createElement('span');
  lastLabel.textContent = new Date(points.at(-1).t * 1000).toLocaleString([], labelOptions);
  labels.append(firstLabel, lastLabel);
}

function updateSimulatedActivityValues() {
  const movement = (signalHistoryData.movement || []).filter(point => Number.isFinite(point.t) && Number.isFinite(point.value));
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todaySteps = movement.filter(point => point.t >= today.getTime() / 1000)
    .reduce((total, point) => total + point.value, 0);
  if (todaySteps > 0) {
    ['#homeMovement', '#signalsMovement'].forEach(selector => {
      document.querySelector(selector).innerHTML = `${Math.round(todaySteps).toLocaleString()} <small>steps</small>`;
    });
  }
  const sleep = (signalHistoryData.sleep || []).filter(point => Number.isFinite(point.t) && Number.isFinite(point.value));
  const sleepStart = new Date();
  sleepStart.setHours(18, 0, 0, 0);
  if (sleepStart.getTime() > Date.now()) sleepStart.setDate(sleepStart.getDate() - 1);
  const sleepMinutes = sleep.filter(point => point.t >= sleepStart.getTime() / 1000 && point.t <= Date.now() / 1000)
    .reduce((total, point) => total + point.value * 5, 0);
  if (sleepMinutes > 0) {
    const hours = Math.floor(sleepMinutes / 60);
    const minutes = Math.round(sleepMinutes % 60);
    ['#homeSleep', '#signalsSleep'].forEach(selector => {
      document.querySelector(selector).textContent = `${hours}h ${minutes}m`;
    });
  }
}

function setDefaultMealTime() {
  const input = document.querySelector('#mealTime');
  if (!input) return;
  const now = new Date();
  input.value = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  input.max = input.value;
}

document.querySelectorAll('.signal-launch').forEach(button => button.addEventListener('click', () => {
  currentSignal = button.dataset.signal;
  currentHistoryRange = 'today';
  document.querySelectorAll('.signal-launch').forEach(item => item.setAttribute('aria-expanded', String(item === button)));
  document.querySelector('#signalChartPanel').hidden = false;
  renderSignalChart();
  document.querySelector('#signalChartPanel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}));
document.querySelectorAll('.range-pills button').forEach(button => button.addEventListener('click', () => {
  currentHistoryRange = button.dataset.range;
  renderSignalChart();
}));
document.querySelector('#closeSignalChart').addEventListener('click', () => {
  document.querySelector('#signalChartPanel').hidden = true;
  document.querySelectorAll('.signal-launch').forEach(button => button.setAttribute('aria-expanded', 'false'));
  currentSignal = null;
});
document.querySelector('#mealLogForm').addEventListener('submit', event => {
  event.preventDefault();
  const t = new Date(document.querySelector('#mealTime').value).getTime() / 1000;
  if (!Number.isFinite(t) || t > Date.now() / 1000) { showToast('Choose a meal time in the past.'); return; }
  mealLogs.push({ type: document.querySelector('#mealType').value, t });
  mealLogs = mealLogs.slice(-100);
  saveMealLogs();
  renderMealResponse();
});
setDefaultMealTime();
renderMealResponse();

document.querySelector('#detailsBtn').addEventListener('click', () => showScreen('insightsScreen'));
function showScreen(id) {
  document.querySelectorAll('main').forEach(screen => { screen.hidden = screen.id !== id; });
  document.querySelectorAll('.tabbar a').forEach(link => link.classList.toggle('active', link.dataset.screen === id));
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
document.querySelectorAll('.tabbar a').forEach(link => link.addEventListener('click', event => {
  event.preventDefault();
  showScreen(link.dataset.screen);
}));

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('./service-worker.js', { updateViaCache: 'none' })
    .then(registration => registration.update()).catch(() => {}));
}

updateUnits();
fetch('./api/summary', { cache: 'no-store' })
  .then(async response => {
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || 'Dashboard data could not be loaded.');
      error.mode = data.mode;
      error.sourceLabel = data.source_label;
      throw error;
    }
    return data;
  })
  .then(data => {
    signalHistoryData = data.signal_history || {};
    renderMealResponse();
    if (currentSignal) renderSignalChart();
    if (data.disclaimer) document.querySelector('#disclaimerText').textContent = data.disclaimer;
    document.querySelector('#demoDataBadge').hidden = typeof data.mode === 'string' && data.mode.startsWith('dexcom_');
    renderGlucoseHistory(data.glucose_history, data.chart_end_t);
    renderPatternList(data.patterns);
    renderInsightList(data.insights);
    const isDexcom = typeof data.mode === 'string' && data.mode.startsWith('dexcom_');
    if (isDexcom) {
      const label = data.source_label || 'Dexcom';
      document.querySelector('.live').textContent = `${label} · API`;
      document.querySelector('#trendLabel').textContent = 'Trend unavailable';
      ['#homeHr', '#homeMovement', '#homeEda', '#homeSleep', '#signalsHr', '#signalsMovement', '#signalsEda', '#signalsSleep']
        .forEach(selector => { const node = document.querySelector(selector); if (node) node.textContent = '—'; });
      document.querySelectorAll('.dexcom-unavailable-note').forEach(node => { node.textContent = 'Not connected'; });
      document.querySelector('#signalsFootnote').textContent = 'Dexcom connection supplies glucose only; other signals are not connected.';
      document.querySelector('#previewControls').hidden = true;

      const insights = Array.isArray(data.insights) ? data.insights : [];
      const insightText = insights.length
        ? insights.slice(-3).map(item => item.message).join(' ')
        : (data.glucose_mgdl == null
          ? 'No glucose readings are available from this Dexcom account.'
          : 'No analytics insight was generated for the available glucose window.');
      const insightLabel = insights.length ? `${insights.length} pipeline insight${insights.length === 1 ? '' : 's'}` : 'No insight';
      const latestInsight = insights.at(-1);
      const insightTime = latestInsight
        ? new Date(latestInsight.timestamp * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
        : 'Shared glucose analytics';
      renderHomeInsight(insightLabel, insightText, insightTime);
    } else {
      updateSimulatedActivityValues();
      document.querySelector('.live').textContent = 'Simulated · Python pipeline';
      const label = summaryLabels.get(data.status);
      const description = typeof data.description === 'string' ? data.description.trim() : '';
      const disclaimer = typeof data.disclaimer === 'string' ? data.disclaimer.trim() : '';
      const summary = disclaimer && description.endsWith(disclaimer)
        ? description.slice(0, -disclaimer.length).trim()
        : description;
      renderHomeInsight(label || 'Data unavailable',
        (label && summary) || 'No signal summary is available.', 'Simulated window');
      renderSignal(data.heart_rate_bpm, 'bpm', 0, '#homeHr', '#signalsHr');
      renderSignal(data.eda_tonic_us, 'μS tonic', 1, '#homeEda', '#signalsEda');
    }
    window.latestGlucose = data.glucose_mgdl;
    updateUnits();
    if (Number.isFinite(data.glucose_mgdl)) {
      const age = Number.isFinite(data.glucose_age_seconds)
        ? `${Math.max(0, Math.round(data.glucose_age_seconds / 60))} min ago`
        : 'Time unavailable';
      document.querySelector('.card-foot b').textContent = age;
      document.querySelector('#signalsAge').textContent = age;
    } else {
      document.querySelector('.card-foot b').textContent = 'No reading';
      document.querySelector('#signalsAge').textContent = 'No reading available';
    }
  })
  .catch(error => {
    signalHistoryData = {};
    renderMealResponse();
    if (currentSignal) renderSignalChart();
    window.latestGlucose = null;
    updateUnits();
    document.querySelector('.live').textContent = 'Data unavailable';
    document.querySelector('.card-foot b').textContent = 'Unavailable';
    document.querySelector('#signalsAge').textContent = 'Unavailable';
    renderHomeInsight('Data unavailable', error.message || 'Dashboard data could not be loaded.', '');
    if (typeof error.mode === 'string' && error.mode.startsWith('dexcom_')) {
      document.querySelector('#demoDataBadge').hidden = true;
      document.querySelector('.live').textContent = `${error.sourceLabel || 'Dexcom'} unavailable`;
      document.querySelector('#trendLabel').textContent = 'Trend unavailable';
      ['#homeHr', '#homeMovement', '#homeEda', '#homeSleep', '#signalsHr', '#signalsMovement', '#signalsEda', '#signalsSleep']
        .forEach(selector => { const node = document.querySelector(selector); if (node) node.textContent = '—'; });
      document.querySelectorAll('.dexcom-unavailable-note').forEach(node => { node.textContent = 'Not connected'; });
      document.querySelector('#signalsFootnote').textContent = 'Dexcom connection supplies glucose only; other signals are not connected.';
      document.querySelector('#previewControls').hidden = true;
    } else {
      renderSignal(null, 'bpm', 0, '#homeHr', '#signalsHr');
      renderSignal(null, 'μS tonic', 1, '#homeEda', '#signalsEda');
    }
    renderGlucoseHistory([], null);
    renderPatternList([]);
    renderInsightList([]);
  });
