const state = {
  articles: [],
  articleId: null,
  payload: null,
  version: null,
  platform: "wechat",
  dirty: false,
  articleStatus: "untracked",
  previewRequest: 0,
  richPreviewRequest: 0,
  readerFeedbackRequest: 0,
  readerFeedbackTimer: null,
  visualCopyIndex: 0,
  visualRequestActive: false,
  webEditionRequestActive: false,
  wechatDraftRequestActive: false,
  wechatDraftStatus: "not_configured",
  articleListRefreshActive: false,
  gptPolish: null,
  gptPolishTimer: null,
  gptPolishRequestActive: false,
};

const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const articleList = document.querySelector("#article-list");
const articleSearch = document.querySelector("#article-search");
const statusFilter = document.querySelector("#status-filter");
const progressFilter = document.querySelector("#progress-filter");
const emptyState = document.querySelector("#empty-state");
const editorShell = document.querySelector("#editor-shell");
const titleInput = document.querySelector("#article-title");
const columnInput = document.querySelector("#article-column");
const markdownEditor = document.querySelector("#markdown-editor");
const articlePreview = document.querySelector("#article-preview");
const warnings = document.querySelector("#quality-warnings");
const readerFeedbackPlatform = document.querySelector(
  "#reader-feedback-platform",
);
const readerFeedbackSummary = document.querySelector(
  "#reader-feedback-summary",
);
const readerFeedbackGrid = document.querySelector("#reader-feedback-grid");
const notification = document.querySelector("#notification");
const historyDialog = document.querySelector("#history-dialog");
const historyList = document.querySelector("#history-list");
const contentPanes = document.querySelector("#content-panes");
const showEditorButton = document.querySelector("#show-editor-button");
const showPreviewButton = document.querySelector("#show-preview-button");
const coverPreview = document.querySelector("#cover-preview");
const bodyImagePreview = document.querySelector("#body-image-preview");
const coverPlaceholder = document.querySelector("#cover-placeholder");
const bodyPlaceholder = document.querySelector("#body-placeholder");
const visualTemplate = document.querySelector("#visual-template");
const nextCopyButton = document.querySelector("#next-copy-button");
const renderVisualsButton = document.querySelector("#render-visuals-button");
const richPreviewButton = document.querySelector("#rich-preview-button");
const richPreviewPane = document.querySelector("#rich-preview-pane");
const richArticlePreview = document.querySelector("#rich-article-preview");
const richPreviewCloseButton = document.querySelector(
  "#rich-preview-close-button",
);
const exportWebEditionButton = document.querySelector(
  "#export-web-edition-button",
);
const webEditionLinks = document.querySelector("#web-edition-links");
const wechatDraftButton = document.querySelector("#wechat-draft-button");
const wechatDraftStatus = document.querySelector("#wechat-draft-status");
const gptPolishStatus = document.querySelector("#gpt-polish-status");
const gptPolishNote = document.querySelector("#gpt-polish-note");
const gptPolishResult = document.querySelector("#gpt-polish-result");
const gptPolishSummary = document.querySelector("#gpt-polish-summary");
const gptPolishScoreGrid = document.querySelector("#gpt-polish-score-grid");
const gptPolishChanges = document.querySelector("#gpt-polish-changes");
const gptPolishBefore = document.querySelector("#gpt-polish-before");
const gptPolishAfter = document.querySelector("#gpt-polish-after");
const gptPolishRequestButton = document.querySelector(
  "#gpt-polish-request-button",
);
const gptPolishApplyButton = document.querySelector(
  "#gpt-polish-apply-button",
);
const gptPolishDiscardButton = document.querySelector(
  "#gpt-polish-discard-button",
);

const statusLabels = {
  needs_human_review: "待审核",
  approved: "已通过",
  revision_requested: "已退回",
  untracked: "未入队",
};

const platformLabels = {
  master: "母稿",
  wechat: "公众号",
  xiaohongshu: "小红书",
  toutiao: "今日头条",
  zhihu: "知乎",
};

const warningLabels = {
  missing_source_metadata: "缺少来源信息",
  missing_source_link: "正文缺少来源链接",
  body_too_short: "正文过短",
  below_target_length: "未达到平台建议篇幅",
  editorial_placeholder: "正文包含编辑占位文字",
  title_too_short: "标题过短",
  overpromise: "包含过度承诺",
  high_risk_advice: "包含高风险建议",
  ai_cliche: "存在常见 AI 套话",
  audience_roll_call: "受众罗列过于机械",
  unverified_first_person_trial: "缺少实测证据却使用第一人称体验",
  cheap_clickbait: "标题存在廉价夸张词",
  too_many_exclamations: "感叹号过多",
  legacy_editorial_profile: "文章尚未升级到新的人格版本",
};

