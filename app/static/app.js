/* NutriLens: a small, dependency-free client. All nutrition data comes from the API. */
"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const esc = (value = "") =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
const number = (value) => (Number.isFinite(Number(value)) ? Number(value) : 0);
const fmt = (value) => Math.round(number(value)).toLocaleString();
const pct = (value, goal) =>
  Math.max(
    0,
    Math.min(100, number(goal) > 0 ? (number(value) / number(goal)) * 100 : 0),
  );
const initials = (name) =>
  String(name || "You")
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
const MEAL_TYPES = ["breakfast", "lunch", "dinner", "snack"];
const MEAL_EMOJI = {
  breakfast: "🥑",
  lunch: "🥗",
  dinner: "🍲",
  snack: "🍓",
};
const mealType = (meal) =>
  MEAL_TYPES.includes(meal.meal_type) ? meal.meal_type : "snack";
const icons = {
  overview:
    '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
  diary:
    '<path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-2H4zM20 4h-4a3 3 0 0 0-3 3v14a4 4 0 0 1 4-2h3z"/>',
  community:
    '<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M17 5a3 3 0 0 1 0 6m4 10v-3a6 6 0 0 0-4-5"/>',
  settings:
    '<path d="m10 3-.7 2.1-2 .9-2.1-.4-2 3.4 1.4 1.7v2.6L3.2 15l2 3.4 2.1-.4 2 .9.7 2.1h4l.7-2.1 2-.9 2.1.4 2-3.4-1.4-1.7v-2.6L20.8 9l-2-3.4-2.1.4-2-.9L14 3z"/><circle cx="12" cy="12" r="3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  left: '<path d="m15 5-7 7 7 7"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  calendar:
    '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M16 3v4M8 3v4M3 11h18M8 15h2m4 0h2"/>',
  plane: '<path d="m21 3-7 18-4-8-8-3L21 3Z"/><path d="m10 13 5-5"/>',
  leaf: '<path d="M20 3c0 11-3 17-10 17a6 6 0 0 1-6-6c0-7 7-8 16-11Z"/><path d="M3 22 14 11"/>',
  flame:
    '<path d="M13 2c1 5-4 7-4 10-2-1-3-3-3-3-2 3-3 5-2 8a8 8 0 0 0 16-2c0-5-4-9-7-13Z"/><path d="M12 13c-4 4-3 7 0 7s4-3 0-7Z"/>',
  protein:
    '<path d="M8 15c-4-4-2-8 2-8 1-4 7-5 9-1 4 5-1 11-5 10l-5 5-3-3Z"/><path d="m7 17-3-1-2 2 4 4 2-2"/>',
  carbs:
    '<path d="M12 22V5m0 6C5 12 4 7 5 5c4 0 7 2 7 6Zm0 5c7 1 8-4 7-6-4 0-7 2-7 6Zm0-10c-3-1-3-4 0-5 3 1 3 4 0 5Z"/>',
  fat: '<path d="M12 2C8 7 5 11 5 15a7 7 0 0 0 14 0c0-4-3-8-7-13Z"/><path d="M8 15c0 2 1 3 3 3"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  camera:
    '<path d="m8 5 2-3h4l2 3h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z"/><circle cx="12" cy="13" r="4"/>',
  edit: '<path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-4-4L5 15Z"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  logout: '<path d="M9 4H4v16h5m6-12 4 4-4 4M8 12h12"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.01"/>',
  heart:
    '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
  upload:
    '<path d="M12 16V3m-5 5 5-5 5 5M3 15v5a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-5"/>',
  download: '<path d="M12 3v13m-5-5 5 5 5-5M3 16v5h18v-5"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1"/>',
  moon: '<path d="M21 13a9 9 0 0 1-10-10A9 9 0 1 0 21 13Z"/>',
  bowl: '<path d="M3 11h18a9 9 0 0 1-18 0ZM6 21h12M7 3v4m5-5v5m5-4v4"/>',
  lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4m-4 5v2"/>',
  sparkle:
    '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/>',
};
const icon = (name, size = 18) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.leaf}</svg>`;
const brand = () =>
  '<span class="brand-mark" aria-hidden="true">n<span>·</span></span><span class="brand-word">nutri<span>lens</span></span>';
const bowlArt = () =>
  `<svg viewBox="0 0 300 230" fill="none" aria-hidden="true"><ellipse cx="155" cy="121" rx="102" ry="91" fill="#e0e6d2"/><ellipse cx="155" cy="114" rx="94" ry="86" fill="#fffdf3"/><ellipse cx="155" cy="114" rx="80" ry="73" fill="#f0eedf"/><path d="M93 129c-26-26-9-41 6-43-4-23 24-29 36-13 21-15 38 6 25 24 13 12 2 28-12 31-10 23-40 24-55 1" fill="#a4b581"/><path d="M94 106c-14-11-5-25 11-23 0-14 17-17 25-5 11-7 24 1 19 13 18 10 8 27-6 29-7 13-23 17-35 3" fill="#8fa771"/><path d="m114 131 13-46m-8 29-15-9m19-4 13-9" stroke="#6f8952" stroke-width="2" stroke-linecap="round"/><path d="M157 57c22-11 56 5 66 30l-45 18-29-26 8-22Z" fill="#eedfc1"/><path d="m164 68 30 14m-24-3 30 14m-12-28 23 16" stroke="#d7c8a5" stroke-width="2" stroke-linecap="round"/><path d="M162 120c10-21 44-28 60-9 12 15-1 46-24 55-23 8-49-18-36-46Z" fill="#e59a72"/><path d="m177 118 29 16m-36-5 26 17m-20-7 13 13" stroke="#f6c6a4" stroke-width="4" stroke-linecap="round"/><circle cx="141" cy="143" r="20" fill="#e6ad71"/><circle cx="141" cy="143" r="15" fill="#f4c990"/><path d="m141 129-1 29m-12-19 25 9m-23 4 22-18" stroke="#f8e4b6" stroke-width="2"/><circle cx="123" cy="166" r="12" fill="#b86e4b"/><circle cx="123" cy="166" r="8" fill="#eeb188"/><circle cx="148" cy="176" r="9" fill="#b86e4b"/><circle cx="148" cy="176" r="6" fill="#eeb188"/><circle cx="102" cy="146" r="3" fill="#738c57"/><circle cx="164" cy="160" r="3" fill="#738c57"/><circle cx="170" cy="92" r="2" fill="#8e9c69"/><path d="m28 148 17-69m-23 29 7-32m2 34 8-32m1 35 8-32" stroke="#b7bc9d" stroke-width="4" stroke-linecap="round"/><path d="m255 155 8-76c14 21 10 43-3 48" stroke="#b7bc9d" stroke-width="5" stroke-linecap="round"/><path d="M245 39c11-17 25-18 35-15-4 15-15 24-30 21" fill="#9caf7d"/><path d="m245 47 24-18" stroke="#839966" stroke-width="2"/><circle cx="62" cy="179" r="4" fill="#d5ad79"/><circle cx="239" cy="180" r="3" fill="#d5ad79"/></svg>`;

const state = {
  user: null,
  config: {},
  page: "overview",
  date: "",
  days: 7,
  dashboard: null,
  community: [],
  communityDay: {},
  communityMeals: {},
  authTab: "login",
  modal: null,
  requestId: 0,
  demo: false,
};
let toastTimer;
let modalReturnFocus;
let photoObjectUrl;

function today() {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone:
        state.user?.timezone ||
        Intl.DateTimeFormat().resolvedOptions().timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  } catch {
    return localDate(new Date());
  }
}
function localDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
function dateObject(date) {
  return new Date(`${date}T12:00:00`);
}
function shiftDate(date, delta) {
  const result = dateObject(date);
  result.setDate(result.getDate() + delta);
  return localDate(result);
}
function readableDate(date, options = { month: "short", day: "numeric" }) {
  return dateObject(date).toLocaleDateString(undefined, options);
}
function mealTime(value, zone) {
  try {
    return new Date(value).toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      timeZone: zone || state.user?.timezone || undefined,
    });
  } catch {
    return "";
  }
}
function dateTimeInput(value) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: state.user?.timezone || "UTC",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(value ? new Date(value) : new Date());
  const fields = Object.fromEntries(
    parts.map((part) => [part.type, part.value]),
  );
  return `${fields.year}-${fields.month}-${fields.day}T${fields.hour}:${fields.minute}`;
}
function safeImage(value) {
  if (!value) return "";
  try {
    const url = new URL(value, location.origin);
    return url.origin === location.origin &&
      ["http:", "https:"].includes(url.protocol)
      ? url.href
      : "";
  } catch {
    return "";
  }
}
function normalizeUser(value) {
  return value?.user || value;
}

async function api(path, options = {}) {
  const headers = { "X-Requested-With": "NutriLens", ...options.headers };
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  let data;
  if (response.status !== 204) {
    try {
      data = await response.json();
    } catch {
      data = null;
    }
  }
  if (!response.ok) {
    const detail = data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item.msg).join(". ")
          : "Something went wrong. Please try again.";
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return data;
}
function toast(message, error = false) {
  clearTimeout(toastTimer);
  $("#toast-root").innerHTML =
    `<div role="status" class="toast${error ? " error" : ""}">${icon(error ? "info" : "check", 16)}<span>${esc(message)}</span></div>`;
  toastTimer = setTimeout(
    () => {
      $("#toast-root").innerHTML = "";
    },
    error ? 6500 : 4000,
  );
}
function emptyState(
  title,
  copy,
  action = "add-meal",
  button = "Log your first meal",
  symbol = "bowl",
) {
  return `<div class="empty-state"><div class="empty-icon">${icon(symbol, 25)}</div><h3>${esc(title)}</h3><p>${esc(copy)}</p>${button ? `<button class="btn btn-primary btn-small" data-action="${esc(action)}">${icon("plus", 14)}${esc(button)}</button>` : ""}</div>`;
}
function nav(page, label, symbol, mobile = false) {
  return `<button type="button" class="nav-link${state.page === page ? " active" : ""}" data-action="navigate" data-page="${page}"${state.page === page ? ' aria-current="page"' : ""}>${icon(symbol, 18)}<span>${label}</span>${!mobile && page === "community" ? '<span class="nav-count">↗</span>' : ""}</button>`;
}
function renderShell() {
  const user = state.user;
  const pageLabel = {
    overview: "Overview",
    diary: "Food diary",
    community: "Community",
    settings: "Settings",
  }[state.page];
  $("#app").innerHTML = `<div class="app-shell">
    <aside class="sidebar" aria-label="Main navigation"><a class="brand" href="#overview" aria-label="NutriLens home">${brand()}</a><div class="nav-label">YOUR SPACE</div><nav class="nav-items">${nav("overview", "Overview", "overview")}${nav("diary", "Food diary", "diary")}${nav("community", "Community", "community")}</nav><div class="sidebar-divider"></div><nav>${nav("settings", "Settings", "settings")}</nav>
      <div class="sidebar-bottom"><div class="telegram-card"><div class="plane">${icon("plane", 18)}</div><h3>A photo is all it takes.</h3><p>Send your meal on Telegram.<br>We’ll take it from there.</p><button type="button" data-action="navigate" data-page="settings">${user.telegram_connected ? "Telegram connected" : "Connect Telegram"}${icon(user.telegram_connected ? "check" : "arrow", 13)}</button></div>
      <div class="sidebar-profile"><div class="avatar">${esc(initials(user.display_name))}</div><div class="profile-info"><strong>${esc(user.display_name)}</strong><span>Your personal space</span></div><button type="button" class="icon-button" data-action="logout" aria-label="Sign out" title="Sign out">${icon("logout", 17)}</button></div></div>
    </aside>
    <div class="workspace"><header class="topbar"><div class="breadcrumb">Your space ${icon("chevron", 11)}<strong>${pageLabel}</strong></div><a href="#overview" class="brand" aria-label="NutriLens home">${brand()}</a><div class="topbar-right"><span class="live-date">${icon("calendar", 13)}${esc(readableDate(today(), { weekday: "short", month: "long", day: "numeric", year: "numeric" }))}</span><button type="button" class="icon-button" data-action="navigate" data-page="settings" aria-label="Account settings">${icon("settings", 18)}</button><div class="avatar" aria-label="${esc(user.display_name)}">${esc(initials(user.display_name))}</div></div></header>
    ${state.demo || user.is_demo ? '<div class="demo-banner"><strong>Demo workspace</strong> · Sample meals are here to explore. Your changes stay in this separate demo account.</div>' : ""}
    <main class="main-content" id="main-content" tabindex="-1"><div class="page-loading" role="status"><span class="spinner"></span>Loading your space…</div></main></div>
    <nav class="mobile-nav" aria-label="Mobile navigation">${nav("overview", "Overview", "overview", true)}${nav("diary", "Diary", "diary", true)}<button class="mobile-add" data-action="add-meal" aria-label="Add a meal">${icon("plus", 22)}</button>${nav("community", "Community", "community", true)}${nav("settings", "Settings", "settings", true)}</nav>
  </div>`;
}
async function navigate(page, options = {}) {
  if (!["overview", "diary", "community", "settings"].includes(page))
    page = "overview";
  state.page = page;
  if (location.hash !== `#${page}`) history.replaceState(null, "", `#${page}`);
  renderShell();
  await loadPage();
  if (options.focus) $("#main-content")?.focus({ preventScroll: true });
}
async function loadPage() {
  const request = ++state.requestId;
  const main = $("#main-content");
  if (!main) return;
  main.setAttribute("aria-busy", "true");
  try {
    if (state.page === "overview" || state.page === "diary") {
      const data = await api(
        `/api/dashboard?date=${encodeURIComponent(state.date)}&days=${state.days}`,
      );
      if (request !== state.requestId) return;
      state.dashboard = data;
      main.innerHTML =
        state.page === "overview" ? renderDashboard() : renderDiary();
    } else if (state.page === "community") {
      const data = await api("/api/community");
      if (request !== state.requestId) return;
      state.community = data.users || [];
      main.innerHTML = renderCommunity();
    } else {
      main.innerHTML = renderSettings();
    }
  } catch (error) {
    if (request !== state.requestId) return;
    if (error.status === 401) {
      state.user = null;
      renderAuth();
      return;
    }
    main.innerHTML = `<div class="error-state" role="alert"><h2>We couldn’t load this page.</h2><p>${esc(error.message)}</p><button class="btn btn-secondary" data-action="retry">Try again ${icon("arrow", 14)}</button></div>`;
  } finally {
    main.removeAttribute("aria-busy");
  }
}

