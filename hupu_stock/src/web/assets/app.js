const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  overview: null,
  boards: [],
  selectedBoard: '',
  selectedData: null,
  history: [],
  filter: '全部',
  query: '',
  view: 'overview',
  requestToken: 0,
};

const STATE_STYLE = {
  '亢奋拥挤': 'risk-red',
  '恐慌拥挤': 'risk-orange',
  '新热启动': 'signal-blue',
  '噪音争吵': 'signal-purple',
  '样本不足': 'signal-muted',
  '低置信观察': 'signal-muted',
  '无强信号': 'signal-muted',
};

const METRICS = [
  { key: 'hot_score', label: '热度', className: 'metric-hot', note: '讨论活跃度相对强度' },
  { key: 'sent_score', label: '情绪', className: 'metric-sent', note: '正向情绪强度' },
  { key: 'crowding_score', label: '拥挤度', className: 'metric-crowd', note: '综合拥挤风险' },
  { key: 'coverage_score', label: '覆盖度', className: 'metric-coverage', note: '分析样本覆盖程度' },
];

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function svgElement(tag, attributes = {}) {
  const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
}

function replaceChildren(target, children) {
  target.replaceChildren(...children.filter(Boolean));
}

function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(1) : '—';
}

function formatPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : '—';
}

function stateClass(value) {
  return STATE_STYLE[value] || 'signal-muted';
}

function makeStateLabel(value) {
  return createElement('span', `state-label ${stateClass(value)}`, value || '无强信号');
}

function humanAge(source) {
  if (!source || source.age_hours == null) return '暂无';
  const hours = Number(source.age_hours);
  if (hours < 1) return '刚刚';
  if (hours < 24) return `${Math.round(hours)}小时前`;
  return `${Math.round(hours / 24)}天前`;
}

async function fetchJSON(url) {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`请求失败（HTTP ${response.status}）`);
  return response.json();
}

function renderHeader() {
  const overview = state.overview || {};
  $('#as-of-date').textContent = overview.as_of_date || '—';
  const sources = overview.health?.sources || {};
  [
    ['forum', 'source-forum'],
    ['analysis', 'source-analysis'],
    ['price', 'source-price'],
  ].forEach(([key, id]) => {
    const source = sources[key];
    const target = $(`#${id}`);
    target.classList.toggle('stale', !source?.fresh);
    $('b', target).textContent = humanAge(source);
    target.title = source?.latest ? `最近数据：${source.latest}` : '暂无数据';
  });
}

function filteredBoards() {
  const query = state.query.trim().toLocaleLowerCase('zh-CN');
  return state.boards.filter((board) => {
    const matchesState = state.filter === '全部' || board.state === state.filter;
    const matchesQuery = !query || String(board.board || '').toLocaleLowerCase('zh-CN').includes(query);
    return matchesState && matchesQuery;
  });
}

function renderSidebar() {
  const list = $('#sector-list');
  const boards = filteredBoards();
  const rows = boards.map((board) => {
    const button = createElement('button', 'sector-row');
    button.type = 'button';
    button.setAttribute('role', 'option');
    button.setAttribute('aria-selected', String(board.board === state.selectedBoard));
    if (board.board === state.selectedBoard) button.classList.add('selected');

    const copy = createElement('span', 'sector-row-copy');
    copy.append(
      createElement('strong', '', board.board || '未命名板块'),
      createElement('small', stateClass(board.state), board.state || '无强信号'),
    );
    const confidence = createElement('span', 'sector-row-confidence', board.confidence || '—');
    button.append(copy, confidence);
    button.addEventListener('click', () => selectBoard(board.board));
    return button;
  });

  if (!rows.length) {
    rows.push(createElement('p', 'sidebar-empty', '没有符合条件的板块'));
  }
  replaceChildren(list, rows);
  $('#sector-count').textContent = `${state.boards.length} 个板块`;
  $('#sidebar-updated').textContent = state.overview?.as_of_date ? `数据 ${state.overview.as_of_date}` : '尚未更新';
}

function renderSelectedSummary(data) {
  $('#selected-board').textContent = data?.board || state.selectedBoard || '选择板块';
  $('#selected-date').textContent = data?.date || state.overview?.as_of_date || '—';
  $('#current-state').replaceChildren(makeStateLabel(data?.state));

  const historyDays = Number(data?.history_days) || 0;
  const confidenceProgress = Math.min(100, Math.round((historyDays / 20) * 100));
  $('#current-confidence').textContent = `${data?.confidence || '冷启动'} · ${confidenceProgress}%`;
  $('#history-days').textContent = historyDays ? `${historyDays} 个数据日` : '—';
  $('#selected-summary').textContent = data
    ? `有效文本 ${formatNumber(data.effective_item_count)} · 独立作者 ${data.unique_authors ?? '—'}`
    : '该板块暂无分析数据。';
}

function renderMetrics(data) {
  const cards = METRICS.map((metric) => {
    const card = createElement('article', `metric-block ${metric.className}`);
    card.append(
      createElement('span', 'metric-label', metric.label),
      createElement('strong', 'metric-value', formatNumber(data?.[metric.key])),
      createElement('small', 'metric-note', metric.note),
    );
    return card;
  });
  replaceChildren($('#metric-grid'), cards);
}