async function api(path, options = {}) {
  const apiRequest = {...options};
  apiRequest.headers = {
    Accept: "application/json",
    ...(apiRequest.headers || {}),
  };
  if (apiRequest.body !== undefined) {
    apiRequest.headers["Content-Type"] = "application/json";
    apiRequest.headers["X-CSRF-Token"] = csrfToken;
  }
  const response = await fetch(path, apiRequest);
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("登录已过期");
  }
  let value = {};
  try {
    value = await response.json();
  } catch {
    value = {};
  }
  if (!response.ok) {
    if (response.status === 409) {
      throw new Error("文章已在其他页面修改，请刷新后重试。");
    }
    const error = new Error(
      value.detail || value.error || `请求失败（${response.status}）`,
    );
    error.apiStatus = value.status;
    throw error;
  }
  return value;
}

function notify(message, kind = "success") {
  notification.textContent = message;
  notification.className = `notification ${kind}`;
  notification.hidden = false;
  window.setTimeout(() => {
    notification.hidden = true;
  }, 2600);
}

function bodyFor(platform) {
  if (platform === "master") {
    return state.payload.master_markdown;
  }
  return state.payload.platform_markdown[platform];
}

function setBody(platform, value) {
  if (platform === "master") {
    state.payload.master_markdown = value;
  } else {
    state.payload.platform_markdown[platform] = value;
  }
}

function readEditorIntoPayload() {
  if (!state.payload) return;
  state.payload.master_title = titleInput.value;
  state.payload.column = columnInput.value;
  setBody(state.platform, markdownEditor.value);
}

function renderWarnings(items) {
  warnings.replaceChildren();
  if (!items || items.length === 0) {
    warnings.hidden = true;
    return;
  }
  const strong = document.createElement("strong");
  strong.textContent = "质量提醒：";
  const labels = items.map((item) => {
    const leaf = item.includes(":") ? item.split(":").at(-1) : item;
    return warningLabels[leaf] || item;
  });
  warnings.append(strong, document.createTextNode(labels.join("、")));
  warnings.hidden = false;
}

function clearWebEditionLinks() {
  webEditionLinks.replaceChildren();
  webEditionLinks.hidden = true;
}

function updateWebEditionControls() {
  exportWebEditionButton.disabled = (
    !state.articleId
    || state.articleStatus !== "approved"
    || state.dirty
    || state.webEditionRequestActive
  );
}

function updateWechatDraftControls() {
  const labels = {
    not_configured: "公众号未配置",
    not_synced: "未同步",
    success: "已进入公众号草稿箱",
    error: "同步失败，可重试",
    pending: "结果待确认，请到公众号后台核对",
  };
  wechatDraftStatus.textContent = (
    labels[state.wechatDraftStatus] || state.wechatDraftStatus
  );
  wechatDraftButton.disabled = (
    !state.articleId
    || state.articleStatus !== "approved"
    || state.dirty
    || state.wechatDraftRequestActive
    || state.wechatDraftStatus === "not_configured"
    || state.wechatDraftStatus === "success"
    || state.wechatDraftStatus === "pending"
  );
}

const gptPolishStatusLabels = {
  queued: "等待本机 GPT 领取",
  claimed: "GPT 正在精修",
  ready: "候选稿待确认",
  applied: "候选稿已应用",
  discarded: "候选稿已放弃",
  failed: "精修失败，可重新请求",
};

function updateGptPolishControls() {
  const status = state.gptPolish?.status;
  const active = ["queued", "claimed", "ready"].includes(status);
  const matchingVersion = (
    !state.gptPolish
    || state.gptPolish.base_version === state.version
  );
  gptPolishRequestButton.disabled = (
    !state.articleId
    || state.dirty
    || state.gptPolishRequestActive
    || (active && matchingVersion)
  );
  gptPolishApplyButton.disabled = (
    status !== "ready"
    || !matchingVersion
    || state.dirty
    || state.gptPolishRequestActive
  );
  gptPolishDiscardButton.disabled = (
    status !== "ready" || state.gptPolishRequestActive
  );
}

function stopGptPolishPolling() {
  window.clearTimeout(state.gptPolishTimer);
  state.gptPolishTimer = null;
}

function scheduleGptPolishPolling() {
  stopGptPolishPolling();
  if (!["queued", "claimed"].includes(state.gptPolish?.status)) return;
  const articleId = state.articleId;
  state.gptPolishTimer = window.setTimeout(async () => {
    try {
      const value = await api(
        `/api/articles/${encodeURIComponent(articleId)}/gpt-polish`,
      );
      if (articleId !== state.articleId) return;
      renderGptPolish(value.gpt_polish);
    } catch (error) {
      if (articleId === state.articleId) notify(error.message, "error");
    }
  }, 4000);
}

