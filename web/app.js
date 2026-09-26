/* Bonsai Launcher 前端逻辑 (pywebview js_api 桥接) */
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
let CFG = {};          // 后端配置镜像
let STATE = {};        // get_state 快照
let messages = [];     // 对话历史
let generating = false;

const api = () => window.pywebview.api;

function dlog(m) {
  const v = $("#log-view");
  if (v) { v.textContent += `[boot] ${m}\n`; v.scrollTop = v.scrollHeight; }
  console.log("[boot]", m);
}
window.addEventListener("error", (e) => dlog("JS错误: " + e.message + " @" + (e.filename||"").split("/").pop() + ":" + e.lineno));
window.addEventListener("unhandledrejection", (e) => dlog("Promise错误: " + (e.reason && e.reason.stack || e.reason)));

/* ---------------- 通用 ---------------- */
function toast(msg, ms = 2200) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), ms);
}

function fmtGB(bytes) { return (bytes / 1e9).toFixed(2) + " GB"; }
function fmtMB(b) { return b >= 1024 ? (b / 1024).toFixed(1) + " GB" : b + " MB"; }

/* ---------------- 导航 ---------------- */
const PAGE_TITLES = { chat: "对话助手", models: "模型管理", params: "参数调节", settings: "系统设置" };
$$(".nav-item").forEach(btn => btn.addEventListener("click", () => gotoPage(btn.dataset.page)));
$$("[data-goto]").forEach(el => el.addEventListener("click", () => gotoPage(el.dataset.goto)));
function gotoPage(p) {
  $$(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.page === p));
  $$(".page").forEach(s => s.classList.toggle("active", s.id === "page-" + p));
  $("#page-title").textContent = PAGE_TITLES[p] || p;
}

/* ---------------- 配置绑定 ---------------- */
/* 数值格式化: 滑杆右侧数值与徽章 */
const FMT_VAL = {
  ctx: v => v >= 1024 ? ((v / 1024) % 1 ? (v / 1024).toFixed(1) : v / 1024) + "K" : String(v),
  ngl: v => (v >= 64 || v < 0) ? "全部" : String(v) + " 层",
};
const FMT_BADGE = {
  ctx: () => "tokens",
  ngl: v => "≈" + ((v >= 64 || v < 0 ? 64 : v) / 64 * 5.95).toFixed(1) + " GB 显存",
};
function fmtVal(key, v) { return (FMT_VAL[key] || (x => String(x)))(v); }
function paintVal(key, v) {
  $$(`[data-sval="${key}"]`).forEach(s => s.textContent = fmtVal(key, v));
  $$(`[data-badge="${key}"]`).forEach(s => { if (FMT_BADGE[key]) s.textContent = FMT_BADGE[key](v); });
}
/* 把 CFG 重新刷到所有绑定控件 (预设应用后用) */
function syncCfgToUI() {
  $$("input[type=range][data-cfg]").forEach(el => {
    const key = el.dataset.cfg;
    let v = parseFloat(CFG[key]);
    if (isNaN(v)) v = parseFloat(el.min);
    v = Math.min(Math.max(v, parseFloat(el.min)), parseFloat(el.max));
    el.value = v; paintSlider(el); paintVal(key, v);
  });
  $$("[data-cfg-num]").forEach(el => { el.value = CFG[el.dataset.cfgNum]; });
  $$("[data-cfg-sel]").forEach(el => { el.value = CFG[el.dataset.cfgSel]; });
  $$("[data-cfg-chk]").forEach(el => { el.checked = !!CFG[el.dataset.cfgChk]; });
}

