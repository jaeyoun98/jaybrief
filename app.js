"use strict";

const APP_NAME = "JayBrief"; // display name — see CLAUDE.md "Rename policy"
const READ_KEY = "jb.read.v1";
const FILTER_KEY = "jb.filter.v1";
const EVENT_FILTER_KEY = "jb.event-filter.v1";
const RANK_KEY = "jb.rank.v1";
const STALE_MS = 10 * 60 * 1000;
const TOP_SCORE_MIN = 3.0; // matches pipeline scoring: tier-1 exclusive or watchlist mention

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

function loadRank() {
  const value = localStorage.getItem(RANK_KEY);
  return value === "all" || value === "top" ? value : "top";
}

const state = {
  feed: null,
  digest: null,
  digestIndex: [],
  digestPath: null,
  companies: [],
  events: [],
  filter: localStorage.getItem(FILTER_KEY) || "all",
  eventFilter: localStorage.getItem(EVENT_FILTER_KEY) || "all",
  rank: loadRank(),
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
    const [feed, digest, companies, events, digestIndex] = await Promise.all([
      fetchJson("./data/feed.json").catch(() => null),
      fetchJson("./data/digest.json").catch(() => null),
      fetchJson("./companies.json").catch(() => null),
      fetchJson("./events.json").catch(() => null),
      fetchJson("./data/digests/index.json").catch(() => null),
    ]);
    state.feed = feed;
    state.digest = digest;
    state.companies = companies ? companies.companies : [];
    state.events = events ? events.events : [];
    state.digestIndex = digestIndex ? digestIndex.digests : [];
    // select the index entry for the digest actually displayed; a stale index must not mislabel it
    const current = digest && state.digestIndex.find((e) => e.generated_at === digest.generated_at);
    state.digestPath = current ? current.path : null;
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

function clusterFeed(items) {
  const groups = new Map();
  for (const item of items) {
    const key = item.cluster_id || item.id; // tolerate cached pre-cluster feeds
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  const clusters = [];
  for (const [key, members] of groups) {
    const rep = members.find((m) => m.id === key) || members[0];
    const sources = new Set(members.map((m) => m.source.trim().toLowerCase()));
    clusters.push({
      rep,
      members,
      themes: Object.keys(THEME_LABELS).filter(
        (theme) => members.some((m) => m.themes.includes(theme))
      ),
      companyIds: [...new Set(members.flatMap((m) => m.company_ids || []))],
      score: typeof rep.score === "number" ? rep.score : 0,
      sourceCount: sources.size,
      latest: members.reduce(
        (max, m) => (m.published > max ? m.published : max), rep.published
      ),
    });
  }
  return clusters;
}

function renderFeedCard(cluster) {
  const { rep, members } = cluster;
  const allRead = members.every((m) => state.read.has(m.id));
  const li = el("li", "feed-item" + (allRead ? " read" : ""));
  const a = el("a");
  const href = safeUrl(rep.url);
  if (href) a.href = href; // only http(s); no href = inert anchor
  a.target = "_blank";
  a.rel = "noopener";
  a.addEventListener("click", () => {
    for (const m of members) state.read.add(m.id);
    saveRead();
    li.classList.add("read");
  });
  a.appendChild(el("p", "feed-title", rep.title));
  const meta = el("div", "feed-meta");
  for (const theme of cluster.themes) {
    meta.appendChild(el("span", `badge ${theme}`, THEME_LABELS[theme] || theme));
  }
  meta.appendChild(el("span", "", rep.source));
  meta.appendChild(el("span", "", "·"));
  meta.appendChild(el("span", "", relTime(cluster.latest)));
  a.appendChild(meta);
  li.appendChild(a);

  if (cluster.sourceCount > 1) {
    // Other members expand as pills OUTSIDE the card anchor (nested anchors break).
    const sourcesBox = el("div", "feed-sources hidden");
    for (const m of members) {
      if (m.id === rep.id) continue;
      const pill = el("a", "", m.source);
      const pillHref = safeUrl(m.url);
      if (pillHref) pill.href = pillHref;
      pill.target = "_blank";
      pill.rel = "noopener";
      pill.title = m.title;
      pill.addEventListener("click", () => {
        state.read.add(m.id);
        saveRead();
      });
      sourcesBox.appendChild(pill);
    }
    const toggle = el("span", "src-count", `출처 ${cluster.sourceCount}곳`);
    toggle.setAttribute("role", "button");
    toggle.tabIndex = 0;
    const flip = (event) => {
      event.preventDefault(); // the toggle sits inside the card anchor
      event.stopPropagation();
      sourcesBox.classList.toggle("hidden");
    };
    toggle.addEventListener("click", flip);
    toggle.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") flip(event);
    });
    meta.appendChild(toggle);
    li.appendChild(sourcesBox);
  }

  for (const id of cluster.companyIds) {
    const company = state.companies.find((c) => c.id === id);
    if (company) meta.appendChild(el("span", "company-chip", company.name));
  }
  return li;
}

function renderFeed() {
  const list = $("#feed-list");
  list.textContent = "";
  const items = state.feed ? state.feed.items : [];
  // Cached pre-cluster feed.json has no scores; 주요 would be silently empty.
  const hasScores = items.some((i) => typeof i.score === "number");
  $("#rank-chips").classList.toggle("hidden", !hasScores);
  const rank = hasScores ? state.rank : "all";

  const visible = clusterFeed(items).filter(
    (c) => state.filter === "all" || c.themes.includes(state.filter)
  );
  const clusters = rank === "top"
    ? visible.filter((c) => c.score >= TOP_SCORE_MIN)
    : visible;
  clusters.sort((a, b) =>
    (rank === "top" && b.score - a.score) || b.latest.localeCompare(a.latest)
  );

  const empty = $("#feed-empty");
  empty.classList.toggle("hidden", clusters.length > 0);
  empty.textContent = clusters.length === 0 && visible.length > 0
    ? "주요 소식이 없습니다. 전체 보기로 전환해 보세요."
    : "표시할 기사가 없습니다.";

  const frag = document.createDocumentFragment();
  for (const cluster of clusters) frag.appendChild(renderFeedCard(cluster));
  list.appendChild(frag);
}