function renderGptPolish(job) {
  state.gptPolish = job || null;
  gptPolishResult.hidden = true;
  gptPolishScoreGrid.replaceChildren();
  gptPolishChanges.replaceChildren();
  if (!job) {
    gptPolishStatus.textContent = "尚未请求";
    gptPolishNote.textContent = (
      "请求后由 Windows 本机 Codex 领取任务；完成后会在这里显示候选稿，人工确认前不会覆盖正文。"
    );
    updateGptPolishControls();
    stopGptPolishPolling();
    return;
  }
  const matchingVersion = job.base_version === state.version;
  const terminal = ["applied", "discarded", "failed"].includes(job.status);
  gptPolishStatus.textContent = (matchingVersion || terminal)
    ? (gptPolishStatusLabels[job.status] || job.status)
    : "文章已变化，旧候选稿不可应用";
  if (job.status === "queued") {
    gptPolishNote.textContent = (
      "任务已进入队列。请在 Windows Codex 中运行 gpt-polish-article Skill（可直接说“处理待精修文章”）。"
    );
  } else if (job.status === "claimed") {
    gptPolishNote.textContent = "本机 GPT 已领取任务，正在阅读、评分并改写。";
  } else if (job.status === "failed") {
    gptPolishNote.textContent = `本次处理失败：${job.error || "未知错误"}`;
  } else if (job.status === "ready") {
    gptPolishNote.textContent = matchingVersion
      ? "候选稿已返回。请检查评分、调整摘要和前后对照，再决定是否应用。"
      : "候选稿基于旧版本生成。请重新请求，避免覆盖较新的人工修改。";
  } else {
    gptPolishNote.textContent = "本次精修任务已经结束。";
  }
  const proposal = job.proposal;
  if (job.status === "ready" && proposal?.assessment) {
    const assessment = proposal.assessment;
    gptPolishResult.hidden = false;
    gptPolishSummary.textContent = (
      `${assessment.overall}/5 · ${assessment.verdict} · ${assessment.summary}`
    );
    const scores = [
      ...(assessment.dimensions || []),
      ...(assessment.audits || []),
    ];
    for (const item of scores) {
      const card = document.createElement("div");
      card.className = "gpt-polish-score";
      const label = document.createElement("span");
      label.textContent = item.label;
      const score = document.createElement("strong");
      score.textContent = `${item.score}/5`;
      card.title = `${item.evidence}\n建议：${item.suggestion}`;
      card.append(label, score);
      gptPolishScoreGrid.append(card);
    }
    for (const change of proposal.change_summary || []) {
      const item = document.createElement("li");
      item.textContent = change;
      gptPolishChanges.append(item);
    }
    gptPolishBefore.textContent = job.request?.master_markdown || "";
    gptPolishAfter.textContent = proposal.master_markdown || "";
  }
  updateGptPolishControls();
  scheduleGptPolishPolling();
}

function setArticleStatus(status) {
  state.articleStatus = status;
  updateWebEditionControls();
  updateWechatDraftControls();
}

function invalidateRichPreview() {
  state.richPreviewRequest += 1;
  richPreviewPane.hidden = true;
  contentPanes.hidden = false;
  richPreviewButton.disabled = false;
}

function formatArticleDate(article) {
  return article.generated_date || "未知日期";
}

function assetUrl(asset) {
  if (!asset || !state.articleId) return "";
  return `/api/articles/${
    encodeURIComponent(state.articleId)
  }/assets/${encodeURIComponent(asset.asset_id)}/${
    encodeURIComponent(asset.revision)
  }`;
}

function renderVisuals() {
  const assets = state.payload?.visual_assets;
  const cover = assets?.cover;
  const body = assets?.body?.[0];

  coverPreview.hidden = !cover;
  coverPlaceholder.hidden = Boolean(cover);
  coverPreview.src = cover ? assetUrl(cover) : "";

  bodyImagePreview.hidden = !body;
  bodyPlaceholder.hidden = Boolean(body);
  bodyImagePreview.src = body ? assetUrl(body) : "";

  if (cover) {
    state.visualCopyIndex = cover.copy_index;
    visualTemplate.value = cover.template;
  } else {
    state.visualCopyIndex = 0;
    visualTemplate.value = (
      state.payload?.visual_brief?.template_hint || "ai_done_vs_tests"
    );
  }
}