function renderHistory(history) {
  const target = $('#history-chart');
  target.replaceChildren();
  if (!history.length) {
    target.append(createElement('p', 'panel-empty', '暂无历史数据'));
    return;
  }

  const rows = [...history].reverse();
  const width = 720;
  const height = 280;
  const pad = { top: 20, right: 20, bottom: 34, left: 42 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const x = (index) => pad.left + (rows.length === 1 ? plotWidth / 2 : (index / (rows.length - 1)) * plotWidth);
  const y = (value) => pad.top + (1 - Math.max(0, Math.min(100, Number(value) || 0)) / 100) * plotHeight;

  const svg = svgElement('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': '最近 30 个数据日指标趋势' });
  [0, 25, 50, 75, 100].forEach((value) => {
    svg.append(svgElement('line', { x1: pad.left, y1: y(value), x2: width - pad.right, y2: y(value), class: 'chart-grid-line' }));
    const label = svgElement('text', { x: pad.left - 10, y: y(value) + 4, class: 'chart-axis-label', 'text-anchor': 'end' });
    label.textContent = String(value);
    svg.append(label);
  });

  [
    ['hot_score', 'chart-hot'],
    ['sent_score', 'chart-sent'],
    ['crowding_score', 'chart-crowd'],
  ].forEach(([key, className]) => {
    const points = rows.map((row, index) => `${x(index)},${y(row[key])}`).join(' ');
    svg.append(svgElement('polyline', { points, class: `chart-line ${className}` }));
  });

  const dates = rows.length > 2 ? [0, Math.floor((rows.length - 1) / 2), rows.length - 1] : rows.map((_, index) => index);
  [...new Set(dates)].forEach((index) => {
    const label = svgElement('text', { x: x(index), y: height - 8, class: 'chart-axis-label', 'text-anchor': 'middle' });
    label.textContent = rows[index].date.slice(5);
    svg.append(label);
  });
  target.append(svg);
}

function renderPosts(data) {
  const posts = data?.top_posts || [];
  const list = $('#post-list');
  $('#posts-subtitle').textContent = data?.date ? `${data.date} · 板块匹配证据` : '板块证据';
  if (!posts.length) {
    replaceChildren(list, [createElement('li', 'panel-empty', '该数据日暂无匹配帖子')]);
    return;
  }

  const items = posts.slice(0, 6).map((post, index) => {
    const item = createElement('li', 'post-item');
    const rank = createElement('span', 'post-rank', String(index + 1));
    const copy = createElement('div', 'post-copy');
    const link = createElement('a', '', post.title || '未命名帖子');
    link.href = `https://bbs.hupu.com/${encodeURIComponent(String(post.thread_id || ''))}.html`;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    copy.append(link, createElement('small', '', `${Number(post.views) || 0} 浏览 · ${Number(post.likes) || 0} 亮 · ${Number(post.replies) || 0} 回复`));
    item.append(rank, copy);
    return item;
  });
  replaceChildren(list, items);
}

function boardButton(board) {
  const button = createElement('button', 'board-link', board.board || '未命名板块');
  button.type = 'button';
  button.addEventListener('click', () => selectBoard(board.board));
  return button;
}

function renderComparison() {
  const boards = state.boards.slice(0, 12);
  const bodyRows = boards.map((board, index) => {
    const row = document.createElement('tr');
    if (board.board === state.selectedBoard) row.classList.add('selected');
    const rank = createElement('td', '', String(index + 1));
    const name = document.createElement('td');
    name.append(boardButton(board));
    const status = document.createElement('td');
    status.append(makeStateLabel(board.state));
    row.append(
      rank, name, status,
      createElement('td', '', formatNumber(board.hot_score)),
      createElement('td', '', formatNumber(board.sent_score)),
      createElement('td', '', formatNumber(board.crowding_score)),
      createElement('td', '', formatNumber(board.coverage_score)),
      createElement('td', '', board.confidence || '—'),
    );
    return row;
  });
  replaceChildren($('#comparison-body'), bodyRows);

  const cards = boards.slice(0, 8).map((board, index) => {
    const button = createElement('button', 'comparison-card');
    button.type = 'button';
    if (board.board === state.selectedBoard) button.classList.add('selected');
    const heading = createElement('span', 'comparison-card-heading');
    heading.append(createElement('b', 'rank-number', String(index + 1)), createElement('strong', '', board.board), makeStateLabel(board.state));
    const values = createElement('span', 'comparison-values', `${formatNumber(board.hot_score)} / ${formatNumber(board.sent_score)} / ${formatNumber(board.crowding_score)} / ${formatNumber(board.coverage_score)}`);
    button.append(heading, values);
    button.addEventListener('click', () => selectBoard(board.board));
    return button;
  });
  replaceChildren($('#comparison-cards'), cards);
}