function bindConfig() {
  // 滑杆
  $$("input[type=range][data-cfg]").forEach(el => {
    const key = el.dataset.cfg;
    el.addEventListener("input", () => {
      CFG[key] = parseFloat(el.value);
      paintSlider(el);
      $$(`input[type=range][data-cfg="${key}"]`).forEach(o => { if (o !== el) { o.value = el.value; paintSlider(o); } });
      paintVal(key, parseFloat(el.value));
      markPresetDirty();
      debouncedSave();
    });
  });
  // 数字输入
  $$("[data-cfg-num]").forEach(el => {
    const key = el.dataset.cfgNum;
    el.value = CFG[key];
    el.addEventListener("change", () => { CFG[key] = el.value; markPresetDirty(); debouncedSave(); });
  });
  // 下拉
  $$("[data-cfg-sel]").forEach(el => {
    const key = el.dataset.cfgSel;
    el.value = CFG[key];
    el.addEventListener("change", () => { CFG[key] = el.value; markPresetDirty(); debouncedSave(); });
  });
  // 开关
  $$("[data-cfg-chk]").forEach(el => {
    const key = el.dataset.cfgChk;
    el.checked = !!CFG[key];
    el.addEventListener("change", () => { CFG[key] = el.checked; debouncedSave(); });
  });
}
/* ---------------- 预设方案 ---------------- */
const PRESETS = {
  min:   { ctx: 4096,  cache_k: "q8_0", cache_v: "q8_0", ngl: 64 },
  chat:  { ctx: 8192,  cache_k: "f16",  cache_v: "f16",  ngl: 64 },
  agent: { ctx: 32768, cache_k: "q8_0", cache_v: "q8_0", ngl: 64 },
};
function markPresetDirty() {
  $$(".preset-card").forEach(c => c.classList.remove("active"));
  const t = $("#preset-tag");
  if (t) t.textContent = "自定义";
}
$$(".preset-card").forEach(card => card.addEventListener("click", () => {
  Object.assign(CFG, PRESETS[card.dataset.preset]);
  syncCfgToUI();
  $$(".preset-card").forEach(c => c.classList.toggle("active", c === card));
  $("#preset-tag").textContent = "已应用: " + card.querySelector("b").textContent.split(" ")[0];
  debouncedSave();
  toast("预设已应用, 重启服务后生效");
}));

function paintSlider(el) {
  const pct = (el.value - el.min) / (el.max - el.min) * 100;
  el.style.setProperty("--fill", pct + "%");
}
let saveTimer = null;
function debouncedSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => api().save_config(CFG), 400);
}

/* ---------------- 状态刷新 ---------------- */
function applyState(st) {
  STATE = st;
  const hw = st.hw || {};
  const vendorMap = { nvidia: "NVIDIA 显卡", amd: "AMD 显卡", intel: "Intel 显卡", cpu: "纯 CPU 推理", unknown: "检测中..." };
  $("#hw-vendor").textContent = vendorMap[hw.vendor] || hw.vendor;
  $("#hw-names").textContent = (hw.names || []).join(" · ");
  $("#hw-cuda").textContent = hw.cuda || "—";

  // 系统信息
  const gpuNames = (hw.names || []).join(" / ") || "未检测到";
  ["#sys-os", "#set-os"].forEach(s => $(s).textContent = "Windows");
  ["#sys-gpu", "#set-gpu"].forEach(s => { $(s).textContent = gpuNames; $(s).title = gpuNames; });
  ["#sys-cuda", "#set-cuda"].forEach(s => $(s).textContent = hw.cuda || "—");

  // 运行时
  $("#rt-tag").textContent = st.runtime.installed ? "已安装" : "未安装";
  $("#rt-tag").className = "tag" + (st.runtime.installed ? "" : " warn");
  $("#rt-version").textContent = st.runtime.version
    ? `${st.runtime.version} (${st.runtime.backend || "?"})` : "--";
  $("#rt-path").textContent = st.runtime.path || "--";
  $("#rt-path").title = st.runtime.path || "";

  // 模型
  applyModel(st.model);

  // 服务
  applyServer(st.server);
  $("#api-url").textContent = st.server.url;
}