function schedulePreview() {
  const requestId = ++state.previewRequest;
  const markdown = markdownEditor.value;
  window.setTimeout(async () => {
    if (requestId !== state.previewRequest) return;
    try {
      const value = await api("/api/preview", {
        method: "POST",
        body: JSON.stringify({
          article_id: state.articleId,
          markdown,
        }),
      });
      if (requestId === state.previewRequest) {
        articlePreview.innerHTML = value.html;
      }
    } catch (error) {
      notify(error.message, "error");
    }
  }, 250);
}

function renderArticleList() {
  articleList.replaceChildren();
  const visibleArticles = filterVisibleArticles();
  if (visibleArticles.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted sidebar-empty";
    empty.textContent = "当前筛选条件下没有文章。";
    articleList.append(empty);
    return;
  }
  for (const article of visibleArticles) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "article-item";
    button.dataset.articleId = article.article_id;
    if (article.article_id === state.articleId) {
      button.classList.add("selected");
    }

    const title = document.createElement("strong");
    title.textContent = article.title;
    const meta = document.createElement("span");
    const status = statusLabels[article.status] || article.status;
    meta.textContent = `${article.column} · ${status}`;
    const progress = document.createElement("span");
    progress.className = "article-progress";
    const progressLabels = [];
    if (article.gpt_polish_status === "ready") {
      progressLabels.push("GPT 待应用");
    } else if (article.gpt_polish_status === "applied") {
      progressLabels.push("GPT 已应用");
    }
    if (article.wechat_draft_status === "success") {
      progressLabels.push("公众号已同步");
    }
    progress.textContent = progressLabels.join(" · ") || "尚未完成后续处理";
    const date = document.createElement("span");
    date.className = "article-date";
    date.textContent = `生成日期：${formatArticleDate(article)}`;
    button.append(title, meta, progress, date);
    button.addEventListener("click", () => openArticle(article.article_id));
    articleList.append(button);
  }
}

async function loadArticles(status = "") {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  const value = await api(`/api/articles${query}`);
  state.articles = value.articles;
  renderArticleList();
  if (!state.articleId && state.articles.length > 0) {
    await openArticle(state.articles[0].article_id);
  }
}

function filterVisibleArticles() {
  const query = articleSearch.value.trim().toLocaleLowerCase("zh-CN");
  const progress = progressFilter.value;
  return state.articles.filter((article) => {
    const searchable = `${article.title} ${article.column}`.toLocaleLowerCase(
      "zh-CN",
    );
    if (query && !searchable.includes(query)) return false;
    if (progress === "gpt_ready") {
      return article.gpt_polish_status === "ready";
    }
    if (progress === "gpt_applied") {
      return article.gpt_polish_status === "applied";
    }
    if (progress === "wechat_success") {
      return article.wechat_draft_status === "success";
    }
    return true;
  });
}

function feedbackTone(score) {
  if (score >= 4) return "strong";
  if (score < 3) return "weak";
  return "watch";
}

function renderReaderFeedback(feedback, platform = state.platform) {
  readerFeedbackGrid.replaceChildren();
  readerFeedbackPlatform.textContent = platformLabels[platform] || platform;
  if (
    !feedback
    || feedback.version !== "reader-feedback-v1"
    || !Array.isArray(feedback.dimensions)
  ) {
    readerFeedbackSummary.textContent = "暂时无法评分";
    return;
  }
  readerFeedbackSummary.textContent = (
    `${feedback.overall}/5 · ${feedback.verdict} · ${feedback.summary}`
  );
  for (const item of feedback.dimensions) {
    const card = document.createElement("section");
    card.className = `feedback-card ${feedbackTone(item.score)}`;
    card.dataset.feedbackKey = item.key;

    const header = document.createElement("div");
    header.className = "feedback-card-header";
    const label = document.createElement("strong");
    label.textContent = item.label;
    const score = document.createElement("span");
    score.className = "feedback-score";
    score.textContent = `${item.score}/5`;
    header.append(label, score);

    const meter = document.createElement("div");
    meter.className = "feedback-meter";
    const fill = document.createElement("span");
    const boundedScore = Math.max(0, Math.min(5, Number(item.score) || 0));
    fill.style.width = `${boundedScore * 20}%`;
    meter.append(fill);

    const evidence = document.createElement("p");
    evidence.className = "feedback-evidence";
    evidence.textContent = item.evidence;
    const suggestion = document.createElement("p");
    suggestion.className = "feedback-suggestion";
    suggestion.textContent = `建议：${item.suggestion}`;
    card.append(header, meter, evidence, suggestion);
    readerFeedbackGrid.append(card);
  }
}