function clearCommunityCache() {
  state.community = [];
  state.communityDay = {};
  state.communityMeals = {};
}
function renderCommunityPage(focusUser, focusDate) {
  const main = $("#main-content");
  if (!main) return;
  main.innerHTML = renderCommunity();
  // innerHTML replaces the bar that was just pressed, so put focus back on its replacement.
  if (focusUser)
    [...main.querySelectorAll('[data-action="community-day"]')]
      .find(
        (bar) => bar.dataset.user === focusUser && bar.dataset.date === focusDate,
      )
      ?.focus();
}

// Pick up Telegram meals while the dashboard is open, without replacing an
// active form or interrupting keyboard navigation. Refresh only changed data.
let backgroundRefreshRunning = false;
async function refreshProgress() {
  if (
    !state.user ||
    document.hidden ||
    state.modal ||
    backgroundRefreshRunning ||
    !["overview", "diary", "community"].includes(state.page)
  )
    return;
  const currentRequest = state.requestId;
  const currentPage = state.page;
  const main = $("#main-content");
  if (!main || main.getAttribute("aria-busy") === "true") return;
  backgroundRefreshRunning = true;
  try {
    const data = await api(
      currentPage === "community"
        ? "/api/community"
        : `/api/dashboard?date=${encodeURIComponent(state.date)}&days=${state.days}`,
    );
    if (
      state.requestId !== currentRequest ||
      state.page !== currentPage ||
      state.modal ||
      (main.contains(document.activeElement) &&
        document.activeElement.matches(
          "input,select,textarea,button:focus-visible,a:focus-visible",
        ))
    )
      return;
    if (currentPage === "community") {
      if (JSON.stringify(state.community) !== JSON.stringify(data.users)) {
        state.community = data.users || [];
        main.innerHTML = renderCommunity();
      }
    } else if (JSON.stringify(state.dashboard) !== JSON.stringify(data)) {
      state.dashboard = data;
      main.innerHTML =
        currentPage === "overview" ? renderDashboard() : renderDiary();
    }
  } catch (error) {
    if (error.status === 401 && state.requestId === currentRequest) {
      state.user = null;
      state.dashboard = null;
      clearCommunityCache();
      renderAuth("Your session expired. Please sign in again.");
    }
  } finally {
    backgroundRefreshRunning = false;
  }
}
setInterval(refreshProgress, 30000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshProgress();
});
function dateControls() {
  return `<div class="date-tools">${state.date !== today() ? '<button class="today-link" data-action="today">Today</button>' : ""}<div class="date-control"><button data-action="previous-date" aria-label="Previous day">${icon("left", 12)}</button><input id="selected-date" type="date" min="1970-01-01" aria-label="Meal date" value="${esc(state.date)}" max="${today()}"/><button data-action="next-date" aria-label="Next day"${state.date >= today() ? " disabled" : ""}>${icon("chevron", 12)}</button></div></div>`;
}
function heading(title, subtitle, add = true) {
  return `<div class="page-heading"><div><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div>${add ? `<button class="btn btn-primary" data-action="add-meal">${icon("plus", 16)}<span class="desktop-text">Log a meal</span></button>` : ""}</div>`;
}
function renderDashboard() {
  const data = state.dashboard,
    totals = data.totals,
    goals = data.goals;
  const consumed = number(totals.calories),
    remaining = Math.max(0, number(goals.calories) - consumed),
    over = Math.max(0, consumed - number(goals.calories));
  const ringLength = 2 * Math.PI * 73;
  const name = state.user.display_name.trim().split(/\s+/)[0];
  const macros = [
    ["protein", "Protein", "#9aaf89"],
    ["carbs", "Carbs", "#e6bf73"],
    ["fat", "Fats", "#e9a584"],
  ];
  return `${heading(`Your daily overview`, `Welcome back, ${name}. Let’s make room for feeling good.`)}
    <section class="hero-banner" aria-label="A mindful moment"><div class="hero-content"><div class="eyebrow">A LITTLE PROGRESS, EVERY DAY</div><h2>A little more mindful,<br>a little more you.</h2><p>Good food. Small steps. A healthier relationship with your day.</p></div><div class="hero-art">${bowlArt()}</div></section>
    ${renderPlanCards(data)}
    <div class="section-toolbar"><h2>${state.date === today() ? "Today, in balance." : "Your day, in balance."}</h2>${dateControls()}</div>
    <section class="summary-grid" aria-label="Daily nutrition"><div class="card calorie-card"><div class="card-head"><h3>Calorie intake</h3><span class="chip">${icon("leaf", 11)}Daily balance</span></div><div class="ring-container"><svg class="calorie-ring" viewBox="0 0 181 181" role="img" aria-label="${fmt(consumed)} of ${fmt(goals.calories)} calories"><circle cx="90.5" cy="90.5" r="73" fill="none" stroke="#f1f1e8" stroke-width="10"/><circle cx="90.5" cy="90.5" r="73" fill="none" stroke="#eaa47d" stroke-width="10" stroke-linecap="round" stroke-dasharray="${ringLength}" stroke-dashoffset="${ringLength * (1 - pct(consumed, goals.calories) / 100)}"/></svg><div class="ring-center"><span class="flame">${icon("flame", 19)}</span><strong>${fmt(consumed)}</strong><span>of ${fmt(goals.calories)} kcal</span></div></div><div class="calorie-bottom"><div><i class="dot"></i><strong>${fmt(consumed)}</strong><span>eaten</span></div><div><i class="dot light"></i><strong>${fmt(over || remaining)}</strong><span>${over ? "over goal" : "remaining"}</span></div></div></div>
    <div class="card macro-card"><div class="card-head"><h3>Your macronutrients</h3><span class="small muted">A nourishing mix</span></div><div class="macro-list">${macros.map(([key, label, color]) => `<div class="macro-row"><div class="macro-row-top"><div class="macro-label"><span class="macro-icon ${key}">${icon(key, 15)}</span>${label}</div><div class="macro-value">${fmt(totals[key])}g <span>/ ${fmt(goals[key])}g</span></div></div><div class="progress-track" role="progressbar" aria-label="${label}" aria-valuemin="0" aria-valuemax="${Math.max(1, number(goals[key]), number(totals[key]))}" aria-valuenow="${number(totals[key])}"><div class="progress-fill" style="width:${pct(totals[key], goals[key])}%;background:${color}"></div></div></div>`).join("")}</div><div class="macro-footer">${icon("info", 12)}Your goals are personal. Adjust them in settings.</div></div></section>
    <section class="middle-grid" aria-label="Progress over time"><div class="card weekly-card"><div class="card-head"><h3>Your weekly rhythm</h3><div class="segmented" aria-label="Chart period"><button data-action="chart-days" data-days="7" class="${state.days === 7 ? "active" : ""}" aria-pressed="${state.days === 7}">7 days</button><button data-action="chart-days" data-days="30" class="${state.days === 30 ? "active" : ""}" aria-pressed="${state.days === 30}">30 days</button></div></div>${weeklyChart(data.weekly, goals.calories)}</div>${streakCard(data)}</section>
    <section class="meal-section" aria-label="Meals"><div class="section-toolbar"><div class="meal-heading"><h2>On your plate</h2><span class="count">${number(data.meal_count)} meals</span></div><button class="text-button" data-action="navigate" data-page="diary">View food diary ${icon("arrow", 13)}</button></div><div class="meal-grid">${
      data.meals.length
        ? data.meals
            .slice(0, 6)
            .map((meal) => mealCard(meal))
            .join("")
        : emptyState(
            "A fresh start for your plate",
            "Add your first meal, or connect Telegram and send a photo or meal description. Your daily balance will grow from here.",
          )
    }</div></section><div class="footer-note">${icon("heart", 11)}Progress is personal. Every small step counts.</div>`;
}
function chartColumn(day, top, label, owner, selected) {
  const current = day.date === selected;
  const body = `<div class="chart-tooltip">${esc(readableDate(day.date))} · ${fmt(day.calories)} kcal</div><div class="chart-bar" style="height:${pct(day.calories, top)}%"></div>${label}`;
  const name = `${esc(readableDate(day.date, { month: "short", day: "numeric" }))}: ${fmt(day.calories)} calories`;
  // A community card's bars pick which day's shared meals sit below it, so they are real buttons.
  return owner
    ? `<button type="button" class="chart-column${current ? " current" : ""}" data-action="community-day" data-user="${esc(owner.id)}" data-date="${esc(day.date)}" aria-pressed="${current}" aria-label="Show ${name}">${body}</button>`
    : `<div class="chart-column${current ? " current" : ""}" tabindex="0" aria-label="${name}">${body}</div>`;
}
function weeklyChart(entries = [], goal = 2000, compact = false, owner = null) {
  const max = Math.max(
    number(goal) * 1.2,
    ...entries.map((day) => number(day.calories) * 1.1),
    100,
  );
  const top = Math.ceil(max / 500) * 500;
  const average = entries.length
    ? entries.reduce((sum, entry) => sum + number(entry.calories), 0) /
      entries.length
    : 0;
  const step = entries.length > 14 ? Math.ceil(entries.length / 6) : 1;
  return `<div class="${compact ? "shared-chart" : ""}"><div class="chart-summary"><strong>${fmt(average)}</strong><span>kcal daily average</span></div><div class="chart-legend"><span class="dash"></span>Daily goal · ${fmt(goal)} kcal</div><div class="chart${entries.length > 14 ? " chart-30" : ""}" role="group" aria-label="${owner ? "Daily calories. Choose a day to see the meals shared on it." : "Daily calorie intake chart"}"><div class="chart-grid"><div><span>${fmt(top)}</span></div><div><span>${fmt(top / 2)}</span></div><div><span>0</span></div></div><div class="chart-goal" style="bottom:calc(25px + (100% - 25px) * ${pct(goal, top) / 100})" aria-hidden="true"></div><div class="chart-bars">${entries.map((day, index) => chartColumn(day, top, index % step === 0 || index === entries.length - 1 ? `<span class="chart-label">${esc(readableDate(day.date, entries.length > 14 ? { month: "short", day: "numeric" } : { weekday: "short" }))}</span>` : "", owner, owner ? owner.selected : state.date)).join("")}</div></div></div>`;
}
function streakCard(data) {
  const recent = data.weekly.slice(-7);
  return `<div class="consistency-card"><div class="eyebrow">SHOWING UP FOR YOURSELF</div><div class="streak-number">${fmt(data.streak)}${icon("flame", 31)}</div><h3>${number(data.streak) === 1 ? "day of consistency" : "days of consistency"}</h3><p>${number(data.streak) > 0 ? "A little intention goes a long way. Keep making time for you." : "Your next small step starts with a meal. Let’s build a rhythm."}</p><div class="streak-days">${recent.map((day) => `<div class="streak-day"><span class="streak-check${number(day.meal_count) > 0 ? " checked" : ""}" aria-label="${esc(readableDate(day.date))}: ${number(day.meal_count) > 0 ? "meal logged" : "no meals"}">${number(day.meal_count) > 0 ? icon("check", 12) : "<span>·</span>"}</span><span>${esc(readableDate(day.date, { weekday: "narrow" }))}</span></div>`).join("")}</div></div>`;
}
function mealCard(meal) {
  const type = mealType(meal);
  const emoji = MEAL_EMOJI[type];
  const imageUrl = safeImage(meal.image_url);
  return `<article class="card meal-card"><div class="meal-image ${type}">${imageUrl ? `<img src="${esc(imageUrl)}" alt="${esc(meal.name)}" loading="lazy"/>` : `<span class="meal-illustration" aria-hidden="true">${emoji}</span>`}<span class="meal-type">${icon(type === "dinner" ? "moon" : "sun", 9)}${type}</span><button class="meal-edit" data-action="edit-meal" data-id="${esc(meal.id)}" aria-label="Edit ${esc(meal.name)}">${icon("edit", 12)}</button></div><div class="meal-card-content"><div class="meal-title-line"><h3 title="${esc(meal.name)}"><button data-action="edit-meal" data-id="${esc(meal.id)}">${esc(meal.name)}</button></h3></div><div class="meal-time">${icon("clock", 10)}${esc(mealTime(meal.logged_at))}${meal.source === "telegram" ? ` · ${icon("plane", 10)} Telegram` : ""}</div><div class="meal-calories">${icon("flame", 13)}<strong>${fmt(meal.calories)}</strong>kcal${meal.estimated ? '<span class="estimate-tag">Estimated</span>' : ""}</div><div class="meal-macros"><span><i class="macro-dot" style="background:#9aaf89"></i><b>${fmt(meal.protein)}g</b> protein</span><span><i class="macro-dot" style="background:#e6bf73"></i><b>${fmt(meal.carbs)}g</b> carbs</span><span><i class="macro-dot" style="background:#e9a584"></i><b>${fmt(meal.fat)}g</b> fat</span></div></div></article>`;
}
function renderDiary() {
  const data = state.dashboard;
  return `${heading("Your food diary", "A little attention to what fuels your day.")}<div class="section-toolbar"><h2>${state.date === today() ? "Today’s meals" : readableDate(state.date, { weekday: "long", month: "long", day: "numeric" })}</h2>${dateControls()}</div><div class="diary-summary"><div><strong>${fmt(data.totals.calories)}</strong><span>kcal</span></div><div><strong>${fmt(data.totals.protein)}g</strong><span>protein</span></div><div><strong>${fmt(data.totals.carbs)}g</strong><span>carbs</span></div><div><strong>${fmt(data.totals.fat)}g</strong><span>fat</span></div><div class="diary-meal-count">${number(data.meal_count)} meals logged</div></div><div class="meal-grid">${data.meals.length ? data.meals.map((meal) => mealCard(meal)).join("") : emptyState("Nothing on the menu yet", "Log a meal for this day. You can enter the details yourself or let a photo get you started.")}</div>`;
}
function sharedDayLabel(date, today) {
  if (!date) return "Earlier";
  if (date === today) return "Today";
  if (date === shiftDate(today, -1)) return "Yesterday";
  return readableDate(date, { weekday: "short", month: "short", day: "numeric" });
}
function communitySelectedDay(user) {
  return state.communityDay[String(user.id)] || user.date;
}
// The profile payload always carries the member's current day. Any other day in the window is
// fetched when its bar is picked and kept here, so going back to it costs nothing.
function communityDayMeals(user, date) {
  if (date === user.date) return Array.isArray(user.meals) ? user.meals : [];
  return state.communityMeals[`${user.id}|${date}`];
}
function sharedMealRow(meal, zone) {
  const type = mealType(meal);
  const image = safeImage(meal.image_url);
  const time = mealTime(meal.logged_at, zone);
  return `<div class="community-meal">${image ? `<img class="community-meal-photo" src="${esc(image)}" alt="${esc(meal.name)}" loading="lazy"/>` : `<span class="community-meal-photo placeholder" aria-hidden="true">${MEAL_EMOJI[type]}</span>`}<div class="community-meal-body"><span class="community-meal-name" title="${esc(meal.name)}">${esc(meal.name)}</span><span class="community-meal-meta">${esc(type)}${time ? ` · ${esc(time)}` : ""}</span></div><div class="community-meal-figures"><span class="community-meal-kcal">${meal.estimated ? "≈ " : ""}${fmt(meal.calories)} kcal</span><span class="community-meal-macros">${fmt(meal.protein)}P · ${fmt(meal.carbs)}C · ${fmt(meal.fat)}F</span></div></div>`;
}
function sharedMealFeed(user) {
  if (!user.share_meals)
    return '<p class="community-meals-note">This member shares progress only.</p>';
  const date = communitySelectedDay(user);
  const meals = communityDayMeals(user, date);
  let body;
  if (meals === "error")
    body =
      '<p class="community-meals-note">We couldn’t load that day. Pick it again to retry.</p>';
  else if (!Array.isArray(meals))
    body =
      '<p class="community-meals-note"><span class="spinner"></span>Loading…</p>';
  else if (!meals.length)
    body = '<p class="community-meals-note">No meals shared on this day.</p>';
  else body = meals.map((meal) => sharedMealRow(meal, user.timezone)).join("");
  return `<div class="community-meals"><h4>Shared meals<span class="community-day-label">${esc(sharedDayLabel(date, user.date))}</span></h4>${body}</div>`;
}
function renderCommunity() {
  return `${heading("Better, together.", "A shared space for small wins and everyday inspiration.", false)}<section class="community-banner"><div><h3>${state.user.share_progress ? "You’re part of the picture." : "Your journey is yours to share."}</h3><p>${state.user.share_progress ? "Your daily totals and weekly progress are visible here. You decide whether to share individual meals, too." : "Get inspired by people who have chosen to share their progress. Your own activity stays private until you opt in."}</p></div><button class="btn btn-secondary btn-small" data-action="navigate" data-page="settings">${icon("settings", 13)}Sharing settings</button></section><div class="section-toolbar"><h2>Community progress</h2><span class="small muted">${state.community.length} sharing</span></div><div class="community-grid">${state.community.length ? state.community.map((user) => `<article class="card community-user"><div class="community-user-header"><div class="avatar">${esc(user.initials || initials(user.display_name))}</div><div><h3>${esc(user.display_name)}${String(user.id) === String(state.user.id) ? ' <span class="muted small">(you)</span>' : ""}</h3><p>Today’s balance</p></div><span class="chip">${icon("flame", 12)}${fmt(user.streak)} day${number(user.streak) === 1 ? "" : "s"}</span></div><div class="community-total">${fmt(user.totals.calories)} <span>/ ${fmt(user.daily_calorie_goal)} kcal</span></div><div class="progress-track community-progress"><div class="progress-fill" style="width:${pct(user.totals.calories, user.daily_calorie_goal)}%;background:#a5b796"></div></div>${weeklyChart(user.weekly, user.daily_calorie_goal, true, { id: String(user.id), selected: communitySelectedDay(user) })}${sharedMealFeed(user)}</article>`).join("") : emptyState("Room for the first small win", "No one has shared progress yet. You can be the first by turning on progress sharing in settings.", "navigate-settings", "Choose what to share", "community")}</div>`;
}
function photoPrivacyNotice() {
  return esc(
    state.config.photo_privacy_notice ||
      "Photos and portion notes are sent to the configured AI provider for analysis.",
  );
}

