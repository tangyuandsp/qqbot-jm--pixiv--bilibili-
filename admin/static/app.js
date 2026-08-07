/* ============================================================
   BiliBot 控制台 · 前端逻辑（原生 JS，零依赖）
   ============================================================ */
"use strict";

const TOKEN_KEY = "bilibot_admin_token";
const $ = (id) => document.getElementById(id);
let state = {
  config: null,
  voices: null,
  features: null,
};

/* ---------- 漂浮光点（限 12 个，纯 CSS 动画） ---------- */
function spawnSparkles() {
  const layer = $("spark-layer");
  for (let i = 0; i < 12; i++) {
    const s = document.createElement("div");
    s.className = "spark";
    s.style.left = Math.random() * 100 + "vw";
    const size = 2 + Math.random() * 4;
    s.style.width = size + "px";
    s.style.height = size + "px";
    s.style.animationDuration = (12 + Math.random() * 14) + "s";
    s.style.animationDelay = (-Math.random() * 22) + "s";
    layer.appendChild(s);
  }
}

/* ---------- API ---------- */
async function api(path, method = "GET", body = null) {
  const headers = { Authorization: "Bearer " + localStorage.getItem(TOKEN_KEY) || "" };
  let opts = { method, headers };
  if (body !== null) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  if (resp.status === 401) {
    showLogin();
    throw new Error("unauthorized");
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return resp.json();
}

/* ---------- Toast ---------- */
let toastTimer = null;
function toast(msg, ms = 2600) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), ms);
}

/* ---------- 登录 ---------- */
function showLogin() {
  $("login-overlay").classList.remove("hidden");
  $("app").classList.add("hidden");
  $("login-err").textContent = "";
}
async function doLogin() {
  const token = $("login-token").value.trim();
  if (!token) return;
  localStorage.setItem(TOKEN_KEY, token);
  $("login-err").textContent = "";
  try {
    await api("/api/config");
    $("login-overlay").classList.add("hidden");
    $("app").classList.remove("hidden");
    init();
  } catch (e) {
    localStorage.removeItem(TOKEN_KEY);
    $("login-err").textContent = "令牌错误，请重试";
  }
}

/* ---------- Tabs ---------- */
function initTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab-page").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      $("tab-" + tab.dataset.tab).classList.add("active");
      if (tab.dataset.tab === "logs") refreshLogs();
      if (tab.dataset.tab === "overview") refreshStatus();
      if (tab.dataset.tab === "ai") { loadAI(); loadAffection(); }
    });
  });
}

/* ---------- 总览 ---------- */
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const pill = $("bot-status-pill");
    if (s.bot_active && s.ws_status === "connected") {
      pill.textContent = "● Bot 在线";
      pill.className = "status-pill ok";
    } else if (s.bot_active) {
      pill.textContent = "● Bot 运行中 · NapCat 未连接";
      pill.className = "status-pill bad";
    } else {
      pill.textContent = "● Bot 未运行";
      pill.className = "status-pill bad";
    }
    $("st-bot").textContent = s.bot_active ? "运行中" : "已停止";
    $("st-ws").textContent = s.ws_status === "connected" ? "已连接" : (s.ws_status === "disconnected" ? "断开" : "未知");
    $("st-cpu").textContent = s.cpu_percent + "%";
    $("st-mem").textContent = Math.round((1 - s.mem_avail_mb / s.mem_total_mb) * 100) + "%";
    $("st-disk").textContent = s.disk_free_gb + "G / " + s.disk_total_gb + "G";
    $("st-uptime").textContent = fmtUptime(s.uptime_seconds);

    // Hero 横幅数据
    $("hero-bot").textContent = s.bot_active ? "运行中" : "已停止";
    $("hero-cpu").textContent = s.cpu_percent + "%";
    $("hero-mem").textContent = Math.round((1 - s.mem_avail_mb / s.mem_total_mb) * 100) + "%";
    $("hero-ws").textContent = s.ws_status === "connected" ? "已连接" : (s.ws_status === "disconnected" ? "断开" : "未知");
  } catch (e) {}
}

function fmtUptime(sec) {
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d > 0) return d + "天 " + h + "时";
  if (h > 0) return h + "时 " + m + "分";
  return m + " 分";
}