function scheduleReaderFeedback(delay = 320) {
  if (!state.payload) return;
  const requestId = ++state.readerFeedbackRequest;
  const articleId = state.articleId;
  const platform = state.platform;
  const title = titleInput.value;
  const markdown = markdownEditor.value;
  window.clearTimeout(state.readerFeedbackTimer);
  readerFeedbackPlatform.textContent = platformLabels[platform] || platform;
  readerFeedbackSummary.textContent = "正在重新评分…";
  state.readerFeedbackTimer = window.setTimeout(async () => {
    try {
      const value = await api("/api/editorial-feedback", {
        method: "POST",
        body: JSON.stringify({title, markdown}),
      });
      if (
        requestId !== state.readerFeedbackRequest
        || articleId !== state.articleId
        || platform !== state.platform
      ) {
        return;
      }
      renderReaderFeedback(value.reader_feedback, platform);
    } catch (error) {
      if (requestId === state.readerFeedbackRequest) {
        readerFeedbackSummary.textContent = "评分暂时不可用";
        notify(error.message, "error");
      }
    }
  }, delay);
}

async function refreshArticlesOnFocus() {
  if (state.dirty) return;
  if (state.articleListRefreshActive || state.articles.length === 0) return;
  state.articleListRefreshActive = true;
  const knownArticleIds = new Set(
    state.articles.map((article) => article.article_id),
  );
  try {
    await loadArticles(statusFilter.value);
    const newArticle = state.articles.find(
      (article) => !knownArticleIds.has(article.article_id),
    );
    if (newArticle) {
      notify(`发现新文章，请在左侧打开查看：${newArticle.title}`);
    }
  } catch (error) {
    notify(error.message, "error");
  } finally {
    state.articleListRefreshActive = false;
  }
}

async function openArticle(articleId) {
  if (
    state.dirty
    && !window.confirm("当前修改尚未保存，确定切换文章吗？")
  ) {
    return;
  }
  invalidateRichPreview();
  stopGptPolishPolling();
  try {
    const value = await api(
      `/api/articles/${encodeURIComponent(articleId)}`,
    );
    state.articleId = articleId;
    state.payload = value.payload;
    state.version = value.version;
    state.platform = "wechat";
    state.dirty = false;
    state.gptPolishRequestActive = false;
    state.wechatDraftStatus = value.wechat_draft?.status || "not_synced";
    const article = state.articles.find(
      (item) => item.article_id === articleId,
    );
    setArticleStatus(article?.status || "untracked");
    clearWebEditionLinks();
    titleInput.value = state.payload.master_title;
    columnInput.value = state.payload.column;
    emptyState.hidden = true;
    editorShell.hidden = false;
    renderWarnings(value.warnings);
    renderReaderFeedback(value.reader_feedback, "master");
    renderGptPolish(value.gpt_polish);
    renderVisuals();
    selectPlatform("wechat", false);
    renderArticleList();
    document.querySelector("#article-sidebar").classList.remove("open");
  } catch (error) {
    notify(error.message, "error");
  }
}

function selectPlatform(platform, preserveCurrent = true) {
  if (!state.payload) return;
  if (preserveCurrent) {
    setBody(state.platform, markdownEditor.value);
  }
  state.platform = platform;
  markdownEditor.value = bodyFor(platform);
  for (const button of document.querySelectorAll("[data-platform]")) {
    button.classList.toggle(
      "selected",
      button.dataset.platform === platform,
    );
  }
  schedulePreview();
  scheduleReaderFeedback();
}

async function saveArticle() {
  if (!state.payload) return;
  readEditorIntoPayload();
  try {
    const value = await api(
      `/api/articles/${encodeURIComponent(state.articleId)}`,
      {
        method: "PUT",
        body: JSON.stringify({
          payload: state.payload,
          version: state.version,
        }),
      },
    );
    state.payload = value.payload;
    state.version = value.version;
    state.dirty = false;
    renderGptPolish(state.gptPolish);
    state.wechatDraftStatus = "not_synced";
    setArticleStatus("needs_human_review");
    clearWebEditionLinks();
    invalidateRichPreview();
    renderWarnings(value.warnings);
    renderVisuals();
    scheduleReaderFeedback(0);
    notify("修改已保存，并创建了历史版本。");
    await loadArticles(statusFilter.value);
  } catch (error) {
    notify(error.message, "error");
  }
}

async function copyCurrentBody() {
  try {
    await navigator.clipboard.writeText(markdownEditor.value);
    notify("正文已复制。");
  } catch {
    notify("复制失败，请手动选择正文复制。", "error");
  }
}