// ---------- digest view ----------

function renderDigest() {
  const body = $("#digest-body");
  const meta = $("#digest-meta");
  body.textContent = "";
  meta.textContent = "";
  const d = state.digest;
  const archive = $("#digest-archive");
  archive.textContent = "";
  for (const entry of state.digestIndex) {
    const option = el("option", "", `${entry.date} ${{
      morning: "아침", noon: "점심", evening: "저녁", night: "밤",
    }[entry.edition] || entry.edition}`);
    option.value = entry.path;
    option.selected = entry.path === state.digestPath;
    archive.appendChild(option);
  }
  if (!state.digestPath) archive.selectedIndex = -1;
  $(".digest-toolbar").classList.toggle("hidden", state.digestIndex.length < 2);
  $("#digest-empty").classList.toggle("hidden", !!d);
  if (!d) return;

  const EDITION_LABELS = {
    morning: "아침", noon: "점심", evening: "저녁", night: "밤",
    am: "아침", pm: "저녁", // legacy archive files
  };
  const edition = EDITION_LABELS[d.edition] || "";
  meta.textContent = `${d.date} ${edition} 브리핑 · ${relTime(d.generated_at)} 생성`;

  const itemById = new Map([
    ...(state.feed ? state.feed.items : []),
    ...(d.articles || []),
  ].map((item) => [item.id, item]));
  const companyById = new Map(state.companies.map((company) => [company.id, company]));
  const eventById = new Map(state.events.map((event) => [event.id, event]));
  for (const theme of d.themes || []) {
    const section = el("section", "digest-theme");
    section.appendChild(el("h2", "", THEME_LABELS[theme.theme] || theme.theme));
    if (theme.overview) section.appendChild(el("p", "digest-overview", theme.overview));
    for (const story of theme.stories || []) {
      const card = el("article", "story");
      const h3 = el("h3");
      h3.appendChild(document.createTextNode(story.headline));
      if (story.importance >= 3) h3.appendChild(el("span", "importance", "중요"));
      card.appendChild(h3);

      const signals = el("div", "story-signals");
      if (story.impact) signals.appendChild(el("span", `signal impact-${story.impact}`, IMPACT_LABELS[story.impact] || story.impact));
      if (story.horizon) signals.appendChild(el("span", "signal", HORIZON_LABELS[story.horizon] || story.horizon));
      if (story.confidence) signals.appendChild(el("span", "signal", CONFIDENCE_LABELS[story.confidence] || story.confidence));
      if (signals.childNodes.length) card.appendChild(signals);

      if (story.facts && story.facts.length) {
        const facts = el("ul", "story-facts");
        for (const fact of story.facts) facts.appendChild(el("li", "", fact));
        card.appendChild(facts);
      }
      const interpretation = story.interpretation || story.body;
      if (interpretation) card.appendChild(el("p", "story-interpretation", interpretation));

      const companies = (story.affected_company_ids || [])
        .map((id) => companyById.get(id))
        .filter(Boolean)
        .map((company) => company.name === company.ticker
          ? company.name
          : `${company.name} · ${company.ticker}`);
      if (companies.length) card.appendChild(el("p", "story-companies", companies.join(", ")));
      if (story.watch_next) {
        const watch = el("p", "story-watch");
        watch.appendChild(el("strong", "", "다음 확인 "));
        watch.appendChild(document.createTextNode(story.watch_next));
        card.appendChild(watch);
      }

      const eventLinks = el("div", "story-events");
      for (const id of story.upcoming_event_ids || []) {
        const event = eventById.get(id);
        if (!event) continue;
        const button = el("button", "story-event", `일정 · ${event.title}`);
        button.type = "button";
        button.addEventListener("click", () => {
          const key = eventDate(event);
          const date = new Date(`${key}T00:00:00`);
          state.eventMonth = new Date(date.getFullYear(), date.getMonth(), 1);
          state.selectedEventDate = key;
          document.querySelector('.tab[data-view="events"]').click();
          renderEvents();
        });
        eventLinks.appendChild(button);
      }
      if (eventLinks.childNodes.length) card.appendChild(eventLinks);

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

function initDigestControls() {
  $("#digest-archive").addEventListener("change", async (event) => {
    const path = event.target.value;
    if (!path) return;
    const previousPath = state.digestPath;
    event.target.disabled = true;
    try {
      state.digest = await fetchJson(`./${path}`);
      state.digestPath = path;
      renderDigest();
    } catch (error) {
      console.error(error);
      event.target.value = previousPath;
    } finally {
      event.target.disabled = false;
    }
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

function initRankChips() {
  const chips = document.querySelectorAll("#rank-chips .chip");
  chips.forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.rank === state.rank);
    chip.addEventListener("click", () => {
      state.rank = chip.dataset.rank;
      localStorage.setItem(RANK_KEY, state.rank);
      chips.forEach((c) => c.classList.toggle("active", c === chip));
      renderFeed();
    });
  });
}

document.title = APP_NAME;
$("#app-title").textContent = APP_NAME;
initTabs();
initChips();
initRankChips();
initEventControls();
initDigestControls();
$("#refresh-btn").addEventListener("click", load);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && Date.now() - state.lastLoad > STALE_MS) load();
});
load();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js");
}