function renderPlanCards(data) {
  const plan = data.plan, fasting = data.fasting;
  const detail = plan.mode === "custom" ? "Your personal daily target" : `${fmt(plan.maintenance_calories)} kcal maintenance${plan.mode === "bulk" ? ` + ${fmt(plan.calorie_adjustment)} kcal surplus` : plan.mode === "deficit" ? ` − ${fmt(plan.calorie_adjustment)} kcal deficit` : ""}`;
  const minutes = Math.ceil(fasting.seconds_until_transition / 60);
  const eating = fasting.phase === "eating";
  return `<section class="plan-grid" aria-label="Your current plan"><div class="card plan-card"><div class="card-head"><h3>${esc(plan.label)}</h3><button class="text-button" data-action="navigate" data-page="settings">Edit plan</button></div><strong class="plan-value">${fmt(plan.target)} <span>kcal / day</span></strong><p>${esc(detail)}</p></div><div class="card plan-card fasting-card"><div class="card-head"><h3>Intermittent fasting</h3><span class="chip">Right now</span></div>${fasting.enabled ? `<strong class="plan-value">${eating ? "Eating window open" : "Fasting window"}</strong><p>${eating ? "Closes" : "Opens"} in ${Math.floor(minutes / 60)}h ${minutes % 60}m · ${fasting.fasting_hours}h fast / ${fasting.eating_hours}h eat</p><p>${esc(fasting.window_start)}–${esc(fasting.window_end)} · ${esc(fasting.timezone)}</p><span class="small muted">${fasting.reminders_enabled && fasting.telegram_connected && state.config.telegram_reminders_available && !state.user.is_demo ? "Telegram reminders enabled" : "Telegram reminders inactive · check Settings"}</span>` : `<p>Choose a daily eating window and receive reminders in Telegram.</p><button class="text-button" data-action="navigate" data-page="settings">Set up your schedule ${icon("arrow", 12)}</button>`}</div></section>`;
}