function applyModel(m) {
  if (!m) return;
  const ok = m.path && m.exists;
  $("#model-tag").textContent = ok ? "已导入" : (m.path ? "文件缺失" : "未导入");
  $("#model-tag").className = "tag" + (ok ? "" : " warn");
  $("#model-path").textContent = m.path || "--";
  $("#model-path").title = m.path || "";
  $("#model-size").textContent = ok ? fmtGB(m.size) : "--";
  $("#side-model-path").textContent = m.name || "未导入";
  $("#side-model-path").title = m.path || "";
  if (ok) $("#banner-model-sub").textContent = `${m.name} · ${fmtGB(m.size)}`;
}

function applyServer(sv) {
  const running = sv.running, ready = sv.ready;
  const pill = $("#status-pill");
  pill.className = "status-pill" + (ready ? " on" : running ? " busy" : "");
  $("#status-text").textContent = ready ? "本地服务运行中" : running ? "服务启动中..." : "服务未启动";
  const tagText = ready ? "运行中" : running ? "启动中" : "未启动";
  ["#srv-tag", "#side-srv-tag"].forEach(s => {
    $(s).textContent = tagText;
    $(s).className = "tag" + (ready ? "" : running ? " warn" : " off");
  });
  ["#btn-start", "#side-btn-start"].forEach(s => { $(s).classList.toggle("hidden", running); });
  ["#btn-stop", "#side-btn-stop"].forEach(s => { $(s).classList.toggle("hidden", !running); });
}

/* ---------------- 统计轮询 ---------------- */
async function pollStats() {
  try {
    const st = await api().poll_stats();
    if (st.gpu.ok) {
      $("#stat-gpu-util").textContent = st.gpu.util + "%";
      $("#meter-gpu").style.width = st.gpu.util + "%";
      $("#stat-vram").textContent = `${(st.gpu.vram_used / 1024).toFixed(1)} / ${(st.gpu.vram_total / 1024).toFixed(0)} GB`;
      $("#meter-vram").style.width = (st.gpu.vram_used / st.gpu.vram_total * 100) + "%";
      $("#side-meter-vram").style.width = (st.gpu.vram_used / st.gpu.vram_total * 100) + "%";
      $("#side-vram-text").textContent = `${fmtMB(st.gpu.vram_used)} / ${fmtMB(st.gpu.vram_total)}`;
    } else {
      $("#stat-gpu-util").textContent = "N/A";
      $("#stat-vram").textContent = "N/A";
      $("#side-vram-text").textContent = "GPU 计数器不可用";
    }
    $("#stat-tps").textContent = st.tps ? st.tps + " tok/s" : "--";
    $("#meter-tps").style.width = Math.min(st.tps / 60 * 100, 100) + "%";
    const ramGB = st.ram.total ? (st.ram.total / 1e9).toFixed(0) + " GB" : "--";
    ["#sys-ram", "#set-ram"].forEach(s => $(s).textContent = ramGB);
    // 同步服务状态(兜底)
    if (STATE.server && (st.running !== STATE.server.running || st.ready !== STATE.server.ready)) {
      STATE.server.running = st.running; STATE.server.ready = st.ready;
      applyServer(STATE.server);
    }
  } catch (e) { /* 后端未就绪 */ }
}
setInterval(pollStats, 2000);

/* ---------------- 模型管理页动作 ---------------- */
$("#btn-re-detect").addEventListener("click", async () => {
  $("#hw-vendor").textContent = "检测中...";
  await api().refresh_hw();
});

$("#btn-dl-runtime").addEventListener("click", async (e) => {
  const btn = e.target;
  btn.disabled = true;
  $("#dl-wrap").classList.remove("hidden");
  $("#dl-text").textContent = "正在获取版本信息...";
  const r = await api().download_runtime($("#sel-backend").value);
  if (!r.ok) { btn.disabled = false; toast(r.err || "无法开始下载"); }
});

window.addEventListener("dl_progress", (ev) => {
  const d = ev.detail;
  $("#dl-wrap").classList.remove("hidden");
  $("#dl-bar").style.width = d.pct.toFixed(1) + "%";
  $("#dl-text").textContent = d.total
    ? `${(d.done / 1e9).toFixed(2)} / ${(d.total / 1e9).toFixed(2)} GB   ${(d.speed / 1e6).toFixed(1)} MB/s`
    : `${(d.done / 1e6).toFixed(0)} MB`;
});