async function renderFeaturePreview() {
  try {
    const feats = await api("/api/features");
    const wrap = $("feature-preview");
    wrap.innerHTML = "";
    feats.forEach((f) => {
      const c = document.createElement("span");
      c.className = "chip";
      c.textContent = (f.enabled ? "✅ " : "🚫 ") + f.icon + " " + f.name;
      wrap.appendChild(c);
    });
  } catch (e) {}
}

/* ---------- 白名单 ---------- */
function renderChips(key, containerId) {
  const arr = state.config[key] || [];
  const wrap = $(containerId);
  wrap.innerHTML = "";
  arr.forEach((v) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    const x = document.createElement("span");
    x.className = "x";
    x.textContent = "×";
    x.onclick = () => {
      state.config[key] = arr.filter((i) => i !== v);
      renderChips(key, containerId);
    };
    chip.append(document.createTextNode(String(v)), x);
    wrap.appendChild(chip);
  });
}

function bindAdd(key, inputId, btn) {
  const add = () => {
    const val = parseInt($(inputId).value, 10);
    if (!Number.isInteger(val) || val <= 0) return;
    if (!state.config[key].includes(val)) state.config[key].push(val);
    $(inputId).value = "";
    renderChips(key, { groups: "wl-groups", users: "wl-users", voice: "wl-voice" }[key]);
  };
  btn.addEventListener("click", add);
  $(inputId).addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
}

async function loadWhitelist() {
  state.config = await api("/api/config");
  renderChips("allowed_groups", "wl-groups");
  renderChips("comic_allowed_users", "wl-users");
  renderChips("voice_control_users", "wl-voice");
  $("cfg-maxfile").value = Math.round(state.config.max_file_size / 1024 / 1024);
  $("cfg-maxpdf").value = Math.round(state.config.comic_max_pdf_size / 1024 / 1024);
  $("cfg-voicechars").value = state.config.voice_max_chars || 80;
  const sel = $("cfg-defaultvoice");
  sel.innerHTML = "";
  Object.keys(state.voices).forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  });
  sel.value = state.config.default_voice || Object.keys(state.voices)[0];
}

async function saveWhitelist() {
  try {
    const body = {
      allowed_groups: state.config.allowed_groups,
      comic_allowed_users: state.config.comic_allowed_users,
      voice_control_users: state.config.voice_control_users,
      max_file_size: Math.round(parseFloat($("cfg-maxfile").value) || 100) * 1024 * 1024,
      comic_max_pdf_size: Math.round(parseFloat($("cfg-maxpdf").value) || 80) * 1024 * 1024,
      voice_max_chars: Math.round(parseFloat($("cfg-voicechars").value) || 80),
      default_voice: $("cfg-defaultvoice").value,
    };
    const r = await api("/api/config", "PUT", body);
    $("whitelist-hint").textContent = "✅ 已保存，" + (r.hint || "30秒内生效");
    toast("✅ 白名单配置已保存");
    refreshStatus();
  } catch (e) {
    $("whitelist-hint").textContent = "❌ " + e.message;
    toast("❌ 保存失败: " + e.message);
  }
}

