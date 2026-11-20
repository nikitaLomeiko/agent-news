const state = {
  articles: [],
  config: {},
  view: "all",
  category: "Все",
  query: "",
  read: new Set(JSON.parse(localStorage.getItem("agent-news-read") || "[]")),
  signature: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHTML(value = "") {
  return String(value).replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#039;", '"': "&quot;",
  })[char]);
}

function safeURL(value = "") {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch { return ""; }
}

function safeMediaURL(value = "") {
  if (["/media/", "./media/", "media/"].some((prefix) => String(value).startsWith(prefix))) return String(value);
  return safeURL(value);
}

function inlineMarkdown(value) {
  let text = escapeHTML(value);
  text = text.replace(/!\[([^\]]*)]\(([^)\s]+)\)/g, (match, alt, source) => {
    const url = safeMediaURL(source.replaceAll("&amp;", "&"));
    return url ? `<img class="markdown-image" src="${escapeHTML(url)}" alt="${alt}" loading="lazy" decoding="async">` : match;
  });
  text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  text = text.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  text = text.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  text = text.replace(/\[([^\]]+)]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  return text;
}

function renderMarkdown(markdown = "") {
  const lines = markdown.replace(/\r/g, "").split("\n");
  const output = [];
  let paragraph = [];
  let list = null;
  let inCode = false;
  let code = [];

  const flushParagraph = () => {
    if (paragraph.length) output.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (list) output.push(`</${list}>`);
    list = null;
  };

  lines.forEach((line) => {
    if (line.trim().startsWith("```")) {
      if (inCode) {
        output.push(`<pre><code>${escapeHTML(code.join("\n"))}</code></pre>`);
        code = []; inCode = false;
      } else { flushParagraph(); closeList(); inCode = true; }
      return;
    }
    if (inCode) { code.push(line); return; }
    if (!line.trim()) { flushParagraph(); closeList(); return; }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph(); closeList();
      const level = heading[1].length;
      output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      return;
    }
    if (/^---+$/.test(line.trim())) { flushParagraph(); closeList(); output.push("<hr>"); return; }
    const quote = line.match(/^>\s?(.*)$/);
    if (quote) { flushParagraph(); closeList(); output.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`); return; }
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      const target = unordered ? "ul" : "ol";
      if (list !== target) { closeList(); output.push(`<${target}>`); list = target; }
      output.push(`<li>${inlineMarkdown((unordered || ordered)[1])}</li>`);
      return;
    }
    paragraph.push(line.trim());
  });
  flushParagraph(); closeList();
  if (inCode) output.push(`<pre><code>${escapeHTML(code.join("\n"))}</code></pre>`);
  return output.join("\n");
}

function formatDate(value, long = false) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ru-RU", long
    ? { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }
    : { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }
  ).format(date).replace(",", " ·");
}

function isToday(value) {
  const date = new Date(value); const now = new Date();
  return date.toDateString() === now.toDateString();
}

function filteredArticles() {
  const query = state.query.toLocaleLowerCase("ru");
  return state.articles.filter((article) => {
    if (state.view === "unread" && state.read.has(article.id)) return false;
    if (state.view === "important" && !["high", "urgent", "important", "важно"].includes(article.priority)) return false;
    if (state.category !== "Все" && article.category !== state.category) return false;
    if (query) {
      const haystack = [article.title, article.summary, article.content, article.source, article.category, ...article.tags].join(" ").toLocaleLowerCase("ru");
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

function renderCategories() {
  const categories = ["Все", ...new Set(state.articles.map((item) => item.category))];
  $("#categoryRow").innerHTML = categories.map((category) => {
    const count = category === "Все" ? state.articles.length : state.articles.filter((item) => item.category === category).length;
    return `<button class="chip ${category === state.category ? "active" : ""}" data-category="${escapeHTML(category)}">${escapeHTML(category)} · ${count}</button>`;
  }).join("");
}

function renderMetrics() {
  const unread = state.articles.filter((item) => !state.read.has(item.id)).length;
  const important = state.articles.filter((item) => ["high", "urgent", "important", "важно"].includes(item.priority)).length;
  $("#allCount").textContent = state.articles.length;
  $("#unreadCount").textContent = unread;
  $("#importantCount").textContent = important;
  $("#totalMetric").textContent = state.articles.length;
  $("#todayMetric").textContent = state.articles.filter((item) => isToday(item.date)).length;
  $("#sourceMetric").textContent = new Set(state.articles.map((item) => item.source)).size;
  $("#latestMetric").textContent = state.articles[0] ? `Последнее обновление: ${formatDate(state.articles[0].date)}` : "Ждём первые материалы";
}

function renderFeed() {
  const articles = filteredArticles();
  if (!articles.length) {
    const hasAny = state.articles.length > 0;
    $("#feed").innerHTML = `<div class="empty"><strong>${hasAny ? "Ничего не найдено" : "Лента пока пуста"}</strong><p>${hasAny ? "Попробуйте изменить поиск или фильтры." : "Добавьте первый Markdown-файл в папку ленты — сообщение появится здесь автоматически."}</p></div>`;
    return;
  }
  $("#feed").innerHTML = articles.map((article) => {
    const read = state.read.has(article.id);
    const important = ["high", "urgent", "important", "важно"].includes(article.priority);
    const classes = ["news-card", read ? "is-read" : ""].filter(Boolean).join(" ");
    const tags = article.tags.slice(0, 3).map((tag) => `<span class="tag">#${escapeHTML(tag)}</span>`).join("");
    const image = safeMediaURL(article.image);
    const sourceURL = safeURL(article.url);
    return `<article class="${classes}" data-article="${article.id}">
      <div class="message-bubble">
        <div class="message-head">
          <strong>${escapeHTML(article.source)}</strong>
          <span class="category">${escapeHTML(article.category)}</span>
          ${!read ? '<span class="new-badge" title="Новое"></span>' : important ? '<span class="priority-mark" title="Важное"></span>' : ""}
          <time>${formatDate(article.date)}</time>
        </div>
        <h2>${escapeHTML(article.title)}</h2>
        ${image ? `<img class="message-image" src="${escapeHTML(image)}" alt="" loading="lazy" decoding="async">` : ""}
        <div class="message-content article-body">${renderMarkdown(article.content || article.summary)}</div>
        <div class="message-footer">
          <div class="tags">${tags}</div>
          ${sourceURL ? `<a class="source-link" href="${escapeHTML(sourceURL)}" target="_blank" rel="noreferrer">Источник</a>` : ""}
        </div>
      </div>
    </article>`;
  }).join("");
}

