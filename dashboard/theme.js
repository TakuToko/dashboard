/**
 * theme.js — 仪表盘主题配置
 * ============================================
 * 所有颜色都集中在这里。改颜色只改这一个文件。
 */

const THEME_PRESETS = {
  // —— 预设 1：蓝 vs 橙 + 暗色主题（原版自走棋风格）——
  wzq_jcc_classic: {
    name: "自走棋经典（蓝 vs 橙 · 暗）",
    colors: {
      color_a: "#3B82F6", color_b: "#F97316",
      negative: "#EF4444", positive: "#10B981", warning: "#F59E0B", accent: "#22D3EE",
      palette_positive: ["#3B82F6", "#22D3EE", "#A78BFA", "#60A5FA", "#818CF8", "#F472B6"],
      palette_negative: ["#EF4444", "#F97316", "#FBBF24", "#DC2626", "#EA580C"],
    },
    bg: {
      body_grad: ["#0F172A", "#1E1B4B", "#0F172A"],
      surface: "#1E293B",
      surface_glass: "rgba(30, 41, 59, 0.7)",
      scrollbar: "#0F172A",
      chart_axis: "#475569", chart_grid: "#334155",
      chart_text: "#94a3b8", chart_text_bold: "#e2e8f0",
      chart_contrast: "#1E293B",
    }
  },

  // —— 预设 2：粉 vs 绿 + 暗色主题 ——
  pink_mint: {
    name: "柔和粉 vs 薄荷绿 · 暗",
    colors: {
      color_a: "#F19B88", color_b: "#84D7BB",
      negative: "#E57373", positive: "#66BB6A", warning: "#FFB74D", accent: "#BA68C8",
      palette_positive: ["#F19B88", "#BA68C8", "#84D7BB", "#4FC3F7", "#F48FB1", "#A5D6A7"],
      palette_negative: ["#E57373", "#FF8A65", "#FFB74D", "#EF5350", "#FB8C00"],
    },
    bg: {
      body_grad: ["#0F172A", "#1E1B4B", "#0F172A"],
      surface: "#1E293B",
      surface_glass: "rgba(30, 41, 59, 0.7)",
      scrollbar: "#0F172A",
      chart_axis: "#475569", chart_grid: "#334155",
      chart_text: "#94a3b8", chart_text_bold: "#e2e8f0",
      chart_contrast: "#1E293B",
    }
  },

  // —— 预设 3：赛博朋克紫 vs 电光青 + 暗色霓虹背景 ——
  cyberpunk: {
    name: "赛博朋克（紫 vs 青）",
    colors: {
      color_a: "#C026D3", color_b: "#06B6D4",
      negative: "#FF1744", positive: "#00E676", warning: "#FFEA00", accent: "#F0ABFC",
      palette_positive: ["#C026D3", "#06B6D4", "#F0ABFC", "#67E8F9", "#E879F9", "#A5F3FC"],
      palette_negative: ["#FF1744", "#FF5252", "#FFAB40", "#D50000", "#FF6E40"],
    },
    bg: {
      body_grad: ["#0A0A0F", "#1A0A2E", "#050510"],
      surface: "#151525",
      surface_glass: "rgba(21, 21, 37, 0.75)",
      scrollbar: "#0A0A0F",
      chart_axis: "#3D2D5C", chart_grid: "#1F1535",
      chart_text: "#A09BC0", chart_text_bold: "#E8E0F5",
      chart_contrast: "#151525",
    }
  },

  // —— 预设 4：莫兰迪低饱和 + 米白亮主题 ——
  morandi: {
    name: "莫兰迪（亮主题）",
    colors: {
      color_a: "#8B9DA5", color_b: "#9CAF88",
      negative: "#C9807C", positive: "#7CAE82", warning: "#D4A76A", accent: "#B08D57",
      palette_positive: ["#8B9DA5", "#9CAF88", "#B08D57", "#A8B5A0", "#C4B89C", "#D4C5B0"],
      palette_negative: ["#C9807C", "#D4A76A", "#CD7F32", "#A0522D", "#8B4513"],
    },
    bg: {
      body_grad: ["#F7F4EF", "#EFEAE2", "#F5F1E8"],
      surface: "#FFFFFF",
      surface_glass: "rgba(255, 255, 255, 0.85)",
      scrollbar: "#E8E2D8",
      chart_axis: "#B8AFA0", chart_grid: "#E0D8C8",
      chart_text: "#6B6558", chart_text_bold: "#2D2A24",
      chart_contrast: "#FFFFFF",
    }
  },

  // —— 预设 5：游戏数据 · 夜空金蓝 ——
  game_night: {
    name: "游戏数据（琥珀金 vs 电光蓝 · 深空）",
    colors: {
      color_a: "#F59E0B",           // 王者万象棋 —— 琥珀金（王者品牌色）
      color_b: "#38BDF8",           // 金铲铲之战 —— 电光蓝
      negative: "#F43F5E",          // 负面 —— 玫瑰红
      positive: "#10B981",          // 正面 —— 翠绿
      warning: "#FBBF24",           // 警示 —— 琥珀亮
      accent: "#A78BFA",            // 点缀 —— 紫罗兰
      palette_positive: ["#F59E0B", "#38BDF8", "#A78BFA", "#FBBF24", "#22D3EE", "#C084FC", "#34D399"],
      palette_negative: ["#F43F5E", "#FB7185", "#F97316", "#FBBF24", "#EF4444"],
    },
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
    }
  },
};