function qualityRow(label, description, value, fresh) {
  const row = createElement('div', 'quality-row');
  const copy = createElement('div');
  copy.append(createElement('strong', '', label), createElement('small', '', description));
  const status = createElement('span', fresh === false ? 'quality-value stale' : 'quality-value', value);
  row.append(copy, status);
  return row;
}

function renderQuality() {
  const health = state.overview?.health || {};
  const sources = health.sources || {};
  const stats = state.overview?.stats || {};
  const rows = [
    qualityRow('论坛数据', '帖子与评论抓取', humanAge(sources.forum), sources.forum?.fresh),
    qualityRow('分析结果', '板块匹配与情绪计算', humanAge(sources.analysis), sources.analysis?.fresh),
    qualityRow('行情数据', '价格扩展指标', humanAge(sources.price), sources.price?.fresh),
    qualityRow('分析覆盖', `${stats.today_boards || 0} 个板块 · 累计 ${stats.all_crawled_threads || 0} 帖`, `未匹配 ${formatPercent(stats.unmatched_rate)}`, Number(stats.unmatched_rate) <= 0.5),
  ];
  replaceChildren($('#quality-list'), rows);
}

function renderView() {
  $('#dashboard').dataset.view = state.view;
  $$('.workspace-tabs button').forEach((button) => {
    const active = button.dataset.view === state.view;
    button.classList.toggle('active', active);
    button.setAttribute('aria-current', active ? 'page' : 'false');
  });
}

function openSidebar() {
  $('#sector-sidebar').classList.add('open');
  $('#sidebar-overlay').hidden = false;
  $('#menu-button').setAttribute('aria-expanded', 'true');
  document.body.classList.add('drawer-open');
}

function closeSidebar() {
  $('#sector-sidebar').classList.remove('open');
  $('#sidebar-overlay').hidden = true;
  $('#menu-button').setAttribute('aria-expanded', 'false');
  document.body.classList.remove('drawer-open');
}

async function selectBoard(boardName, updateUrl = true) {
  if (!boardName) return;
  state.selectedBoard = boardName;
  state.selectedData = null;
  state.history = [];
  renderSidebar();
  renderComparison();
  renderSelectedSummary(null);
  renderMetrics(null);
  renderHistory([]);
  renderPosts(null);
  if (updateUrl) {
    const url = new URL(location.href);
    url.searchParams.set('board', boardName);
    history.replaceState({}, '', url);
  }
  if (matchMedia('(max-width: 800px)').matches) closeSidebar();

  const token = ++state.requestToken;
  try {
    const [latest, historyData] = await Promise.all([
      fetchJSON(`/boards/${encodeURIComponent(boardName)}/latest`),
      fetchJSON(`/boards/${encodeURIComponent(boardName)}/history?days=30`),
    ]);
    if (token !== state.requestToken) return;
    state.selectedData = latest;
    state.history = historyData.history || [];
    renderSelectedSummary(latest);
    renderMetrics(latest);
    renderHistory(state.history);
    renderPosts(latest);
  } catch (error) {
    if (token !== state.requestToken) return;
    renderSelectedSummary(null);
    $('#selected-summary').textContent = error.message;
  }
}

function setLoading(loading) {
  const button = $('#refresh-button');
  button.disabled = loading;
  button.classList.toggle('loading', loading);
  button.setAttribute('aria-busy', String(loading));
}

function showError(message) {
  const target = $('#page-error');
  target.textContent = message;
  target.hidden = !message;
}

async function loadDashboard() {
  setLoading(true);
  showError('');
  try {
    const overview = await fetchJSON('/overview');
    state.overview = overview;
    state.boards = overview.boards || [];
    renderHeader();
    renderSidebar();
    renderComparison();
    renderQuality();
    $('#empty-state').hidden = state.boards.length > 0;
    $('#dashboard').hidden = state.boards.length === 0;

    if (state.boards.length) {
      const requested = new URL(location.href).searchParams.get('board');
      const nextBoard = state.boards.some((board) => board.board === requested)
        ? requested
        : (state.selectedBoard && state.boards.some((board) => board.board === state.selectedBoard)
          ? state.selectedBoard
          : state.boards[0].board);
      await selectBoard(nextBoard, false);
    }
  } catch (error) {
    showError(`数据加载失败：${error.message}`);
  } finally {
    setLoading(false);
  }
}

$('#sector-search').addEventListener('input', (event) => {
  state.query = event.target.value;
  renderSidebar();
});

$('#state-filters').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-state]');
  if (!button) return;
  state.filter = button.dataset.state;
  $$('#state-filters button').forEach((candidate) => candidate.classList.toggle('active', candidate === button));
  renderSidebar();
});

$('.workspace-tabs').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-view]');
  if (!button) return;
  state.view = button.dataset.view;
  renderView();
});

$('#menu-button').addEventListener('click', openSidebar);
$('#close-sidebar').addEventListener('click', closeSidebar);
$('#sidebar-overlay').addEventListener('click', closeSidebar);
$('#refresh-button').addEventListener('click', loadDashboard);
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeSidebar();
});

renderView();
loadDashboard();
setInterval(loadDashboard, 5 * 60 * 1000);