function renderGoalSettings(user) {
  const custom = user.goal_mode === "custom", adjusted = ["bulk", "deficit"].includes(user.goal_mode);
  return `<div class="field"><label for="goal-mode">Calorie plan</label><select id="goal-mode" name="goal_mode">${[["custom", "Custom target"], ["maintain", "Maintenance"], ["bulk", "Bulking (surplus)"], ["deficit", "Calorie deficit"]].map(([mode, label]) => `<option value="${mode}"${user.goal_mode === mode ? " selected" : ""}>${label}</option>`).join("")}</select></div><div id="maintenance-fields"${custom ? " hidden" : ""}><div class="field"><label for="maintenance-calories">Maintenance calories (kcal)</label><input id="maintenance-calories" name="maintenance_calories" type="number" min="1" max="20000" step="1" value="${number(user.maintenance_calories)}"${custom ? " disabled" : " required"}/><p class="field-hint">Enter your own maintenance estimate. Your target adds a surplus or subtracts a deficit.</p></div><div id="adjustment-field" class="field"${adjusted ? "" : " hidden"}><label for="calorie-adjustment">Daily surplus / deficit (kcal)</label><input id="calorie-adjustment" name="calorie_adjustment" type="number" min="0" max="2000" step="1" value="${number(user.calorie_adjustment)}"${adjusted ? " required" : " disabled"}/></div></div>`;
}