/* ---------- 音色 ---------- */
async function loadVoices() {
  state.voices = await api("/api/voices");
  const grid = $("voice-cards");
  grid.innerHTML = "";
  Object.values(state.voices).forEach((v) => {
    const card = document.createElement("div");
    card.className = "voice-card";
    card.dataset.name = v.name;

    const name = document.createElement("div");
    name.className = "vname";
    name.textContent = v.name + " (" + v.id + ")";
    card.appendChild(name);

    const row1 = document.createElement("div");
    row1.className = "v-row";
    row1.appendChild(rangeRow("语速", "speed_factor", v.speed_factor || 0.85, 0.5, 1.2, 0.05));
    row1.appendChild(rangeRow("温度", "temperature", v.temperature || 0.7, 0.3, 1.0, 0.05));
    card.appendChild(row1);

    const row2 = document.createElement("div");
    row2.className = "v-row";
    const splitLabel = document.createElement("label");
    splitLabel.textContent = "断句方式";
    const split = document.createElement("select");
    ["cut0", "cut1", "cut2", "cut3", "cut4", "cut5"].forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = m + (m === "cut0" ? "（整句，配片段间隔）" : "");
      split.appendChild(opt);
    });
    split.value = v.text_split_method || "cut5";
    split.dataset.key = "text_split_method";
    splitLabel.appendChild(split);
    row2.appendChild(splitLabel);

    const fragLabel = document.createElement("label");
    fragLabel.textContent = "片段间隔（cut0 时生效）";
    const frag = document.createElement("input");
    frag.type = "number";
    frag.step = "0.05";
    frag.min = "0";
    frag.max = "5";
    frag.value = v.fragment_interval ?? 0.3;
    frag.dataset.key = "fragment_interval";
    fragLabel.appendChild(frag);
    row2.appendChild(fragLabel);
    card.appendChild(row2);

    const adv = document.createElement("details");
    adv.className = "v-adv";
    adv.open = true;  // 默认展开，避免看起来“缺控件”
    const sum = document.createElement("summary");
    sum.textContent = "高级参数（参考音频 / 提示文本）";
    adv.appendChild(sum);
    const refLabel = document.createElement("label");
    refLabel.textContent = "参考音频路径";
    const ref = document.createElement("input");
    ref.type = "text";
    ref.value = v.ref_audio || "";
    ref.dataset.key = "ref_audio";
    refLabel.appendChild(ref);
    adv.appendChild(refLabel);

    const promptLabel = document.createElement("label");
    promptLabel.textContent = "参考文本（需与音频内容一致，改错会跑音色）";
    const prompt = document.createElement("textarea");
    prompt.value = v.prompt_text || "";
    prompt.dataset.key = "prompt_text";
    promptLabel.appendChild(prompt);
    adv.appendChild(promptLabel);
    card.appendChild(adv);

    grid.appendChild(card);
  });
}

function rangeRow(labelText, key, value, min, max, step) {
  const wrap = document.createElement("label");
  wrap.innerHTML = "";
  const title = document.createElement("span");
  title.textContent = labelText;
  const val = document.createElement("span");
  val.className = "val";
  val.textContent = Number(value).toFixed(2);
  title.appendChild(val);
  const range = document.createElement("input");
  range.type = "range";
  range.min = min;
  range.max = max;
  range.step = step;
  range.value = value;
  range.dataset.key = key;
  range.addEventListener("input", () => {
    val.textContent = Number(range.value).toFixed(2);
  });
  wrap.append(title, range);
  return wrap;
}

async function saveVoices() {
  try {
    const overrides = {};
    document.querySelectorAll(".voice-card").forEach((card) => {
      const ov = {};
      card.querySelectorAll("input[data-key], select[data-key], textarea[data-key]").forEach((el) => {
        const k = el.dataset.key;
        if (k === "fragment_interval") {
          const v = parseFloat(el.value);
          if (!isNaN(v)) ov[k] = v;
        } else if (k === "speed_factor" || k === "temperature") {
          ov[k] = parseFloat(el.value);
        } else {
          ov[k] = el.value.trim();
        }
      });
      overrides[card.dataset.name] = ov;
    });
    await api("/api/voices", "PUT", overrides);
    $("voices-hint").textContent = "✅ 已保存，30 秒内生效";
    toast("✅ 音色参数已保存");
  } catch (e) {
    $("voices-hint").textContent = "❌ " + e.message;
    toast("❌ 保存失败: " + e.message);
  }
}

/* ---------- 功能开关 ---------- */
async function loadFeatures() {
  state.features = await api("/api/features");
  const list = $("feature-list");
  list.innerHTML = "";
  state.features.forEach((f) => {
    const item = document.createElement("div");
    item.className = "feature-item";
    const icon = document.createElement("div");
    icon.className = "feature-icon";
    icon.textContent = f.icon;
    const info = document.createElement("div");
    const nm = document.createElement("div");
    nm.className = "feature-name";
    nm.textContent = f.name;
    const desc = document.createElement("div");
    desc.className = "feature-desc";
    desc.textContent = f.desc;
    info.append(nm, desc);
    const sw = document.createElement("label");
    sw.className = "switch";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = f.enabled;
    cb.dataset.fid = f.id;
    const slider = document.createElement("span");
    slider.className = "slider";
    sw.append(cb, slider);
    item.append(icon, info, sw);
    list.appendChild(item);
  });
}

