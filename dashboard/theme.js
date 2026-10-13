/**
 * theme.js — 仪表盘主题配置
 * ============================================
 * 支持「深色 / 浅色」两套主题，运行时可切换，选择记忆在 localStorage。
 * 所有颜色都集中在这里。改颜色只改这一个文件。
 */

// —— 品牌强调色（深浅两模式共用，保证游戏配色识别度不变）——
const BRAND_COLORS = {
  color_a: "#F59E0B",           // 王者万象棋 —— 琥珀金（王者品牌色）
  color_b: "#38BDF8",           // 金铲铲之战 —— 电光蓝
  negative: "#F43F5E",          // 负面 —— 玫瑰红
  positive: "#10B981",          // 正面 —— 翠绿
  warning: "#FBBF24",           // 警示 —— 琥珀亮
  accent: "#A78BFA",            // 点缀 —— 紫罗兰
  palette_positive: ["#F59E0B", "#38BDF8", "#A78BFA", "#FBBF24", "#22D3EE", "#C084FC", "#34D399"],
  palette_negative: ["#F43F5E", "#FB7185", "#F97316", "#FBBF24", "#EF4444"],
};

// =========================================================
// 两套主题
// =========================================================
const THEME_MODES = {
  // —— 深色（默认，原「游戏数据 · 夜空金蓝」）——
  dark: {
    bg: {
      body_grad: ["#0B1120", "#1A0F2E", "#050814"],   // 深蓝黑 → 深紫黑 → 纯深空
      surface: "#131A2E",
      surface_glass: "rgba(19, 26, 46, 0.72)",
      scrollbar: "#0B1120",
      chart_axis: "#2D3B5C",
      chart_grid: "#1C2640",
      chart_text: "#7D8DB8",
      chart_text_bold: "#E0E8F5",
      chart_contrast: "#131A2E",
    },
    // 前景灰阶（对应 Tailwind 的 slate-200~800；浅色模式下整体反相）
    fg: { 200: "226 232 240", 300: "203 213 225", 400: "148 163 184", 500: "100 116 139", 600: "71 85 105", 700: "51 65 85", 800: "30 41 59" },
    // UI 角色色（theme.css 中复用）
    ui: {
      body_text: "#E0E8F5",
      card_grad_a: "rgba(19, 26, 46, 0.9)", card_grad_b: "rgba(11, 17, 32, 0.9)",
      card_soft_a: "rgba(19, 26, 46, 0.8)", card_soft_b: "rgba(11, 17, 32, 0.6)",
      finding_a: "rgba(19, 26, 46, 0.9)", finding_b: "rgba(11, 17, 32, 0.7)",
      chat_bubble: "rgba(19, 26, 46, 0.6)", chat_ref: "rgba(11, 17, 32, 0.6)",
      glass_border: "rgba(125, 141, 184, 0.12)",
      hairline_top: "rgba(255, 255, 255, 0.12)",
      shadow_card: "rgba(0, 0, 0, 0.5)",
      tooltip_bg: "rgba(19, 26, 46, 0.95)",
      tooltip_border: "rgba(125, 141, 184, 0.2)",
      pre_bg: "rgba(0, 0, 0, 0.3)",
      code_bg: "rgba(127, 127, 127, 0.18)",
      glow_opacity: "0.15",
    },
  },

  // —— 浅色（品牌色不变，仅背景/表面/前景翻转）——
  light: {
    bg: {
      body_grad: ["#F7F8FB", "#EEF1F6", "#F5F6FA"],
      surface: "#FFFFFF",
      surface_glass: "rgba(255, 255, 255, 0.82)",
      scrollbar: "#E2E8F0",
      chart_axis: "#CBD5E1",
      chart_grid: "#E9EDF3",
      chart_text: "#64748B",
      chart_text_bold: "#1E293B",
      chart_contrast: "#FFFFFF",
    },
    fg: { 200: "15 23 42", 300: "30 41 59", 400: "71 85 105", 500: "100 116 139", 600: "148 163 184", 700: "203 213 225", 800: "226 232 240" },
    ui: {
      body_text: "#1E293B",
      card_grad_a: "rgba(255, 255, 255, 0.95)", card_grad_b: "rgba(244, 247, 251, 0.95)",
      card_soft_a: "rgba(255, 255, 255, 0.9)", card_soft_b: "rgba(248, 250, 252, 0.9)",
      finding_a: "rgba(255, 255, 255, 0.95)", finding_b: "rgba(244, 247, 251, 0.85)",
      chat_bubble: "rgba(255, 255, 255, 0.92)", chat_ref: "rgba(248, 250, 252, 0.92)",
      glass_border: "rgba(100, 116, 139, 0.18)",
      hairline_top: "rgba(15, 23, 42, 0.06)",
      shadow_card: "rgba(15, 23, 42, 0.12)",
      tooltip_bg: "rgba(255, 255, 255, 0.98)",
      tooltip_border: "rgba(100, 116, 139, 0.25)",
      pre_bg: "rgba(15, 23, 42, 0.05)",
      code_bg: "rgba(100, 116, 139, 0.12)",
      glow_opacity: "0.10",
    },
  },
};