function settingsToggle(name, title, description, checked) {
  return `<div class="toggle-row"><div><strong id="${name}-label">${esc(title)}</strong><p>${esc(description)}</p></div><label class="switch"><input type="checkbox" name="${name}" aria-labelledby="${name}-label"${checked ? " checked" : ""}/><span class="switch-track"></span></label></div>`;
}

function renderFastingSettings(user) {
  const active = user.fasting_enabled && user.fasting_reminders;
  const reminderNote = user.is_demo ? "Reminders are not sent from demo accounts." : !state.config.telegram_reminders_available ? "Reminders need Telegram polling enabled on the server. Keep the server running to receive them." : !user.telegram_connected ? "Connect your Telegram account to receive reminders. Keep the server running." : "Reminders go to your connected private Telegram chat while the server is running.";
  return `<section class="card settings-card"><h2>Intermittent fasting</h2><p>Choose a daily eating window in your profile’s time zone. A window can cross midnight.</p>${settingsToggle("fasting_enabled", "Enable fasting schedule", "Show your current fasting or eating window on the dashboard.", user.fasting_enabled)}<fieldset id="fasting-schedule" class="plain-fieldset"${user.fasting_enabled ? "" : " disabled"}><legend class="sr-only">Daily eating window</legend><div class="field-row"><div class="field"><label for="eating-window-start">Eating window opens</label><input id="eating-window-start" type="time" name="eating_window_start" value="${esc(user.eating_window_start)}" required/></div><div class="field"><label for="eating-window-end">Eating window closes</label><input id="eating-window-end" type="time" name="eating_window_end" value="${esc(user.eating_window_end)}" required/></div></div><p id="window-duration" class="field-hint" aria-live="polite">${windowDuration(user.eating_window_start, user.eating_window_end)}</p>${settingsToggle("fasting_reminders", "Telegram reminders", "Send notifications for your daily fasting schedule.", user.fasting_reminders)}</fieldset><fieldset id="fasting-notifications" class="plain-fieldset"${active ? "" : " disabled"}><legend class="sr-only">Reminder preferences</legend>${settingsToggle("remind_window_open", "Eating window opened", "Notify me when my scheduled fast ends.", user.remind_window_open)}${settingsToggle("remind_window_close", "Eating window closed", "Notify me when my scheduled fast starts.", user.remind_window_close)}<div class="field"><label for="fasting-reminder-minutes">Fasting heads-up (minutes before closing)</label><input id="fasting-reminder-minutes" name="fasting_reminder_minutes" type="number" min="0" max="120" step="1" value="${number(user.fasting_reminder_minutes)}" required/><p class="field-hint">Set 0 to turn off the heads-up. Must be shorter than the eating window.</p></div></fieldset><div class="inline-note">${esc(reminderNote)} Save changes to apply your schedule.</div></section>`;
}

function windowDuration(start, end) {
  const toMinutes = (value) => { const [h, m] = value.split(":").map(Number); return h * 60 + m; };
  const minutes = (toMinutes(end) - toMinutes(start) + 1440) % 1440;
  return minutes ? `${Number(((1440 - minutes) / 60).toFixed(2))}h fasting · ${Number((minutes / 60).toFixed(2))}h eating each day` : "Choose different opening and closing times.";
}

function updatePlanForm() {
  const form = $("#settings-form");
  if (!form) return;
  const mode = form.elements.goal_mode.value, custom = mode === "custom", adjusted = ["bulk", "deficit"].includes(mode);
  $("#maintenance-fields").hidden = custom;
  $("#adjustment-field").hidden = !adjusted;
  form.elements.maintenance_calories.disabled = custom;
  form.elements.maintenance_calories.required = !custom;
  form.elements.calorie_adjustment.disabled = !adjusted;
  form.elements.calorie_adjustment.required = adjusted;
  form.elements.daily_calorie_goal.readOnly = !custom;
  if (!custom) form.elements.daily_calorie_goal.value = Number(form.elements.maintenance_calories.value) + (mode === "bulk" ? 1 : mode === "deficit" ? -1 : 0) * Number(form.elements.calorie_adjustment.value);
  $("#fasting-schedule").disabled = !form.elements.fasting_enabled.checked;
  $("#fasting-notifications").disabled = !form.elements.fasting_enabled.checked || !form.elements.fasting_reminders.checked;
  $("#window-duration").textContent = windowDuration(form.elements.eating_window_start.value, form.elements.eating_window_end.value);
}