async function saveFeatures() {
  try {
    const body = {};
    document.querySelectorAll("#feature-list input[type=checkbox]").forEach((cb) => {
      body[cb.dataset.fid] = cb.checked;
    });
    await api("/api/features", "PUT", body);
    $("features-hint").textContent = "✅ 已保存，30 秒内生效";
    toast("✅ 功能开关已保存");
    renderFeaturePreview();
  } catch (e) {
    $("features-hint").textContent = "❌ " + e.message;
    toast("❌ 保存失败: " + e.message);
  }
}

/* ---------- 日志 ---------- */
let logTimer = null;
async function refreshLogs() {
  try {
    const r = await api("/api/logs?lines=300");
    const box = $("log-box");
    box.textContent = r.lines.join("\n");
    box.scrollTop = box.scrollHeight;
  } catch (e) {}
}

/* ---------- AI 人设 ---------- */
async function loadAI() {
  try {
    state.ai = await api("/api/ai");
  } catch (e) {
    toast("❌ 加载 AI 设置失败: " + e.message);
    return;
  }
  const grid = $("ai-persona-grid");
  grid.innerHTML = "";
  state.ai.selected = state.ai.current;
  state.ai.personas.forEach((p) => {
    const card = document.createElement("div");
    card.className = "ai-card" + (p.id === state.ai.current ? " active" : "");
    card.dataset.pid = p.id;
    const name = document.createElement("div");
    name.className = "ai-name";
    name.textContent = p.id;
    const voice = document.createElement("div");
    voice.className = "ai-voice";
    voice.textContent = "🎙️ " + p.voice;
    const greet = document.createElement("div");
    greet.className = "ai-greet";
    greet.textContent = p.greeting || "";
    card.append(name, voice, greet);
    card.addEventListener("click", () => {
      state.ai.selected = p.id;
      document.querySelectorAll(".ai-card").forEach((el) => el.classList.toggle("active", el.dataset.pid === p.id));
    });
    grid.appendChild(card);
  });
  $("ai-current").textContent = "当前人设：" + (state.ai.current || "（未设置）");
  $("ai-ctx").value = state.ai.context_length;
  $("ai-budget").value = state.ai.turn_budget;
  $("ai-queue").value = state.ai.queue_max;
  $("ai-voice-reply").checked = state.ai.voice_reply !== false;
}

async function saveAI() {
  try {
    const ctx = Math.max(2, Math.min(50, Math.round(parseInt($("ai-ctx").value, 10) || 10)));
    const budget = Math.max(1, Math.min(5, Math.round(parseInt($("ai-budget").value, 10) || 2)));
    const qmax = Math.max(1, Math.min(10, Math.round(parseInt($("ai-queue").value, 10) || 3)));
    const body = { context_length: ctx, turn_budget: budget, voice_reply: $("ai-voice-reply").checked, queue_max: qmax };
    if (state.ai.selected) body.persona = state.ai.selected;
    const r = await api("/api/ai", "PUT", body);
    state.ai = r;
    $("ai-hint").textContent = "✅ 已保存，立即生效";
    toast("✅ AI 设置已保存");
    $("ai-current").textContent = "当前人设：" + (r.current || "（未设置）");
    $("ai-ctx").value = r.context_length;
    $("ai-budget").value = r.turn_budget;
    $("ai-queue").value = r.queue_max;
    $("ai-voice-reply").checked = r.voice_reply !== false;
  } catch (e) {
    $("ai-hint").textContent = "❌ " + e.message;
    toast("❌ 保存失败: " + e.message);
  }
}

/* ---------- 好感度 ---------- */
async function loadAffection() {
  try {
    state.affection = await api("/api/ai/affection");
  } catch (e) {
    toast("❌ 加载好感度失败: " + e.message);
    return;
  }
  const sel = $("aff-persona");
  if (sel.options.length === 0 && state.ai && state.ai.personas) {
    state.ai.personas.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.id;
      sel.appendChild(opt);
    });
    sel.value = (state.ai.current || state.ai.personas[0].id);
  }
  renderAffList();
}

