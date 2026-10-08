/**
 * Cloudflare Worker —— 网页「重新采集」按钮的后端
 * =================================================
 * 作用：接收前端 POST 请求 → 调用 GitHub API 触发 update-data.yml 工作流。
 *
 * 为什么必须用 Worker：
 *   TapTap 接口没有 CORS 响应头，浏览器直接 fetch 会被拦截；
 *   而且触发 GitHub Actions 需要 PAT，绝不能放在公开的前端页面里。
 *   把 PAT 存在 Worker 的 Secret 里，前端只暴露 Worker 地址。
 *
 * 部署后需要设置的环境变量 / Secret（wrangler）：
 *   wrangler secret put GITHUB_TOKEN   # fine-grained PAT，勾 Actions: Read and write，仅限本仓库
 * vars（见 wrangler.toml）：GITHUB_OWNER / GITHUB_REPO / WORKFLOW_FILE / GITHUB_BRANCH / ALLOWED_ORIGIN
 */

export default {
  async fetch(request, env) {
    const cors = {
      "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN || "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };

    // 预检
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }
    if (request.method !== "POST") {
      return json({ ok: false, error: "只支持 POST 请求" }, 405, cors);
    }

    // 触发 GitHub Actions 的 workflow_dispatch
    const apiUrl =
      `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}` +
      `/actions/workflows/${env.WORKFLOW_FILE}/dispatches`;

    let resp;
    try {
      resp = await fetch(apiUrl, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "dashboard-collect-worker",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: env.GITHUB_BRANCH || "main" }),
      });
    } catch (e) {
      return json({ ok: false, error: "无法连接 GitHub API", detail: String(e) }, 502, cors);
    }

    // workflow_dispatch 成功时返回 204 No Content
    if (resp.status === 204) {
      return json({ ok: true, message: "已触发云端采集，请几分钟后刷新页面" }, 200, cors);
    }

    const detail = await resp.text();
    return json({ ok: false, error: `GitHub API ${resp.status}`, detail }, 502, cors);
  },
};

function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...cors, "Content-Type": "application/json; charset=utf-8" },
  });
}