function render() {
  renderMetrics(); renderCategories(); renderFeed();
}

function markRead(id, element = null) {
  if (state.read.has(id)) return;
  state.read.add(id);
  localStorage.setItem("agent-news-read", JSON.stringify([...state.read].slice(-1000)));
  renderMetrics();
  if (state.view === "unread") {
    renderFeed();
  } else if (element) {
    element.classList.add("is-read");
    element.querySelector(".new-badge")?.remove();
  }
}

function setConnection(online, message = "Лента обновляется") {
  $("#statusDot").className = `connection-dot ${online ? "online" : "offline"}`;
  $("#statusText").textContent = online ? message : "Нет соединения";
}

function showToast(message) {
  const toast = $("#toast"); toast.textContent = message; toast.classList.add("show");
  clearTimeout(showToast.timer); showToast.timer = setTimeout(() => toast.classList.remove("show"), 2600);
}

async function loadData() {
  try {
    let news;
    if (window.AGENT_NEWS_STATIC) {
      const response = await fetch("./news.json", { cache: "no-store" });
      if (!response.ok) throw new Error("request failed");
      news = await response.json();
      state.config = news.config;
    } else {
      const [newsResponse, configResponse] = await Promise.all([fetch("/api/news"), fetch("/api/config")]);
      if (!newsResponse.ok || !configResponse.ok) throw new Error("request failed");
      news = await newsResponse.json();
      state.config = await configResponse.json();
    }
    document.title = state.config.title;
    $("#pageTitle").textContent = state.config.title;
    if (state.signature !== news.signature) {
      const hadSignature = state.signature !== null;
      state.articles = news.articles; state.signature = news.signature; render();
      if (hadSignature) showToast("Лента обновлена");
    }
    setConnection(true, window.AGENT_NEWS_STATIC ? "Статическая лента" : "Лента обновляется");
  } catch { setConnection(false); }
}

document.addEventListener("click", async (event) => {
  const article = event.target.closest("[data-article]");
  if (article && !event.target.closest("a, button")) markRead(article.dataset.article, article);
  const nav = event.target.closest("[data-view]");
  if (nav) {
    state.view = nav.dataset.view;
    $$(".nav-item").forEach((item) => item.classList.toggle("active", item === nav)); renderFeed();
  }
  const category = event.target.closest("[data-category]");
  if (category) { state.category = category.dataset.category; renderCategories(); renderFeed(); }
});

$("#searchInput").addEventListener("input", (event) => { state.query = event.target.value.trim(); renderFeed(); });
document.addEventListener("keydown", (event) => {
  if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) { event.preventDefault(); $("#searchInput").focus(); }
});

$("#todayLabel").textContent = new Intl.DateTimeFormat("ru-RU", { weekday: "long", day: "numeric", month: "long" }).format(new Date()).toLocaleUpperCase("ru");

async function startApp() {
  if (window.AGENT_NEWS_READY) await window.AGENT_NEWS_READY;
  await loadData();
  setInterval(() => loadData(), window.AGENT_NEWS_STATIC ? 60_000 : 8_000);
}

startApp();