const THEME_STORAGE_KEY = "dashboard_theme_mode";

// hex → "r g b"（供 Tailwind 的 rgb(var(--x) / <alpha-value>) 使用）
function _hexToRgbTriplet(hex) {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `${r} ${g} ${b}`;
}

// hex → rgba（用于渐变色）
function _hexToRgba(hex, alpha) {
  if (hex.startsWith("rgba")) return hex;
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// =========================================================
// 应用主题：注入所有 CSS 变量
// =========================================================
function applyTheme(mode) {
  const m = THEME_MODES[mode] ? mode : "dark";
  const resolved = THEME_MODES[m];
  const colors = BRAND_COLORS;
  const bg = resolved.bg;
  const ui = resolved.ui;

  // 导出到 window（图表渲染读这里）
  window.THEME = colors;
  window.THEME_BG = bg;
  window.THEME_NAME = m;
  window.THEME_MODE = m;
  window.THEME_UI = ui;

  const root = document.documentElement;
  root.dataset.theme = m;   // 供 CSS 按模式微调

  // 品牌色
  root.style.setProperty("--color-a", colors.color_a);
  root.style.setProperty("--color-b", colors.color_b);
  root.style.setProperty("--color-negative", colors.negative);
  root.style.setProperty("--color-positive", colors.positive);
  root.style.setProperty("--color-warning", colors.warning);
  root.style.setProperty("--color-accent", colors.accent);

  // 背景
  root.style.setProperty("--bg-body-0", bg.body_grad[0]);
  root.style.setProperty("--bg-body-1", bg.body_grad[1]);
  root.style.setProperty("--bg-body-2", bg.body_grad[2]);
  root.style.setProperty("--bg-surface", bg.surface);
  root.style.setProperty("--bg-surface-glass", bg.surface_glass);
  root.style.setProperty("--bg-scrollbar", bg.scrollbar);
  root.style.setProperty("--chart-axis", bg.chart_axis);
  root.style.setProperty("--chart-grid", bg.chart_grid);
  root.style.setProperty("--chart-text", bg.chart_text);
  root.style.setProperty("--chart-text-bold", bg.chart_text_bold);
  root.style.setProperty("--chart-contrast", bg.chart_contrast);

  // 前景灰阶（Tailwind slate-200~800 映射到这些）
  Object.keys(resolved.fg).forEach(k => root.style.setProperty(`--fg-${k}`, resolved.fg[k]));

  // UI 角色色
  Object.keys(ui).forEach(k => root.style.setProperty(`--ui-${k.replace(/_/g, "-")}`, ui[k]));

  // rgba 版本（用于渐变色与发光）
  root.style.setProperty("--color-a-soft", _hexToRgba(colors.color_a, 0.25));
  root.style.setProperty("--color-b-soft", _hexToRgba(colors.color_b, 0.25));
  root.style.setProperty("--color-a-glow", _hexToRgba(colors.color_a, 0.5));
  root.style.setProperty("--color-b-glow", _hexToRgba(colors.color_b, 0.5));

  // 广播，供图表等模块重绘
  window.dispatchEvent(new CustomEvent("themechange", { detail: { mode: m } }));
}

// =========================================================
// 切换 / 记忆
// =========================================================
function setThemeMode(mode, { persist = true } = {}) {
  const m = THEME_MODES[mode] ? mode : "dark";
  applyTheme(m);
  if (persist) {
    try { localStorage.setItem(THEME_STORAGE_KEY, m); } catch (e) { /* 隐私模式忽略 */ }
  }
  updateThemeToggleUI();
  return m;
}

function getThemeMode() {
  let saved = null;
  try { saved = localStorage.getItem(THEME_STORAGE_KEY); } catch (e) { /* 忽略 */ }
  // 默认深色（保持原有观感）；仅在用户未显式选择时读系统偏好
  if (saved === "dark" || saved === "light") return saved;
  const prefersLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
  return prefersLight ? "light" : "dark";
}

function toggleThemeMode() {
  return setThemeMode(window.THEME_MODE === "dark" ? "light" : "dark");
}

// 更新开关按钮的图标/文案（按钮内 #theme-toggle-icon / #theme-toggle-label）
function updateThemeToggleUI() {
  const icon = document.getElementById("theme-toggle-icon");
  const label = document.getElementById("theme-toggle-label");
  if (icon) icon.textContent = window.THEME_MODE === "dark" ? "🌙" : "☀️";
  if (label) label.textContent = window.THEME_MODE === "dark" ? "深色" : "浅色";
}

// =========================================================
// 启动：尽早应用，避免闪烁
// =========================================================
applyTheme(getThemeMode());

// 暴露到全局
window.applyTheme = applyTheme;
window.setThemeMode = setThemeMode;
window.getThemeMode = getThemeMode;
window.toggleThemeMode = toggleThemeMode;
window.updateThemeToggleUI = updateThemeToggleUI;
window.THEME_MODES = THEME_MODES;
window.BRAND_COLORS = BRAND_COLORS;

console.log(`🎨 主题已加载: ${window.THEME_NAME}`, window.THEME, "背景:", window.THEME_BG);