"use strict";

const APP_NAME = "JayBrief"; // display name — see CLAUDE.md "Rename policy"
const READ_KEY = "jb.read.v1";
const FILTER_KEY = "jb.filter.v1";
const STALE_MS = 10 * 60 * 1000;

const THEME_LABELS = { semi: "반도체", sw: "SW테크" };

function loadReadSet() {
  try {
    return new Set(JSON.parse(localStorage.getItem(READ_KEY) || "[]"));
  } catch {
    return new Set(); // one corrupt stored value must not brick the app
  }
}

const state = {
  feed: null,
  digest: null,
  filter: localStorage.getItem(FILTER_KEY) || "all",
  read: loadReadSet(),
  lastLoad: 0,
};

const $ = (sel) => document.querySelector(sel);

// ---------- data ----------

async function fetchJson(path) {
  const resp = await fetch(path, { cache: "no-cache" });
  if (!resp.ok) throw new Error(`${path}: HTTP ${resp.status}`);
  return resp.json();
}

async function load() {
  const btn = $("#refresh-btn");
  btn.classList.add("spin");
  try {
    const [feed, digest] = await Promise.all([
      fetchJson("./data/feed.json").catch(() => null),
      fetchJson("./data/digest.json").catch(() => null),
    ]);
    state.feed = feed;
    state.digest = digest;
    state.lastLoad = Date.now();
    render();
  } finally {
    btn.classList.remove("spin");
  }
}

// ---------- helpers ----------

function safeUrl(url) {
  return /^https?:\/\//i.test(url) ? url : null;
}

function relTime(iso) {
  const diff = Math.max(0, Date.now() - new Date(iso).getTime());
  const min = Math.floor(diff / 60000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}시간 전`;
  return `${Math.floor(hr / 24)}일 전`;
}

function saveRead() {
  // cap stored ids so localStorage never grows unbounded
  localStorage.setItem(READ_KEY, JSON.stringify([...state.read].slice(-2000)));
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

// ---------- feed view ----------

function renderFeed() {
  const list = $("#feed-list");
  list.textContent = "";
  const items = state.feed ? state.feed.items : [];
  const visible = items.filter(
    (i) => state.filter === "all" || i.themes.includes(state.filter)
  );
  $("#feed-empty").classList.toggle("hidden", visible.length > 0);

  const frag = document.createDocumentFragment();
  for (const item of visible) {
    const li = el("li", "feed-item" + (state.read.has(item.id) ? " read" : ""));
    const a = el("a");
    const href = safeUrl(item.url);
    if (href) a.href = href; // only http(s); no href = inert anchor
    a.target = "_blank";
    a.rel = "noopener";
    a.addEventListener("click", () => {
      state.read.add(item.id);
      saveRead();
      li.classList.add("read");
    });
    a.appendChild(el("p", "feed-title", item.title));
    const meta = el("div", "feed-meta");
    for (const theme of item.themes) {
      meta.appendChild(el("span", `badge ${theme}`, THEME_LABELS[theme] || theme));
    }
    meta.appendChild(el("span", "", item.source));
    meta.appendChild(el("span", "", "·"));
    meta.appendChild(el("span", "", relTime(item.published)));
    a.appendChild(meta);
    li.appendChild(a);
    frag.appendChild(li);
  }
  list.appendChild(frag);
}

// ---------- digest view ----------

function renderDigest() {
  const body = $("#digest-body");
  const meta = $("#digest-meta");
  body.textContent = "";
  meta.textContent = "";
  const d = state.digest;
  $("#digest-empty").classList.toggle("hidden", !!d);
  if (!d) return;

  const edition = d.edition === "am" ? "아침" : "저녁";
  meta.textContent = `${d.date} ${edition} 브리핑 · ${relTime(d.generated_at)} 생성`;

  const itemById = new Map((state.feed ? state.feed.items : []).map((i) => [i.id, i]));
  for (const theme of d.themes || []) {
    const section = el("section", "digest-theme");
    section.appendChild(el("h2", "", THEME_LABELS[theme.theme] || theme.theme));
    if (theme.overview) section.appendChild(el("p", "digest-overview", theme.overview));
    for (const story of theme.stories || []) {
      const card = el("article", "story");
      const h3 = el("h3");
      if (story.importance >= 3) h3.appendChild(el("span", "imp", "🔥"));
      h3.appendChild(document.createTextNode(story.headline));
      card.appendChild(h3);
      card.appendChild(el("p", "", story.body));
      const links = el("div", "story-links");
      for (const id of story.article_ids || []) {
        const item = itemById.get(id);
        const href = item && safeUrl(item.url);
        if (!href) continue;
        const a = el("a", "", item.source);
        a.href = href;
        a.target = "_blank";
        a.rel = "noopener";
        links.appendChild(a);
      }
      if (links.childNodes.length) card.appendChild(links);
      section.appendChild(card);
    }
    body.appendChild(section);
  }
}

// ---------- shell ----------

function render() {
  $("#freshness").textContent =
    state.feed ? `갱신 ${relTime(state.feed.generated_at)}` : "";
  renderFeed();
  renderDigest();
}

function initTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const view = tab.dataset.view;
      $("#view-feed").classList.toggle("hidden", view !== "feed");
      $("#view-digest").classList.toggle("hidden", view !== "digest");
    });
  });
}

function initChips() {
  const chips = document.querySelectorAll("#theme-chips .chip");
  chips.forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.theme === state.filter);
    chip.addEventListener("click", () => {
      state.filter = chip.dataset.theme;
      localStorage.setItem(FILTER_KEY, state.filter);
      chips.forEach((c) => c.classList.toggle("active", c === chip));
      renderFeed();
    });
  });
}

document.title = APP_NAME;
$("#app-title").textContent = APP_NAME;
initTabs();
initChips();
$("#refresh-btn").addEventListener("click", load);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && Date.now() - state.lastLoad > STALE_MS) load();
});
load();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js");
}
