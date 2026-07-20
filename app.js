"use strict";

const APP_NAME = "JayBrief"; // display name — see CLAUDE.md "Rename policy"
const READ_KEY = "jb.read.v1";
const FILTER_KEY = "jb.filter.v1";
const EVENT_FILTER_KEY = "jb.event-filter.v1";
const STALE_MS = 10 * 60 * 1000;

const THEME_LABELS = { semi: "반도체", sw: "SW테크" };
const IMPACT_LABELS = {
  positive: "긍정", negative: "부정", mixed: "혼재", unclear: "불명확",
};
const HORIZON_LABELS = {
  immediate: "단기", quarter: "분기", long_term: "장기",
};
const CONFIDENCE_LABELS = { high: "신뢰 높음", medium: "신뢰 중간", low: "신뢰 낮음" };

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
  companies: [],
  events: [],
  filter: localStorage.getItem(FILTER_KEY) || "all",
  eventFilter: localStorage.getItem(EVENT_FILTER_KEY) || "all",
  read: loadReadSet(),
  lastLoad: 0,
  eventMonth: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
  selectedEventDate: null,
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
    const [feed, digest, companies, events] = await Promise.all([
      fetchJson("./data/feed.json").catch(() => null),
      fetchJson("./data/digest.json").catch(() => null),
      fetchJson("./companies.json").catch(() => null),
      fetchJson("./events.json").catch(() => null),
    ]);
    state.feed = feed;
    state.digest = digest;
    state.companies = companies ? companies.companies : [];
    state.events = events ? events.events : [];
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

function dateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function eventDate(event) {
  return event.all_day ? event.start_at.slice(0, 10) : dateKey(new Date(event.start_at));
}

function formatEventTime(event) {
  if (event.all_day) return "종일";
  return new Intl.DateTimeFormat("ko-KR", {
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(event.start_at));
}

function dayDistance(key) {
  const today = new Date();
  const target = new Date(`${key}T00:00:00`);
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target - start) / 86400000);
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

  const EDITION_LABELS = {
    morning: "아침", noon: "점심", evening: "저녁", night: "밤",
    am: "아침", pm: "저녁", // legacy archive files
  };
  const edition = EDITION_LABELS[d.edition] || "";
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

// ---------- events view ----------

function matchesEventFilter(event) {
  if (state.eventFilter === "all") return true;
  if (state.eventFilter === "macro") return event.type === "macro";
  return event.type !== "macro" && event.themes.includes(state.eventFilter);
}

function eventsForMonth() {
  const year = state.eventMonth.getFullYear();
  const month = state.eventMonth.getMonth();
  return state.events.filter((event) => {
    const date = new Date(`${eventDate(event)}T00:00:00`);
    return date.getFullYear() === year && date.getMonth() === month && matchesEventFilter(event);
  }).sort((a, b) => a.start_at.localeCompare(b.start_at));
}

function renderCalendar() {
  const grid = $("#calendar-grid");
  grid.textContent = "";
  const year = state.eventMonth.getFullYear();
  const month = state.eventMonth.getMonth();
  $("#calendar-month").textContent = `${year}년 ${month + 1}월`;
  const byDate = new Map();
  for (const event of eventsForMonth()) {
    const key = eventDate(event);
    if (!byDate.has(key)) byDate.set(key, []);
    byDate.get(key).push(event);
  }

  const frag = document.createDocumentFragment();
  const leadingDays = new Date(year, month, 1).getDay();
  for (let n = 0; n < leadingDays; n += 1) {
    frag.appendChild(el("span", "calendar-day blank"));
  }
  const days = new Date(year, month + 1, 0).getDate();
  for (let day = 1; day <= days; day += 1) {
    const key = dateKey(new Date(year, month, day));
    const button = el("button", "calendar-day");
    button.type = "button";
    button.appendChild(el("span", "day-number", String(day)));
    const dots = el("span", "event-dots");
    for (const event of (byDate.get(key) || []).slice(0, 3)) {
      dots.appendChild(el("span", `event-dot ${event.type}`));
    }
    button.appendChild(dots);
    button.classList.toggle("today", key === dateKey(new Date()));
    button.classList.toggle("selected", key === state.selectedEventDate);
    button.classList.toggle("has-events", byDate.has(key));
    button.addEventListener("click", () => {
      state.selectedEventDate = key;
      renderEvents();
    });
    frag.appendChild(button);
  }
  for (let n = leadingDays + days; n < 42; n += 1) {
    frag.appendChild(el("span", "calendar-day blank"));
  }
  grid.appendChild(frag);
}