async function setStatus(status) {
  if (!state.articleId) return;
  try {
    await api(
      `/api/articles/${encodeURIComponent(state.articleId)}/status`,
      {
        method: "POST",
        body: JSON.stringify({status}),
      },
    );
    const message = status === "approved"
      ? "文章已标记为通过。"
      : "文章已标记为退回。";
    notify(message);
    setArticleStatus(status);
    if (status !== "approved") {
      clearWebEditionLinks();
    }
    await loadArticles(statusFilter.value);
  } catch (error) {
    notify(error.message, "error");
  }
}

async function requestGptPolish() {
  if (!state.articleId || state.gptPolishRequestActive) return;
  if (state.dirty) {
    notify("请先保存当前修改，再请求 GPT 精修。", "error");
    return;
  }
  state.gptPolishRequestActive = true;
  updateGptPolishControls();
  try {
    const value = await api(
      `/api/articles/${encodeURIComponent(state.articleId)}/gpt-polish`,
      {
        method: "POST",
        body: JSON.stringify({version: state.version}),
      },
    );
    renderGptPolish(value.gpt_polish);
    notify("GPT 精修任务已创建，请在 Windows Codex 中处理。", "success");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    state.gptPolishRequestActive = false;
    updateGptPolishControls();
  }
}

async function applyGptPolish() {
  const job = state.gptPolish;
  if (!state.articleId || job?.status !== "ready") return;
  if (!window.confirm("应用后会保存为新历史版本，并重新进入人工审核。确定继续吗？")) {
    return;
  }
  state.gptPolishRequestActive = true;
  updateGptPolishControls();
  try {
    const previousVersion = state.version;
    const previousTitle = state.payload.master_title;
    const value = await api(
      `/api/articles/${encodeURIComponent(state.articleId)}/gpt-polish/${
        encodeURIComponent(job.job_id)
      }/apply`,
      {
        method: "POST",
        body: JSON.stringify({version: state.version}),
      },
    );
    if (
      value.version === previousVersion
      || value.payload?.master_title !== job.proposal?.master_title
    ) {
      throw new Error("服务器没有确认 GPT 候选稿已写入，请刷新后重试。");
    }
    state.payload = value.payload;
    state.version = value.version;
    state.dirty = false;
    state.wechatDraftStatus = "not_synced";
    titleInput.value = state.payload.master_title;
    columnInput.value = state.payload.column;
    markdownEditor.value = bodyFor(state.platform);
    setArticleStatus("needs_human_review");
    clearWebEditionLinks();
    invalidateRichPreview();
    renderWarnings(value.warnings);
    renderVisuals();
    renderGptPolish(value.gpt_polish);
    schedulePreview();
    scheduleReaderFeedback(0);
    await loadArticles(statusFilter.value);
    notify(
      previousTitle === state.payload.master_title
        ? "GPT 候选稿已写入新版本，并重新进入人工审核。"
        : `GPT 候选稿已应用：标题已更新为“${state.payload.master_title}”。`,
      "success",
    );
  } catch (error) {
    notify(error.message, "error");
  } finally {
    state.gptPolishRequestActive = false;
    updateGptPolishControls();
  }
}

async function discardGptPolish() {
  const job = state.gptPolish;
  if (!state.articleId || job?.status !== "ready") return;
  state.gptPolishRequestActive = true;
  updateGptPolishControls();
  try {
    const value = await api(
      `/api/articles/${encodeURIComponent(state.articleId)}/gpt-polish/${
        encodeURIComponent(job.job_id)
      }/discard`,
      {method: "POST", body: JSON.stringify({})},
    );
    renderGptPolish(value.gpt_polish);
    notify("候选稿已放弃，原文未改变。", "success");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    state.gptPolishRequestActive = false;
    updateGptPolishControls();
  }
}

async function rerenderVisuals({copyIndex = state.visualCopyIndex} = {}) {
  if (!state.articleId || state.visualRequestActive) return;
  if (state.dirty) {
    notify("请先保存正文修改，再更换图片。", "error");
    return;
  }
  const previousCopyIndex = state.visualCopyIndex;
  state.visualRequestActive = true;
  nextCopyButton.disabled = true;
  renderVisualsButton.disabled = true;
  try {
    const value = await api(
      `/api/articles/${
        encodeURIComponent(state.articleId)
      }/visuals/render`,
      {
        method: "POST",
        body: JSON.stringify({
          version: state.version,
          template: visualTemplate.value,
          copy_index: copyIndex,
        }),
      },
    );
    state.payload = value.payload;
    state.version = value.version;
    state.visualCopyIndex = copyIndex;
    state.dirty = false;
    state.wechatDraftStatus = "not_synced";
    setArticleStatus("needs_human_review");
    clearWebEditionLinks();
    invalidateRichPreview();
    renderWarnings(value.warnings);
    renderVisuals();
    schedulePreview();
    scheduleReaderFeedback(0);
    notify("图片新版本已生成，旧版本仍在历史记录中。");
  } catch (error) {
    state.visualCopyIndex = previousCopyIndex;
    notify(error.message, "error");
  } finally {
    state.visualRequestActive = false;
    nextCopyButton.disabled = false;
    renderVisualsButton.disabled = false;
  }
}