function renderSettings() {
  const user = state.user;
  return `${heading("Make yourself at home.", "Your goals, your privacy, your way of tracking.", false)}<form id="settings-form" class="settings-grid"><div><section class="card settings-card"><h2>Your profile</h2><p>A few details to make this space yours.</p><div class="field"><label for="display-name">Display name</label><input id="display-name" name="display_name" value="${esc(user.display_name)}" minlength="1" maxlength="60" required autocomplete="name"/></div><div class="field"><label for="profile-email">Email address</label><input id="profile-email" value="${esc(user.email)}" disabled/><p class="field-hint">Used to sign in. Your email is never shown in the community.</p></div><div class="field"><label for="timezone">Timezone</label><input id="timezone" name="timezone" value="${esc(user.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone)}" placeholder="Asia/Makassar" required list="timezone-options"/><datalist id="timezone-options">${["UTC", "Asia/Makassar", "Asia/Jakarta", "Asia/Singapore", "Asia/Tokyo", "Asia/Kolkata", "Australia/Sydney", "Europe/London", "Europe/Paris", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"].map((zone) => `<option value="${zone}"></option>`).join("")}</datalist><p class="field-hint">Daily totals follow the calendar day in this timezone.</p></div></section>
    <section class="card settings-card"><h2>Your daily goals</h2><p>Set targets that fit you. These are tracking preferences, not dietary recommendations.</p>${renderGoalSettings(user)}<div class="field"><label for="calorie-goal">Daily calories (kcal)</label><input id="calorie-goal" type="number" name="daily_calorie_goal" min="1" max="20000" step="1" value="${number(user.daily_calorie_goal)}"${user.goal_mode === "custom" ? "" : " readonly"} required/></div><div class="field-row three"><div class="field"><label for="protein-goal">Protein (g)</label><input id="protein-goal" type="number" name="protein_goal" min="1" max="2000" step="1" value="${number(user.protein_goal)}" required/></div><div class="field"><label for="carbs-goal">Carbs (g)</label><input id="carbs-goal" type="number" name="carbs_goal" min="1" max="4000" step="1" value="${number(user.carbs_goal)}" required/></div><div class="field"><label for="fat-goal">Fat (g)</label><input id="fat-goal" type="number" name="fat_goal" min="1" max="2000" step="1" value="${number(user.fat_goal)}" required/></div></div></section>
    ${renderFastingSettings(user)}
    <section class="card settings-card"><h2>Your sharing preferences</h2><p>Private by default. Share only what feels right for you.</p><div class="toggle-row"><div><strong id="share-progress-label">Share my progress</strong><p>Show your name, daily totals, streak, and weekly activity to other signed-in users.</p></div><label class="switch"><input type="checkbox" name="share_progress" aria-labelledby="share-progress-label"${user.share_progress ? " checked" : ""}/><span class="switch-track"></span></label></div><div class="toggle-row"><div><strong id="share-meals-label">Share individual meals</strong><p>Also show your meal names, nutrition, and photos from the last 7 days to other signed-in users. Your notes stay private. Requires progress sharing.</p></div><label class="switch"><input type="checkbox" name="share_meals" aria-labelledby="share-meals-label"${user.share_progress && user.share_meals ? " checked" : ""}${user.share_progress ? "" : " disabled"}/><span class="switch-track"></span></label></div></section><div class="form-error" id="settings-error" role="alert"></div><div class="save-bar"><button class="btn btn-primary" type="submit">${icon("check", 15)}Save changes</button></div></div>
    <div><section class="card settings-card"><div class="telegram-connect-art">${icon("plane", 31)}</div><h2>Your meals, one message away.</h2><p>Send a photo or describe your meal and portions in Telegram. ${photoPrivacyNotice()}</p><div class="status-pill${user.telegram_connected ? "" : " offline"}">${icon(user.telegram_connected ? "check" : "info", 12)}${user.telegram_connected ? "Telegram connected" : "Telegram not connected"}</div>${user.telegram_connected ? `<p class="small muted" style="line-height:1.8;margin-bottom:16px">Send “2 eggs and a slice of toast” for an estimate, or /log Chicken rice | 650 | 40 | 75 | 20 for exact calories, protein, carbs, and fat. Use /fasting and /goal to check your plan.</p><button type="button" class="btn btn-secondary btn-small" data-action="disconnect-telegram">Disconnect Telegram</button>` : `<ol class="telegram-steps"><li>Create a private link to your account.</li><li>Open the bot in Telegram and tap Start.</li><li>Send a photo or meal description. Review it here.</li></ol>${state.config.telegram_configured ? '<button type="button" class="btn btn-primary full-width" data-action="connect-telegram">Connect Telegram ' + icon("arrow", 15) + "</button>" : '<div class="inline-note">Telegram is not configured on this server yet. Add the bot token and username to the server environment to enable connections.</div>'}`}<div id="telegram-link-result"></div></section>
    <section class="card settings-card"><h2>AI meal estimates</h2><p>${(state.config.ai_provider_labels || []).length > 1 ? "Failover order: " + esc(state.config.ai_provider_labels.join(" → ")) : "Provider: " + esc(state.config.ai_provider_label || "Not configured")}</p><div class="status-pill${state.config.ai_configured ? "" : " offline"}">${icon(state.config.ai_configured ? "sparkle" : "info", 12)}${state.config.ai_configured ? "Photo & text estimates available" : "AI estimation not configured"}</div><p class="small muted" style="line-height:1.8">${state.config.ai_configured ? "Photo and text estimates can miss ingredients and portion sizes. You can edit every meal’s calories and macros after it is logged." : "The server needs an AI API key to estimate nutrition from photos or text. You can log meals manually while it is being set up."}</p></section>
    <section class="card settings-card"><h2>Your data</h2><p>Take your food diary with you.</p><a class="btn btn-secondary btn-small" href="/api/export" download>${icon("download", 14)}Export meals as CSV</a><div class="settings-meta"><p>Signed in as ${esc(user.email)}</p><button type="button" class="btn btn-quiet btn-small" data-action="logout">${icon("logout", 13)}Sign out</button></div></section></div></form>`;
}
function renderAuth(error = "") {
  const register = state.authTab === "register";
  $("#app").innerHTML =
    `<main class="auth-page" id="main-content"><section class="auth-story"><a href="#" class="brand" aria-label="NutriLens">${brand()}</a><div><h1>Small steps.<br>Good food.<br>A little more you.</h1><p>Your daily balance, made simple. Capture a meal, understand your nutrition, and find a rhythm that feels right.</p></div><div class="auth-art">${bowlArt()}</div><div class="story-footer">${icon("leaf", 13)}A more mindful way to nourish your day.</div></section><section class="auth-form-panel"><div class="auth-form-wrap"><div class="auth-mobile-brand"><a href="#" class="brand">${brand()}</a></div><div class="eyebrow">YOUR PERSONAL SPACE</div><h2>${register ? "A fresh start awaits." : "Welcome to your balance."}</h2><p class="auth-intro">${register ? "Make room for a little more intention. Your nutrition journey starts right here." : "Log a meal, check in with yourself, and keep your small wins growing."}</p><div class="auth-tabs"><button data-action="auth-tab" data-tab="login" class="${register ? "" : "active"}" aria-pressed="${!register}">Sign in</button><button data-action="auth-tab" data-tab="register" class="${register ? "active" : ""}" aria-pressed="${register}">Create account</button></div><form id="auth-form"><div class="form-error" id="auth-error" role="alert">${esc(error)}</div>${register ? '<div class="field"><label for="auth-name">Your name</label><input id="auth-name" name="display_name" placeholder="What should we call you?" required maxlength="60" autocomplete="name"/></div>' : ""}<div class="field"><label for="auth-email">Email address</label><input id="auth-email" name="email" type="email" placeholder="you@example.com" required autocomplete="email" maxlength="254"/></div><div class="field"><label for="auth-password">Password</label><input id="auth-password" name="password" type="password" placeholder="${register ? "At least 10 characters" : "Enter your password"}" minlength="${register ? "10" : "1"}" maxlength="128" required autocomplete="${register ? "new-password" : "current-password"}"/></div><button class="btn btn-primary auth-submit full-width" type="submit">${register ? "Create your account" : "Sign in"}${icon("arrow", 15)}</button></form>${state.config.demo_enabled ? '<div class="auth-divider">A little curious?</div><button class="btn btn-secondary full-width" data-action="demo">Explore a demo workspace ' + icon("arrow", 14) + '</button><p class="auth-note">No signup needed. Explore with sample meals<br>in your own separate demo workspace.</p>' : '<p class="auth-note">Your meals stay private until you choose to share.</p>'}</div></section></main>`;
}