window.addEventListener("runtime_done", async (ev) => {
  $("#btn-dl-runtime").disabled = false;
  if (ev.detail.ok) {
    toast(ev.detail.skipped ? "已是最新版本, 无需下载" : "运行时安装完成");
    refreshState();
  }
  else { toast("运行时下载失败: " + (ev.detail.err || ""), 4000); $("#dl-text").textContent = "失败, 详见日志"; }
});

$("#btn-check-update").addEventListener("click", async () => {
  $("#rt-latest").textContent = "查询中...";
  await api().runtime_status();
});

window.addEventListener("rt_status", (ev) => {
  const d = ev.detail;
  if (!d.ok) { $("#rt-latest").textContent = "查询失败"; toast("版本查询失败: " + (d.err || ""), 4000); return; }
  $("#rt-latest").textContent = d.latest;
  if (d.current && d.up_to_date) toast(`已是最新 (${d.latest})`);
  else if (d.current) toast(`发现新版本: ${d.current} → ${d.latest}, 点「下载 / 更新运行时」升级`, 4000);
});

// ---- 系统依赖检测
async function refreshDeps() {
  const list = $("#deps-list");
  list.innerHTML = '<p class="hint">检测中...</p>';
  const deps = await api().check_deps();
  list.innerHTML = deps.map(d => `
    <div class="kv">
      <label><a href="${d.url}" target="_blank" class="dep-link">${d.name}</a></label>
      <div class="kv-val">
        <span class="tag${d.ok ? "" : " warn"}">${d.ok ? "正常" : "缺失"}</span>
        <span class="dep-ver">${d.version || ""}</span>
        <div class="dep-desc">${d.desc}</div>
      </div>
    </div>`).join("");
}
$("#btn-recheck-deps").addEventListener("click", refreshDeps);

$("#btn-import-model").addEventListener("click", async () => {
  const m = await api().pick_model();
  if (m) { applyModel(m); STATE.model = m; toast("模型已导入"); }
});

async function startServer() {
  const r = await api().start_server(CFG);
  if (!r.ok) { toast(r.err, 4000); return; }
  applyServer({ running: true, ready: false });
}
async function stopServer() {
  await api().stop_server();
  applyServer({ running: false, ready: false });
}
["#btn-start", "#side-btn-start"].forEach(s => $(s).addEventListener("click", startServer));
["#btn-stop", "#side-btn-stop"].forEach(s => $(s).addEventListener("click", stopServer));
$("#btn-webui").addEventListener("click", () => api().open_webui());
$("#btn-copy-api").addEventListener("click", async () => {
  const url = $("#api-url").textContent;
  try { await navigator.clipboard.writeText(url); } catch (e) {}
  toast("API 地址已复制: " + url);
});
$("#btn-clear-log").addEventListener("click", () => { $("#log-view").textContent = ""; });

/* ---------------- 后端事件 ---------------- */
window.addEventListener("log", (ev) => {
  const v = $("#log-view");
  v.textContent += `[${ev.detail.t}] ${ev.detail.msg}\n`;
  v.scrollTop = v.scrollHeight;
});
window.addEventListener("server", (ev) => {
  STATE.server = Object.assign(STATE.server || {}, ev.detail);
  applyServer(STATE.server);
});
window.addEventListener("hw", (ev) => { STATE.hw = ev.detail; applyState(STATE); });

async function refreshState() {
  try {
    const st = await api().get_state();
    if (!st) { dlog("get_state 返回空"); return; }
    dlog("get_state OK");
    CFG = Object.assign(CFG, st.config);
    applyState(st);
    if (!window._bound) { window._bound = true; bindConfig(); }
    syncCfgToUI();
    dlog("配置绑定完成");
  } catch (e) { dlog("refreshState 失败: " + (e && e.stack || e)); }
}