async function showHistory() {
  if (!state.articleId) return;
  try {
    const value = await api(
      `/api/articles/${encodeURIComponent(state.articleId)}/history`,
    );
    historyList.replaceChildren();
    if (value.history.length === 0) {
      const empty = document.createElement("p");
      empty.textContent = "还没有历史版本。";
      historyList.append(empty);
    }
    for (const item of value.history) {
      const row = document.createElement("div");
      row.className = "history-row";
      const text = document.createElement("span");
      const operation = item.operation === "restore" ? "恢复" : "编辑";
      text.textContent = `${
        new Date(item.saved_at).toLocaleString()
      } · ${operation}`;
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "恢复";
      button.addEventListener(
        "click",
        () => restoreHistory(item.history_id),
      );
      row.append(text, button);
      historyList.append(row);
    }
    historyDialog.showModal();
  } catch (error) {
    notify(error.message, "error");
  }
}

async function restoreHistory(historyId) {
  if (!window.confirm("恢复后仍会保留当前版本，确定继续吗？")) {
    return;
  }
  try {
    const value = await api(
      `/api/articles/${
        encodeURIComponent(state.articleId)
      }/restore/${encodeURIComponent(historyId)}`,
      {
        method: "POST",
        body: JSON.stringify({version: state.version}),
      },
    );
    state.payload = value.payload;
    state.version = value.version;
    state.dirty = false;
    state.wechatDraftStatus = "not_synced";
    setArticleStatus("needs_human_review");
    clearWebEditionLinks();
    invalidateRichPreview();
    titleInput.value = state.payload.master_title;
    columnInput.value = state.payload.column;
    markdownEditor.value = bodyFor(state.platform);
    renderWarnings(value.warnings);
    renderVisuals();
    schedulePreview();
    scheduleReaderFeedback(0);
    historyDialog.close();
    notify("历史版本已恢复。");
  } catch (error) {
    notify(error.message, "error");
  }
}

function showMobilePane(pane) {
  const editorSelected = pane === "editor";
  contentPanes.className = `content-panes show-${pane}`;
  showEditorButton.classList.toggle("selected", editorSelected);
  showPreviewButton.classList.toggle("selected", !editorSelected);
}

async function showRichPreview() {
  if (!state.articleId) return;
  const articleId = state.articleId;
  const requestId = ++state.richPreviewRequest;
  richPreviewButton.disabled = true;
  contentPanes.hidden = true;
  richPreviewPane.hidden = false;
  richArticlePreview.textContent = "正在生成富阅读预览…";
  try {
    const value = await api("/api/rich-preview", {
      method: "POST",
      body: JSON.stringify({article_id: articleId}),
    });
    if (requestId !== state.richPreviewRequest || articleId !== state.articleId) {
      return;
    }
    richArticlePreview.innerHTML = value.html;
  } catch (error) {
    if (requestId === state.richPreviewRequest) {
      richArticlePreview.textContent = "富阅读预览暂时无法生成。";
      notify(error.message, "error");
    }
  } finally {
    if (requestId === state.richPreviewRequest) {
      richPreviewButton.disabled = false;
    }
  }
}

function closeRichPreview() {
  invalidateRichPreview();
  showMobilePane("preview");
}

function webEditionUrl(value, key, articleId) {
  if (typeof value[key] !== "string") {
    throw new Error("导出响应缺少网页地址。");
  }
  const url = new URL(value[key], window.location.origin);
  const expectedPath = `/api/articles/${encodeURIComponent(articleId)}/web-edition`;
  if (url.origin !== window.location.origin || url.pathname !== expectedPath) {
    throw new Error("导出响应包含不受信任的网页地址。");
  }
  return url.href;
}

function renderWebEditionLinks(value, articleId) {
  const view = document.createElement("a");
  view.href = webEditionUrl(value, "view_url", articleId);
  view.target = "_blank";
  view.rel = "noopener";
  view.textContent = "查看网页";

  const download = document.createElement("a");
  download.href = webEditionUrl(value, "download_url", articleId);
  download.textContent = "下载 HTML";

  webEditionLinks.replaceChildren(view, download);
  webEditionLinks.hidden = false;
}