function openModal(html, options = {}) {
  if (!$("#modal-root").firstElementChild)
    modalReturnFocus = document.activeElement;
  $("#modal-root").innerHTML =
    `<div class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">${html}</section></div>`;
  document.body.style.overflow = "hidden";
  requestAnimationFrame(() => {
    const first =
      $("[autofocus]", $("#modal-root")) ||
      $('input:not([type="hidden"]),button', $("#modal-root"));
    first?.focus();
  });
}
function closeModal() {
  if (state.modal?.busy) return;
  $("#modal-root").innerHTML = "";
  document.body.style.overflow = "";
  state.modal = null;
  if (photoObjectUrl) {
    URL.revokeObjectURL(photoObjectUrl);
    photoObjectUrl = null;
  }
  if (modalReturnFocus?.isConnected) modalReturnFocus.focus();
}
function findMeal(id) {
  return state.dashboard?.meals.find((meal) => String(meal.id) === String(id));
}
function openMeal(meal = null, tab = "manual") {
  state.modal = { type: "meal", meal, tab, busy: false };
  const edit = Boolean(meal);
  const defaultLogged =
    state.date === today() ? dateTimeInput() : `${state.date}T12:00`;
  const estimated = meal?.estimated;
  const photoAvailable = state.config.ai_configured && !state.user.is_demo;
  openModal(
    `<div class="modal-header"><h2 id="modal-title">${edit ? "A closer look at your meal." : "What’s on your plate?"}</h2><button class="icon-button" data-action="close-modal" aria-label="Close dialog">${icon("close", 20)}</button></div><p class="modal-subtitle">${edit ? "Fine-tune the details to make your diary more accurate." : "Every meal is a small moment to check in with yourself."}</p>${!edit ? `<div class="modal-tabs"><button data-action="meal-tab" data-tab="manual" class="${tab === "manual" ? "active" : ""}" aria-pressed="${tab === "manual"}">${icon("edit", 15)}Add details</button><button data-action="meal-tab" data-tab="photo" class="${tab === "photo" ? "active" : ""}" aria-pressed="${tab === "photo"}">${icon("camera", 16)}From a photo</button></div>` : ""}${estimated ? `<div class="estimate-note">${icon("sparkle", 15)}<span>${meal.image_url ? "Photo" : "Text"} estimate · ${esc(meal.confidence || "low")} confidence. Check portion sizes, ingredients, and nutrition before saving your adjustments.</span></div>` : ""}<form id="meal-form" enctype="multipart/form-data"><div id="meal-error" class="form-error" role="alert"></div>${tab === "photo" ? `<div class="upload-zone"><div id="photo-preview"></div>${icon("camera", 30)}<label for="meal-photo">Start with a meal photo</label><p>JPG, PNG, or WebP · up to 10 MB</p><input id="meal-photo" name="file" type="file" accept="image/jpeg,image/png,image/webp" required/></div>${state.user.is_demo ? '<div class="inline-note">Create your own account to analyze meal photos. You can explore manual meal logging here.</div>' : !photoAvailable ? '<div class="inline-note">Photo estimation isn’t configured yet. Add an AI API key to the server environment, or switch to “Add details” to log your meal manually.</div>' : '<div class="field-hint" style="margin:-7px 0 18px">You’ll be able to review and adjust the estimate after upload. ' + photoPrivacyNotice() + "</div>"}` : `<div class="field"><label for="meal-name">Meal name</label><input id="meal-name" name="name" placeholder="e.g. Avocado toast with eggs" value="${esc(meal?.name || "")}" required maxlength="120" autofocus/></div><div class="field"><label for="meal-calories">Calories (kcal)</label><input id="meal-calories" name="calories" type="number" min="0" max="20000" step="0.1" placeholder="420" value="${edit ? number(meal.calories) : ""}" required/></div><div class="field-row three"><div class="field"><label for="meal-protein">Protein (g)</label><input id="meal-protein" name="protein" type="number" min="0" max="2000" step="0.1" value="${number(meal?.protein)}" required/></div><div class="field"><label for="meal-carbs">Carbs (g)</label><input id="meal-carbs" name="carbs" type="number" min="0" max="4000" step="0.1" value="${number(meal?.carbs)}" required/></div><div class="field"><label for="meal-fat">Fat (g)</label><input id="meal-fat" name="fat" type="number" min="0" max="2000" step="0.1" value="${number(meal?.fat)}" required/></div></div>`}<div class="field-row"><div class="field"><label for="meal-type">Meal type</label><select id="meal-type" name="meal_type">${["breakfast", "lunch", "dinner", "snack"].map((type) => `<option value="${type}"${(meal?.meal_type || "lunch") === type ? " selected" : ""}>${type[0].toUpperCase() + type.slice(1)}</option>`).join("")}</select></div><div class="field"><label for="meal-date">Date & time</label><input id="meal-date" name="logged_at" type="datetime-local" min="1970-01-01T00:00" max="2100-12-31T23:59" value="${esc(meal ? dateTimeInput(meal.logged_at) : defaultLogged)}" required/><p class="field-hint">${esc(state.user.timezone)} time</p></div></div><div class="field"><label for="meal-notes">${tab === "photo" ? "Portions & ingredients" : "Notes"} <span class="muted">(optional)</span></label><textarea id="meal-notes" name="notes" maxlength="2000" placeholder="${tab === "photo" ? "e.g. One cup of rice, chicken cooked in olive oil" : "Anything you’d like to remember?"}">${esc(meal?.notes || "")}</textarea></div><div class="modal-actions">${edit ? `<button type="button" class="btn btn-danger delete-button" data-action="delete-meal" data-id="${esc(meal.id)}">${icon("trash", 14)}Delete</button>` : ""}<button type="button" class="btn btn-secondary" data-action="close-modal">Cancel</button><button class="btn btn-primary" type="submit"${tab === "photo" && !photoAvailable ? " disabled" : ""}>${icon(tab === "photo" ? "sparkle" : "check", 15)}${tab === "photo" ? "Estimate meal" : edit ? "Save changes" : "Log meal"}</button></div></form>`,
  );
}
async function saveMeal(form) {
  if (!state.modal || state.modal.busy) return;
  const modal = state.modal;
  const values = new FormData(form);
  const enteredTime = String(values.get("logged_at"));
  // Preserve the original UTC instant for unchanged timestamps (including a
  // daylight-saving fold). New local values are interpreted in the account zone.
  const loggedAt =
    modal.meal && enteredTime === dateTimeInput(modal.meal.logged_at)
      ? modal.meal.logged_at
      : enteredTime;
  $("#meal-error").textContent = "";
  const submit = $('[type="submit"]', form),
    original = submit.innerHTML;
  let body;
  try {
    if (modal.tab === "photo") {
      const file = values.get("file");
      if (!file?.size) throw new Error("Choose a meal photo to get started.");
      if (file.size > 10 * 1024 * 1024)
        throw new Error("Please choose a photo smaller than 10 MB.");
      body = values;
      body.set("logged_at", loggedAt);
    } else {
      body = {
        name: String(values.get("name")).trim(),
        calories: Number(values.get("calories")),
        protein: Number(values.get("protein")),
        carbs: Number(values.get("carbs")),
        fat: Number(values.get("fat")),
        meal_type: values.get("meal_type"),
        logged_at: loggedAt,
        notes: String(values.get("notes")).trim(),
      };
    }
    modal.busy = true;
    submit.disabled = true;
    submit.innerHTML = `<span class="spinner"></span>${modal.tab === "photo" ? "Estimating…" : "Saving…"}`;
    form.classList.add("form-busy");
    const meal = await api(
      modal.tab === "photo"
        ? "/api/meals/photo"
        : modal.meal
          ? `/api/meals/${encodeURIComponent(modal.meal.id)}`
          : "/api/meals",
      { method: modal.meal ? "PATCH" : "POST", body },
    );
    modal.busy = false;
    closeModal();
    await loadPage();
    if (modal.tab === "photo") {
      toast("Estimate ready. Review your meal details.");
      openMeal(meal.meal || meal);
    } else
      toast(
        modal.meal
          ? "Your meal has been updated."
          : "A little progress, logged.",
      );
  } catch (error) {
    modal.busy = false;
    submit.disabled = false;
    submit.innerHTML = original;
    form.classList.remove("form-busy");
    if ($("#meal-error")) $("#meal-error").textContent = error.message;
  }
}
function confirmDelete(id) {
  const meal = findMeal(id) || state.modal?.meal;
  state.modal = { type: "delete", meal, busy: false };
  openModal(
    `<div class="modal-header"><h2 id="modal-title">Remove this meal?</h2><button class="icon-button" data-action="close-modal" aria-label="Close dialog">${icon("close", 20)}</button></div><p class="confirm-copy">“${esc(meal?.name || "This meal")}” will be removed from your diary, and your daily totals will be updated. This cannot be undone.</p><div class="form-error" id="delete-error" role="alert"></div><div class="modal-actions"><button class="btn btn-secondary" data-action="cancel-delete">Keep meal</button><button class="btn btn-danger" data-action="confirm-delete" data-id="${esc(id)}">${icon("trash", 14)}Remove meal</button></div>`,
  );
}

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!["auth-form", "meal-form", "settings-form"].includes(form.id)) return;
  event.preventDefault();
  if (form.id === "meal-form") {
    await saveMeal(form);
    return;
  }
  const button = $('[type="submit"]', form),
    original = button.innerHTML;
  const errorTarget = $(
    form.id === "auth-form" ? "#auth-error" : "#settings-error",
  );
  errorTarget.textContent = "";
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span>Saving…';
  const values = new FormData(form);
  try {
    if (form.id === "auth-form") {
      const body = {
        email: String(values.get("email")).trim(),
        password: values.get("password"),
      };
      if (state.authTab === "register") {
        body.display_name = String(values.get("display_name")).trim();
        body.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      }
      state.user = normalizeUser(
        await api(
          `/api/auth/${state.authTab === "register" ? "register" : "login"}`,
          { method: "POST", body },
        ),
      );
      state.demo = false;
      state.date = today();
      await navigate("overview");
    } else {
      const body = {
        display_name: String(values.get("display_name")).trim(),
        timezone: String(values.get("timezone")).trim(),
        daily_calorie_goal: Number(values.get("daily_calorie_goal")),
        protein_goal: Number(values.get("protein_goal")),
        carbs_goal: Number(values.get("carbs_goal")),
        fat_goal: Number(values.get("fat_goal")),
        share_progress: values.has("share_progress"),
        share_meals: values.has("share_progress") && values.has("share_meals"),
        goal_mode: form.elements.goal_mode.value,
        maintenance_calories: Number(form.elements.maintenance_calories.value),
        calorie_adjustment: Number(form.elements.calorie_adjustment.value),
        fasting_enabled: form.elements.fasting_enabled.checked,
        eating_window_start: form.elements.eating_window_start.value,
        eating_window_end: form.elements.eating_window_end.value,
        fasting_reminders: form.elements.fasting_reminders.checked,
        remind_window_open: form.elements.remind_window_open.checked,
        remind_window_close: form.elements.remind_window_close.checked,
        fasting_reminder_minutes: Number(form.elements.fasting_reminder_minutes.value),
      };
      state.user = normalizeUser(
        await api("/api/me", { method: "PATCH", body }),
      );
      await navigate("settings");
      toast("Your preferences have been saved.");
    }
  } catch (error) {
    errorTarget.textContent = error.message;
    button.disabled = false;
    button.innerHTML = original;
  }
});