// =========================================================
// 👇 这里是唯一需要改的配置！
// =========================================================

// 留空 "" 表示用下面 CUSTOM 手动配的 colors
const ACTIVE_THEME = "game_night";

// 当 ACTIVE_THEME 为空时，用这里手动配
const CUSTOM_COLORS = {
  color_a: "#F59E0B", color_b: "#38BDF8",
  negative: "#F43F5E", positive: "#10B981", warning: "#FBBF24", accent: "#A78BFA",
  palette_positive: ["#F59E0B", "#38BDF8", "#A78BFA", "#FBBF24", "#22D3EE", "#C084FC", "#34D399"],
  palette_negative: ["#F43F5E", "#FB7185", "#F97316", "#FBBF24", "#EF4444"],
};

// 当 ACTIVE_THEME 为空时，用这里手动配背景
const CUSTOM_BG = {
  body_grad: ["#0B1120", "#1A0F2E", "#050814"],
  surface: "#131A2E",
  surface_glass: "rgba(19, 26, 46, 0.72)",
  scrollbar: "#0B1120",
  chart_axis: "#2D3B5C", chart_grid: "#1C2640",
  chart_text: "#7D8DB8", chart_text_bold: "#E0E8F5",
  chart_contrast: "#131A2E",
};

// =========================================================
// 自动解析：预设优先，否则 CUSTOM
// =========================================================
const THEME = (function () {
  const isPreset = ACTIVE_THEME && THEME_PRESETS[ACTIVE_THEME];
  const resolved = isPreset
    ? THEME_PRESETS[ACTIVE_THEME]
    : { colors: CUSTOM_COLORS, bg: CUSTOM_BG };

  const colors = resolved.colors;
  const bg = resolved.bg;

  // 导出到 window
  window.THEME = colors;
  window.THEME_BG = bg;
  window.THEME_NAME = ACTIVE_THEME || "custom";

  // 注入颜色 CSS 变量
  const root = document.documentElement;
  root.style.setProperty("--color-a", colors.color_a);
  root.style.setProperty("--color-b", colors.color_b);
  root.style.setProperty("--color-negative", colors.negative);
  root.style.setProperty("--color-positive", colors.positive);
  root.style.setProperty("--color-warning", colors.warning);
  root.style.setProperty("--color-accent", colors.accent);

  // 注入背景 CSS 变量
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

  // rgba 版本（用于渐变色）
  const hexToRgba = (hex, alpha) => {
    if (hex.startsWith("rgba")) return hex;
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  };
  root.style.setProperty("--color-a-soft", hexToRgba(colors.color_a, 0.25));
  root.style.setProperty("--color-b-soft", hexToRgba(colors.color_b, 0.25));
  root.style.setProperty("--color-a-glow", hexToRgba(colors.color_a, 0.5));
  root.style.setProperty("--color-b-glow", hexToRgba(colors.color_b, 0.5));

  return colors;
})();

console.log(`🎨 主题已加载: ${window.THEME_NAME}`, THEME, "背景:", THEME_BG);