/* ---------------- 对话 ---------------- */
function mdLite(text) {
  let h = text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  h = h.replace(/```([\s\S]*?)```/g, (_, c) => `<code>${c.trim()}</code>`);
  h = h.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  h = h.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  return h;
}

function addMsg(role, text) {
  $("#chat-empty")?.remove();
  const wrap = $("#chat-scroll");
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.innerHTML = `<div class="avatar">${role === "user" ? "我" : "B2"}</div><div class="bubble">${mdLite(text)}</div>`;
  wrap.appendChild(div);
  wrap.scrollTop = wrap.scrollHeight;
  return div.querySelector(".bubble");
}

async function sendChat() {
  const input = $("#chat-input");
  const text = input.value.trim();
  if (!text || generating) return;
  input.value = "";
  messages.push({ role: "user", content: text });
  addMsg("user", text);
  const bubble = addMsg("ai", "");
  bubble.innerHTML = '<span class="cursor"></span>';
  let acc = "";

  generating = true;
  $("#btn-send").disabled = true;
  $("#btn-stop-gen").classList.remove("hidden");

  const onDelta = (ev) => {
    acc += ev.detail.text;
    bubble.innerHTML = mdLite(acc) + '<span class="cursor"></span>';
    const sc = $("#chat-scroll");
    sc.scrollTop = sc.scrollHeight;
  };
  const onDone = (ev) => {
    window.removeEventListener("chat_delta", onDelta);
    window.removeEventListener("chat_done", onDone);
    generating = false;
    $("#btn-send").disabled = false;
    $("#btn-stop-gen").classList.add("hidden");
    if (ev.detail.ok) {
      bubble.innerHTML = mdLite(acc) || "(无输出)";
      if (acc) messages.push({ role: "assistant", content: acc });
      if (ev.detail.tps) $("#stat-tps").textContent = ev.detail.tps + " tok/s";
    } else {
      bubble.innerHTML = mdLite(acc) + `\n\n⚠ ${ev.detail.err || "生成失败"}`;
    }
  };
  window.addEventListener("chat_delta", onDelta);
  window.addEventListener("chat_done", onDone);

  const r = await api().chat(messages);
  if (!r.ok) {
    window.removeEventListener("chat_delta", onDelta);
    window.removeEventListener("chat_done", onDone);
    generating = false;
    $("#btn-send").disabled = false;
    $("#btn-stop-gen").classList.add("hidden");
    bubble.innerHTML = "⚠ " + (r.err || "调用失败");
  }
}

$("#btn-send").addEventListener("click", sendChat);
$("#btn-stop-gen").addEventListener("click", () => api().chat_stop());
$("#btn-clear-chat").addEventListener("click", () => {
  messages = [];
  $("#chat-scroll").innerHTML = `<div class="chat-empty" id="chat-empty">
    <div class="empty-logo">B2</div><p>你好, 我是本地运行的 Bonsai 2 27B</p>
    <span>所有对话都在本机完成, 数据不出端</span></div>`;
});
$("#chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

/* ---------------- 启动 ---------------- */
async function boot() {
  if (window._booted) return;
  window._booted = true;
  dlog("boot 开始");
  for (let i = 0; i < 100 && !window.pywebview; i++) await new Promise(r => setTimeout(r, 50));
  dlog("bridge: " + (window.pywebview ? "就绪" : "缺失"));
  try { await api().refresh_hw(); } catch (e) { dlog("refresh_hw: " + e); }
  await refreshState();
  try { await pollStats(); } catch (e) { dlog("pollStats: " + e); }
  try { refreshDeps(); } catch (e) { dlog("refreshDeps: " + e); }
  try { api().runtime_status(); } catch (e) { dlog("runtime_status: " + e); }
  dlog("boot 完成");
}
window.addEventListener("pywebviewready", boot);
// 兜底: 部分版本不触发 pywebviewready
setTimeout(() => { if (!STATE.server) boot(); }, 800);
