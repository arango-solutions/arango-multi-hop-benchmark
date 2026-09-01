// Application shell: header, theme toggle, tab bar, and shared state.
//
// Only one tab is mounted at a time. Switching tabs disposes the current tab
// (closing any SSE stream it owns) and builds the next one fresh, mirroring
// how the previous React implementation conditionally rendered tab panels.

import { api } from "./api.js";
import { el, replace } from "./dom.js";
import { createConfigureTab } from "./tabs/configure.js";
import { createRunTab } from "./tabs/run.js";
import { createDashboardTab } from "./tabs/dashboard.js";
import { createAdhocTab } from "./tabs/adhoc.js";
import { createRagEvalTab } from "./tabs/ragEval.js";
import { createHowToTab } from "./tabs/howTo.js";

const THEME_STORAGE_KEY = "multihop-eval-theme";

const TABS = [
  { id: "configure", label: "Configure", create: createConfigureTab },
  { id: "run", label: "Run", create: createRunTab },
  { id: "dashboard", label: "Dashboard", create: createDashboardTab },
  { id: "adhoc", label: "Ad-hoc", create: createAdhocTab },
  { id: "rag_eval", label: "RAG Eval", create: createRagEvalTab },
  { id: "how_to", label: "How-To", create: createHowToTab },
];

function getInitialTheme() {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

function applyTheme(theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Ignore storage failures; the in-session theme still updates.
  }
}

function start(root) {
  const state = { connection: null, configResp: null, theme: getInitialTheme() };
  let activeTabId = TABS[0].id;
  let mounted = null;

  const ctx = {
    get connection() {
      return state.connection;
    },
    get configResp() {
      return state.configResp;
    },
    connected() {
      return Boolean(state.connection?.status?.startsWith("connected"));
    },
    hasConfig() {
      return Boolean(state.configResp?.saved);
    },
    setConnection(status) {
      state.connection = status;
    },
    async refreshConnection() {
      state.connection = await api.connectionStatus();
      return state.connection;
    },
    async refreshConfig() {
      state.configResp = await api.getConfig();
      return state.configResp;
    },
  };

  const panel = el("main", {});
  const tabButtons = new Map();

  function selectTab(id) {
    activeTabId = id;
    for (const [tabId, button] of tabButtons) {
      const active = tabId === id;
      button.className = active ? "tab active" : "tab";
      button.setAttribute("aria-selected", String(active));
    }
    mounted?.dispose?.();
    mounted = TABS.find((t) => t.id === id).create(ctx);
    replace(panel, mounted.element);
  }

  const themeButton = el("button", {
    class: "theme-toggle",
    type: "button",
    onClick: () => {
      state.theme = state.theme === "light" ? "dark" : "light";
      applyTheme(state.theme);
      syncThemeButton();
    },
  });

  function syncThemeButton() {
    const next = state.theme === "light" ? "dark" : "light";
    themeButton.textContent = state.theme === "light" ? "Dark mode" : "Light mode";
    themeButton.setAttribute("aria-label", `Switch to ${next} mode`);
    themeButton.setAttribute("aria-pressed", String(state.theme === "dark"));
  }

  const nav = el("nav", { class: "tabs", role: "tablist" });
  for (const tab of TABS) {
    const button = el(
      "button",
      { class: "tab", type: "button", role: "tab", onClick: () => selectTab(tab.id) },
      tab.label,
    );
    tabButtons.set(tab.id, button);
    nav.appendChild(button);
  }

  const app = el(
    "div",
    { class: "app" },
    el(
      "header",
      { class: "app-header" },
      el(
        "div",
        {},
        el("h1", {}, "Multi-Hop Eval"),
        el(
          "span",
          { class: "subtitle" },
          "QA dataset generation & evaluation against Arango graph data",
        ),
      ),
      themeButton,
    ),
    nav,
    panel,
  );

  applyTheme(state.theme);
  syncThemeButton();
  replace(root, app);
  selectTab(activeTabId);

  // Load shared state, then rebuild the active tab so it sees the result.
  Promise.allSettled([ctx.refreshConnection(), ctx.refreshConfig()]).then(() => {
    selectTab(activeTabId);
  });
}

start(document.getElementById("root"));