document.addEventListener("click", async (event) => {
  if (event.target.classList.contains("modal-backdrop")) {
    closeModal();
    return;
  }
  const button = event.target.closest("[data-action]");
  if (!button || button.disabled) return;
  const action = button.dataset.action;
  if (state.modal?.busy) return;
  try {
    if (action === "navigate") {
      await navigate(button.dataset.page, { focus: true });
    } else if (action === "navigate-settings") {
      await navigate("settings", { focus: true });
    } else if (action === "retry") {
      await loadPage();
    } else if (action === "auth-tab") {
      state.authTab = button.dataset.tab;
      renderAuth();
    } else if (action === "demo") {
      button.disabled = true;
      button.innerHTML = '<span class="spinner"></span>Preparing your space…';
      try {
        state.user = normalizeUser(
          await api("/api/auth/demo", { method: "POST" }),
        );
        state.demo = true;
        state.date = today();
        await navigate("overview");
      } catch (error) {
        renderAuth(error.message);
      }
    } else if (action === "logout") {
      await api("/api/auth/logout", { method: "POST" });
      state.user = null;
      state.demo = false;
      state.dashboard = null;
      clearCommunityCache();
      state.requestId++;
      closeModal();
      history.replaceState(null, "", location.pathname);
      renderAuth();
    } else if (action === "add-meal") {
      openMeal();
    } else if (action === "edit-meal") {
      const meal = findMeal(button.dataset.id);
      if (meal) openMeal(meal);
    } else if (action === "close-modal") {
      closeModal();
    } else if (action === "meal-tab") {
      openMeal(null, button.dataset.tab);
    } else if (action === "delete-meal") {
      confirmDelete(button.dataset.id);
    } else if (action === "cancel-delete") {
      openMeal(state.modal.meal);
    } else if (action === "confirm-delete") {
      button.disabled = true;
      state.modal.busy = true;
      try {
        await api(`/api/meals/${encodeURIComponent(button.dataset.id)}`, {
          method: "DELETE",
        });
        state.modal.busy = false;
        closeModal();
        await loadPage();
        toast("Meal removed from your diary.");
      } catch (error) {
        state.modal.busy = false;
        button.disabled = false;
        $("#delete-error").textContent = error.message;
      }
    } else if (["previous-date", "next-date", "today"].includes(action)) {
      state.date =
        action === "today"
          ? today()
          : shiftDate(state.date, action === "previous-date" ? -1 : 1);
      await loadPage();
    } else if (action === "community-day") {
      const owner = button.dataset.user;
      const date = button.dataset.date;
      const profile = state.community.find((entry) => String(entry.id) === owner);
      if (!profile) return;
      state.communityDay[owner] = date;
      const key = `${owner}|${date}`;
      if (date !== profile.date && !Array.isArray(state.communityMeals[key])) {
        state.communityMeals[key] = "loading";
        renderCommunityPage(owner, date);
        try {
          const data = await api(
            `/api/community/${encodeURIComponent(owner)}/meals?date=${encodeURIComponent(date)}`,
          );
          state.communityMeals[key] = data.meals || [];
        } catch {
          state.communityMeals[key] = "error";
        }
      }
      renderCommunityPage(owner, date);
    } else if (action === "chart-days") {
      state.days = Number(button.dataset.days);
      await loadPage();
    } else if (action === "connect-telegram") {
      button.disabled = true;
      try {
        const result = await api("/api/telegram/link", { method: "POST" });
        let link = "";
        try {
          const url = new URL(result.deep_link);
          if (url.protocol === "https:" && url.hostname === "t.me")
            link = url.href;
        } catch {}
        $("#telegram-link-result").innerHTML =
          `<div class="inline-note">Your link is ready. Open Telegram and tap <strong>Start</strong> to connect this account. The link expires ${esc(new Date(result.expires_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }))}.</div>${link ? `<a class="btn btn-primary full-width" href="${esc(link)}" target="_blank" rel="noopener noreferrer">${icon("plane", 15)}Open in Telegram</a>` : `<div class="connect-code">${esc(result.code)}</div><p class="field-hint">Send /start ${esc(result.code)} to your bot.</p>`}<button type="button" class="text-button" style="margin-top:12px" data-action="refresh-telegram">I’ve connected · refresh status ${icon("arrow", 12)}</button>`;
      } finally {
        button.disabled = false;
      }
    } else if (action === "refresh-telegram") {
      state.user = normalizeUser(await api("/api/me"));
      await navigate("settings");
      toast(
        state.user.telegram_connected
          ? "Telegram connected. Send a photo or meal description."
          : "Still waiting for Telegram. Open your link and tap Start.",
      );
    } else if (action === "disconnect-telegram") {
      await api("/api/telegram/link", { method: "DELETE" });
      state.user = normalizeUser(await api("/api/me"));
      await navigate("settings");
      toast("Telegram has been disconnected.");
    }
  } catch (error) {
    toast(error.message, true);
  }
});
document.addEventListener("change", async (event) => {
  const input = event.target;
  if (input.closest("#settings-form")) updatePlanForm();
  if (input.id === "selected-date" && /^\d{4}-\d{2}-\d{2}$/.test(input.value)) {
    state.date = input.value > today() ? today() : input.value;
    await loadPage();
  } else if (input.name === "share_progress") {
    const meals = $('[name="share_meals"]');
    if (meals) {
      meals.disabled = !input.checked;
      if (!input.checked) meals.checked = false;
    }
  } else if (input.id === "meal-photo") {
    if (photoObjectUrl) URL.revokeObjectURL(photoObjectUrl);
    photoObjectUrl = null;
    const file = input.files[0];
    if (
      file &&
      ["image/jpeg", "image/png", "image/webp"].includes(file.type) &&
      file.size <= 10 * 1024 * 1024
    ) {
      photoObjectUrl = URL.createObjectURL(file);
      $("#photo-preview").innerHTML =
        `<img class="photo-preview" src="${photoObjectUrl}" alt="Your selected meal photo"/>`;
    } else {
      $("#photo-preview").innerHTML = "";
      if (file) {
        input.value = "";
        $("#meal-error").textContent =
          "Choose a JPG, PNG, or WebP photo smaller than 10 MB.";
      }
    }
  }
});
document.addEventListener("input", (event) => {
  if (["maintenance_calories", "calorie_adjustment", "eating_window_start", "eating_window_end"].includes(event.target.name)) updatePlanForm();
});
document.addEventListener("keydown", (event) => {
  const modal = $(".modal");
  if (!modal) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeModal();
  }
  if (event.key === "Tab") {
    const focusable = [
      ...modal.querySelectorAll(
        'button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]',
      ),
    ].filter((element) => element.getClientRects().length);
    const first = focusable[0],
      last = focusable[focusable.length - 1];
    if (!first) {
      event.preventDefault();
      return;
    }
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});
window.addEventListener("hashchange", () => {
  if (state.user) navigate(location.hash.slice(1) || "overview");
});
window.addEventListener("focus", async () => {
  if (
    !state.user ||
    state.page !== "settings" ||
    !$("#telegram-link-result")?.children.length
  )
    return;
  try {
    const user = normalizeUser(await api("/api/me"));
    if (user.telegram_connected !== state.user.telegram_connected) {
      state.user = user;
      await navigate("settings");
      if (user.telegram_connected)
        toast("Telegram connected. You’re ready to send a meal.");
    }
  } catch {}
});

async function init() {
  const [config, user] = await Promise.allSettled([
    api("/api/config"),
    api("/api/me"),
  ]);
  if (config.status === "fulfilled") state.config = config.value;
  if (user.status === "fulfilled") {
    state.user = normalizeUser(user.value);
    state.date = today();
    await navigate(location.hash.slice(1) || "overview");
  } else renderAuth(user.reason.status === 401 ? "" : user.reason.message);
}
init();
