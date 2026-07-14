const state = {
  articles: [],
  articleId: null,
  payload: null,
  version: null,
  platform: "wechat",
  dirty: false,
  previewRequest: 0,
  visualCopyIndex: 0,
  visualRequestActive: false,
};

const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const articleList = document.querySelector("#article-list");
const statusFilter = document.querySelector("#status-filter");
const emptyState = document.querySelector("#empty-state");
const editorShell = document.querySelector("#editor-shell");
const titleInput = document.querySelector("#article-title");
const columnInput = document.querySelector("#article-column");
const markdownEditor = document.querySelector("#markdown-editor");
const articlePreview = document.querySelector("#article-preview");
const warnings = document.querySelector("#quality-warnings");
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

const statusLabels = {
  needs_human_review: "待审核",
  approved: "已通过",
  revision_requested: "已退回",
  untracked: "未入队",
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
    throw new Error(
      value.detail || value.error || `请求失败（${response.status}）`,
    );
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
  if (state.articles.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted sidebar-empty";
    empty.textContent = "当前筛选条件下没有文章。";
    articleList.append(empty);
    return;
  }
  for (const article of state.articles) {
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
    const date = document.createElement("span");
    date.className = "article-date";
    date.textContent = `生成日期：${formatArticleDate(article)}`;
    button.append(title, meta, date);
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

async function openArticle(articleId) {
  if (
    state.dirty
    && !window.confirm("当前修改尚未保存，确定切换文章吗？")
  ) {
    return;
  }
  try {
    const value = await api(
      `/api/articles/${encodeURIComponent(articleId)}`,
    );
    state.articleId = articleId;
    state.payload = value.payload;
    state.version = value.version;
    state.platform = "wechat";
    state.dirty = false;
    titleInput.value = state.payload.master_title;
    columnInput.value = state.payload.column;
    emptyState.hidden = true;
    editorShell.hidden = false;
    renderWarnings(value.warnings);
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
    renderWarnings(value.warnings);
    renderVisuals();
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
    await loadArticles(statusFilter.value);
  } catch (error) {
    notify(error.message, "error");
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
    renderWarnings(value.warnings);
    renderVisuals();
    schedulePreview();
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
    titleInput.value = state.payload.master_title;
    columnInput.value = state.payload.column;
    markdownEditor.value = bodyFor(state.platform);
    renderWarnings(value.warnings);
    renderVisuals();
    schedulePreview();
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
    if (input === markdownEditor) {
      schedulePreview();
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

loadArticles().catch((error) => notify(error.message, "error"));
