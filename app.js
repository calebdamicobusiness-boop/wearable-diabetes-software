const unitToggle = document.querySelector('#unitToggle');
let mmol = false;
window.latestGlucose = 112;

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
      document.querySelector('#signalsMiniChart').hidden = true;
      document.querySelector('#previewControls').hidden = true;

      const insights = Array.isArray(data.insights) ? data.insights : [];
      const insightText = insights.length
        ? insights.slice(-3).map(item => item.message).join(' ')
        : (data.glucose_mgdl == null
          ? 'No glucose readings are available from this Dexcom account.'
          : 'No analytics insight was generated for the available glucose window.');
      ['#homeInsightCopy', '#patternInsightCopy'].forEach(selector => {
        const node = document.querySelector(selector);
        if (node) node.textContent = insightText;
      });
      const insightLabel = insights.length ? `${insights.length} pipeline insight${insights.length === 1 ? '' : 's'}` : 'No insight';
      ['#homeInsightStatus', '#patternInsightStatus'].forEach(selector => {
        const node = document.querySelector(selector);
        if (node) node.textContent = insightLabel;
      });
      const latestInsight = insights.at(-1);
      const insightTime = latestInsight
        ? new Date(latestInsight.timestamp * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
        : 'Shared glucose analytics';
      ['#homeInsightTime', '#patternInsightTime'].forEach(selector => {
        const node = document.querySelector(selector);
        if (node) node.textContent = insightTime;
      });
    } else {
      document.querySelector('.live').textContent = 'Simulated · Python pipeline';
    }
    if (data.glucose_mgdl !== null && data.glucose_mgdl !== undefined) {
      window.latestGlucose = data.glucose_mgdl;
      updateUnits();
      const age = Math.max(0, Math.round(data.glucose_age_seconds / 60));
      document.querySelector('.card-foot b').textContent = `${age} min ago`;
      document.querySelector('#signalsAge').textContent = `${age} min ago`;
      if (!isDexcom) {
        document.querySelector('#homeHr').innerHTML = `${Math.round(data.heart_rate_bpm)} <small>bpm</small>`;
        document.querySelector('#homeEda').innerHTML = `${Number(data.eda_tonic_us).toFixed(1)} <small>μS tonic</small>`;
        document.querySelector('#signalsHr').innerHTML = `${Math.round(data.heart_rate_bpm)} <small>bpm</small>`;
        document.querySelector('#signalsEda').innerHTML = `${Number(data.eda_tonic_us).toFixed(1)} <small>μS tonic</small>`;
      }
    } else if (isDexcom) {
      window.latestGlucose = null;
      updateUnits();
      document.querySelector('.card-foot b').textContent = 'No reading';
      document.querySelector('#signalsAge').textContent = 'No reading available';
    }
  })
  .catch(error => {
    window.latestGlucose = null;
    updateUnits();
    document.querySelector('.live').textContent = 'Data unavailable';
    document.querySelector('.card-foot b').textContent = 'Unavailable';
    document.querySelector('#signalsAge').textContent = 'Unavailable';
    ['#homeInsightCopy', '#patternInsightCopy'].forEach(selector => {
      const node = document.querySelector(selector);
      if (node) node.textContent = error.message || 'Dashboard data could not be loaded.';
    });
    if (typeof error.mode === 'string' && error.mode.startsWith('dexcom_')) {
      document.querySelector('#demoDataBadge').hidden = true;
      document.querySelector('.live').textContent = `${error.sourceLabel || 'Dexcom'} unavailable`;
      document.querySelector('#trendLabel').textContent = 'Trend unavailable';
      ['#homeHr', '#homeMovement', '#homeEda', '#homeSleep', '#signalsHr', '#signalsMovement', '#signalsEda', '#signalsSleep']
        .forEach(selector => { const node = document.querySelector(selector); if (node) node.textContent = '—'; });
      document.querySelectorAll('.dexcom-unavailable-note').forEach(node => { node.textContent = 'Not connected'; });
      document.querySelector('#signalsFootnote').textContent = 'Dexcom connection supplies glucose only; other signals are not connected.';
      document.querySelector('#signalsMiniChart').hidden = true;
      document.querySelector('#previewControls').hidden = true;
      ['#homeInsightStatus', '#patternInsightStatus'].forEach(selector => {
        document.querySelector(selector).textContent = 'Data unavailable';
      });
    }
    renderGlucoseHistory([], null);
    renderPatternList([]);
    renderInsightList([]);
  });