async function exportWebEdition() {
  if (!state.articleId || state.articleStatus !== "approved" || state.dirty) {
    notify("文章通过审核后才可导出网页。", "error");
    return;
  }
  const articleId = state.articleId;
  state.webEditionRequestActive = true;
  updateWebEditionControls();
  try {
    const value = await api(
      `/api/articles/${encodeURIComponent(articleId)}/web-edition`,
      {method: "POST", body: JSON.stringify({})},
    );
    if (articleId !== state.articleId) return;
    renderWebEditionLinks(value, articleId);
    notify("网页文章已导出。");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    state.webEditionRequestActive = false;
    updateWebEditionControls();
  }
}

async function syncWechatDraft() {
  if (!state.articleId || state.articleStatus !== "approved" || state.dirty) {
    notify("请先通过审核并保存修改。", "error");
    return;
  }
  state.wechatDraftRequestActive = true;
  updateWechatDraftControls();
  try {
    const value = await api(
      `/api/articles/${encodeURIComponent(state.articleId)}/wechat/draft`,
      {
        method: "POST",
        body: JSON.stringify({version: state.version}),
      },
    );
    state.wechatDraftStatus = value.status;
    notify(
      value.idempotent
        ? "该版本已在公众号草稿箱。"
        : "已同步到公众号草稿箱。",
    );
  } catch (error) {
    state.wechatDraftStatus = error.apiStatus || "error";
    notify(error.message, "error");
  } finally {
    state.wechatDraftRequestActive = false;
    updateWechatDraftControls();
  }
}

for (const button of document.querySelectorAll("[data-platform]")) {
  button.addEventListener(
    "click",
    () => selectPlatform(button.dataset.platform),
  );
}

for (const input of [titleInput, columnInput, markdownEditor]) {
  input.addEventListener("input", () => {
    readEditorIntoPayload();
    state.dirty = true;
    clearWebEditionLinks();
    updateWebEditionControls();
    updateWechatDraftControls();
    updateGptPolishControls();
    invalidateRichPreview();
    if (input === markdownEditor) {
      schedulePreview();
    }
    if (input === titleInput || input === markdownEditor) {
      scheduleReaderFeedback();
    }
  });
}

document.querySelector("#save-button").addEventListener(
  "click",
  saveArticle,
);
document.querySelector("#copy-button").addEventListener(
  "click",
  copyCurrentBody,
);
richPreviewButton.addEventListener("click", showRichPreview);
richPreviewCloseButton.addEventListener("click", closeRichPreview);
exportWebEditionButton.addEventListener("click", exportWebEdition);
wechatDraftButton.addEventListener("click", syncWechatDraft);
gptPolishRequestButton.addEventListener("click", requestGptPolish);
gptPolishApplyButton.addEventListener("click", applyGptPolish);
gptPolishDiscardButton.addEventListener("click", discardGptPolish);
document.querySelector("#approve-button").addEventListener(
  "click",
  () => setStatus("approved"),
);
document.querySelector("#reject-button").addEventListener(
  "click",
  () => setStatus("revision_requested"),
);
document.querySelector("#history-button").addEventListener(
  "click",
  showHistory,
);
nextCopyButton.addEventListener("click", () => {
  const copyIndex = (state.visualCopyIndex + 1) % 3;
  rerenderVisuals({copyIndex});
});
renderVisualsButton.addEventListener("click", () => rerenderVisuals());
document.querySelector("#history-close-button").addEventListener(
  "click",
  () => historyDialog.close(),
);
document.querySelector("#sidebar-button").addEventListener("click", () => {
  document.querySelector("#article-sidebar").classList.toggle("open");
});
showEditorButton.addEventListener("click", () => showMobilePane("editor"));
showPreviewButton.addEventListener("click", () => showMobilePane("preview"));
statusFilter.addEventListener(
  "change",
  () => loadArticles(statusFilter.value),
);
articleSearch.addEventListener("input", renderArticleList);
progressFilter.addEventListener("change", renderArticleList);
document.querySelector("#logout-button").addEventListener(
  "click",
  async () => {
    await fetch("/logout", {
      method: "POST",
      headers: {"X-CSRF-Token": csrfToken},
    });
    window.location.assign("/login");
  },
);

window.addEventListener("beforeunload", (event) => {
  if (!state.dirty) return;
  event.preventDefault();
  event.returnValue = "";
});
window.addEventListener("focus", refreshArticlesOnFocus);

loadArticles().catch((error) => notify(error.message, "error"));