function renderAgenda() {
  const agenda = $("#event-agenda");
  agenda.textContent = "";
  let events = eventsForMonth();
  if (state.selectedEventDate) {
    events = events.filter((event) => eventDate(event) === state.selectedEventDate);
    const selected = new Date(`${state.selectedEventDate}T00:00:00`);
    $("#agenda-title").textContent = `${selected.getMonth() + 1}월 ${selected.getDate()}일 일정`;
  } else {
    $("#agenda-title").textContent = "이번 달 일정";
  }
  $("#agenda-reset").classList.toggle("hidden", !state.selectedEventDate);
  $("#events-empty").classList.toggle("hidden", events.length > 0);

  const companies = new Map(state.companies.map((company) => [company.id, company]));
  let lastDate = null;
  for (const event of events) {
    const key = eventDate(event);
    if (key !== lastDate) {
      const date = new Date(`${key}T00:00:00`);
      agenda.appendChild(el("h3", "agenda-date", `${date.getMonth() + 1}월 ${date.getDate()}일`));
      lastDate = key;
    }
    const row = el("article", "event-row");
    const top = el("div", "event-row-top");
    const distance = dayDistance(key);
    top.appendChild(el("span", "event-dday", distance === 0 ? "D-DAY" : distance > 0 ? `D-${distance}` : `D+${-distance}`));
    top.appendChild(el("span", `event-type ${event.type}`, {
      earnings: "실적", conference: "행사", macro: "Macro",
    }[event.type] || event.type));
    top.appendChild(el("span", "event-time", formatEventTime(event)));
    row.appendChild(top);
    row.appendChild(el("h4", "", event.title));
    const companyNames = event.company_ids.map((id) => {
      const company = companies.get(id);
      if (!company) return id;
      return company.name === company.ticker
        ? company.name
        : `${company.name} · ${company.ticker}`;
    });
    if (companyNames.length) row.appendChild(el("p", "event-companies", companyNames.join(", ")));
    if (event.note) row.appendChild(el("p", "event-note", event.note));
    const source = el("a", "event-source", "공식 출처");
    const href = safeUrl(event.source_url);
    if (href) source.href = href;
    source.target = "_blank";
    source.rel = "noopener";
    row.appendChild(source);
    agenda.appendChild(row);
  }
}

function renderEvents() {
  renderCalendar();
  renderAgenda();
}

// ---------- shell ----------

function render() {
  $("#freshness").textContent =
    state.feed ? `갱신 ${relTime(state.feed.generated_at)}` : "";
  renderFeed();
  renderDigest();
  renderEvents();
}

function initTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
      tab.classList.add("active");
      const view = tab.dataset.view;
      $("#view-feed").classList.toggle("hidden", view !== "feed");
      $("#view-digest").classList.toggle("hidden", view !== "digest");
      $("#view-events").classList.toggle("hidden", view !== "events");
    });
  });
}

function initEventControls() {
  const chips = document.querySelectorAll("#event-chips .chip");
  chips.forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.eventFilter === state.eventFilter);
    chip.addEventListener("click", () => {
      state.eventFilter = chip.dataset.eventFilter;
      state.selectedEventDate = null;
      localStorage.setItem(EVENT_FILTER_KEY, state.eventFilter);
      chips.forEach((value) => value.classList.toggle("active", value === chip));
      renderEvents();
    });
  });
  $("#month-prev").addEventListener("click", () => {
    state.eventMonth = new Date(state.eventMonth.getFullYear(), state.eventMonth.getMonth() - 1, 1);
    state.selectedEventDate = null;
    renderEvents();
  });
  $("#month-next").addEventListener("click", () => {
    state.eventMonth = new Date(state.eventMonth.getFullYear(), state.eventMonth.getMonth() + 1, 1);
    state.selectedEventDate = null;
    renderEvents();
  });
  $("#agenda-reset").addEventListener("click", () => {
    state.selectedEventDate = null;
    renderEvents();
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
initEventControls();
$("#refresh-btn").addEventListener("click", load);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && Date.now() - state.lastLoad > STALE_MS) load();
});
load();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js");
}