function renderAffList() {
  const persona = $("aff-persona").value;
  const data = (state.affection && state.affection[persona]) || {};
  const box = $("aff-list");
  box.innerHTML = "";
  let total = 0;
  Object.entries(data).forEach(([conv, users]) => {
    Object.entries(users).forEach(([qq, value]) => {
      total++;
      const row = document.createElement("div");
      row.className = "aff-row";
      const label = conv.startsWith("p") ? "私聊 " + conv.slice(1) : "群 " + conv.slice(1);
      const span = document.createElement("span");
      span.textContent = `${label} · QQ ${qq} · 好感度 ${value}`;
      const btn = document.createElement("button");
      btn.className = "btn-ghost";
      btn.textContent = "重置";
      btn.onclick = async () => {
        try {
          await api("/api/ai/affection", "PUT", { persona, conv, user: parseInt(qq, 10), reset: true });
          toast("✅ 已重置 " + qq);
          loadAffection();
        } catch (e) { toast("❌ " + e.message); }
      };
      row.append(span, btn);
      box.appendChild(row);
    });
  });
  if (total === 0) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "暂无好感度记录（未设置过的成员默认 50）";
    box.appendChild(empty);
  }
}

/* ---------- 重启 ---------- */
async function restartBot() {
  $("restart-msg").textContent = "正在重启 Bot ...";
  try {
    const r = await api("/api/restart", "POST");
    $("restart-msg").textContent = r.ok ? "✅ 重启指令已发送" : "❌ " + (r.detail || "重启失败");
    toast(r.ok ? "✅ Bot 正在重启" : "❌ 重启失败");
    setTimeout(refreshStatus, 4000);
  } catch (e) {
    $("restart-msg").textContent = "❌ " + e.message;
  }
}

/* ---------- 初始化 ---------- */
async function init() {
  initTabs();
  $("logout-btn").addEventListener("click", () => {
    localStorage.removeItem(TOKEN_KEY);
    showLogin();
  });
  $("save-whitelist").addEventListener("click", saveWhitelist);
  $("save-voices").addEventListener("click", saveVoices);
  $("save-features").addEventListener("click", saveFeatures);
  $("restart-btn").addEventListener("click", restartBot);
  $("log-refresh").addEventListener("click", refreshLogs);
  $("save-ai").addEventListener("click", saveAI);
  $("ai-off-btn").addEventListener("click", async () => {
    try {
      await api("/api/ai", "PUT", { persona: null });
      await loadAI();
      toast("🤖 AI 人设已关闭");
    } catch (e) {
      toast("❌ " + e.message);
    }
  });
  $("aff-persona").addEventListener("change", renderAffList);
  $("aff-set").addEventListener("click", async () => {
    const persona = $("aff-persona").value;
    let conv = $("aff-conv").value.trim();
    const user = parseInt($("aff-user").value, 10);
    const value = parseInt($("aff-value").value, 10);
    if (!conv || !user || isNaN(value)) { toast("❌ 请填写群号/QQ 和好感度"); return; }
    if (/^\d+$/.test(conv)) conv = "g" + conv;
    try {
      await api("/api/ai/affection", "PUT", { persona, conv, user, value });
      toast("✅ 已设置好感度");
      $("aff-user").value = "";
      $("aff-value").value = "";
      loadAffection();
    } catch (e) { toast("❌ " + e.message); }
  });
  bindAdd("allowed_groups", "wl-groups-input", document.querySelector('[data-add="groups"]'));
  bindAdd("comic_allowed_users", "wl-users-input", document.querySelector('[data-add="users"]'));
  bindAdd("voice_control_users", "wl-voice-input", document.querySelector('[data-add="voice"]'));

  await loadVoices();
  await loadWhitelist();
  await loadFeatures();
  await refreshStatus();
  await loadAI();
  await loadAffection();
  renderFeaturePreview();

  setInterval(refreshStatus, 5000);
  setInterval(() => {
    if ($("tab-logs").classList.contains("active")) refreshLogs();
  }, 8000);
}

/* ---------- 启动 ---------- */
spawnSparkles();
// 登录监听器在页面加载时就绑定（不依赖 init）
$("login-btn").addEventListener("click", doLogin);
$("login-token").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });

if (localStorage.getItem(TOKEN_KEY)) {
  api("/api/config")
    .then(() => {
      $("login-overlay").classList.add("hidden");
      $("app").classList.remove("hidden");
      init();
    })
    .catch(() => showLogin());
} else {
  showLogin();
}
