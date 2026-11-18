// PanHarbor 前端逻辑（原生 JS，无框架）
const $ = (id) => document.getElementById(id);
let currentCandidate = null;
let currentPlan = null;

async function api(method, path, body) {
  const resp = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await resp.json().catch(() => ({}));
  if (resp.status === 401) { showLogin(); throw new Error("未登录"); }
  if (!resp.ok) throw new Error(data.error || ("HTTP " + resp.status));
  return data;
}

function fmtSize(bytes) {
  if (!bytes) return "0";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return v.toFixed(1) + units[i];
}

function showLogin() { $("loginView").classList.remove("hidden"); $("appView").classList.add("hidden"); }
function showApp() { $("loginView").classList.add("hidden"); $("appView").classList.remove("hidden"); refreshStatusDots(); }

$("loginBtn").onclick = async () => {
  $("loginError").textContent = "";
  try {
    await api("POST", "/api/login", { password: $("loginPassword").value });
    showApp();
  } catch (e) { $("loginError").textContent = e.message; }
};
$("loginPassword").addEventListener("keydown", (e) => { if (e.key === "Enter") $("loginBtn").click(); });
$("logoutBtn").onclick = async () => { await api("POST", "/api/logout", {}).catch(() => {}); showLogin(); };

// 标签页
document.querySelectorAll(".tab").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".tabpage").forEach((p) => p.classList.add("hidden"));
    $("tab-" + btn.dataset.tab).classList.remove("hidden");
    if (btn.dataset.tab === "tasks") loadTasks();
    if (btn.dataset.tab === "settings") loadSettings();
    if (btn.dataset.tab === "status") loadStatus();
  };
});

// ---------- 搜索 ----------
$("searchBtn").onclick = async () => {
  const kw = $("kw").value.trim();
  if (!kw) return;
  $("searchBtn").disabled = true;
  $("searchMsg").textContent = "搜索中（pansou 并发查多个源，可能要十几秒）…";
  $("candidates").innerHTML = ""; $("pickBox").classList.add("hidden"); $("planBox").classList.add("hidden");
  try {
    const { candidates } = await api("POST", "/api/search", { kw });
    $("searchMsg").textContent = candidates.length ? `共 ${candidates.length} 条夸克结果` : "没有搜到夸克结果，换个片名试试";
    candidates.forEach((c) => {
      const div = document.createElement("div");
      div.className = "candidate";
      const badge = c.alive === true ? '<span class="badge ok">有效</span>'
        : c.alive === false ? '<span class="badge bad">已失效</span>'
        : '<span class="badge unknown">未验</span>';
      div.innerHTML = `<div class="title">${escapeHtml(c.title || "(无标题)")}${badge}</div>
        <div class="mono break">${escapeHtml(c.url)}</div>
        <div class="muted">${escapeHtml(c.datetime || "")} ${c.password ? "提取码：" + escapeHtml(c.password) : ""}</div>`;
      const btn = document.createElement("button");
      btn.textContent = "选它";
      btn.className = "primary";
      btn.onclick = () => {
        currentCandidate = c;
        $("pickUrl").textContent = c.url;
        $("pickTitle").value = kw;
        $("pickBox").classList.remove("hidden");
        $("planBox").classList.add("hidden");
        $("pickBox").scrollIntoView({ behavior: "smooth" });
      };
      div.appendChild(btn);
      $("candidates").appendChild(div);
    });
  } catch (e) { $("searchMsg").textContent = "搜索失败：" + e.message; }
  $("searchBtn").disabled = false;
};

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

// ---------- 计划 ----------
$("planBtn").onclick = async () => {
  if (!currentCandidate) return;
  const kind = document.querySelector('input[name="kind"]:checked').value;
  const title = $("pickTitle").value.trim();
  $("planBtn").disabled = true;
  $("planMsg").textContent = "正在列分享清单并生成计划…";
  try {
    const { plan } = await api("POST", "/api/plan", {
      url: currentCandidate.url, password: currentCandidate.password || "",
      title, kind, candidate_title: currentCandidate.title || "",
    });
    currentPlan = plan;
    renderPlan(plan, title, kind);
    $("planMsg").textContent = "";
  } catch (e) { $("planMsg").textContent = "生成计划失败：" + e.message; }
  $("planBtn").disabled = false;
};

function renderPlan(plan, title, kind) {
  $("planBox").classList.remove("hidden");
  $("planSummary").textContent =
    `将存 ${plan.keep.length} 个文件（共 ${fmtSize(plan.total_size)}）到「${kind === "movie" ? "电影" : "电视剧"} / ${title}」，跳过 ${plan.skip.length} 个。`;
  $("planWarnings").innerHTML = (plan.warnings || []).map((w) => `<p class="warn">⚠ ${escapeHtml(w)}</p>`).join("");
  $("planKeep").innerHTML = "";
  plan.keep.forEach((item, idx) => {
    const row = document.createElement("div");
    row.className = "plan-item";
    row.innerHTML = `<input type="checkbox" data-idx="${idx}" checked>
      <span class="new">${escapeHtml(item.new_name)}</span>
      <span class="muted">${fmtSize(item.size)}${item.warn ? " · " + escapeHtml(item.warn) : ""}<br>原名：${escapeHtml(item.src_name)}</span>`;
    $("planKeep").appendChild(row);
  });
  $("planSkip").innerHTML = plan.skip.map((s) =>
    `<div class="skip-item"><span>${escapeHtml(s.src_name)}</span><span>— ${escapeHtml(s.reason)}</span></div>`).join("") || '<p class="muted">无</p>';
  $("planBox").dataset.title = title;
  $("planBox").dataset.kind = kind;
  $("planBox").scrollIntoView({ behavior: "smooth" });
}

$("execBtn").onclick = async () => {
  if (!currentPlan) return;
  const checked = new Set([...$("planKeep").querySelectorAll("input[type=checkbox]:checked")].map((c) => Number(c.dataset.idx)));
  const plan = { ...currentPlan, keep: currentPlan.keep.filter((_, i) => checked.has(i)) };
  if (!plan.keep.length) { $("execMsg").textContent = "一个文件都没勾"; return; }
  $("execBtn").disabled = true;
  try {
    const { task_id } = await api("POST", "/api/execute", {
      plan, title: $("planBox").dataset.title, kind: $("planBox").dataset.kind,
    });
    $("execMsg").textContent = `已提交，任务 #${task_id}，去「任务」页看进度`;
  } catch (e) { $("execMsg").textContent = "提交失败：" + e.message; }
  $("execBtn").disabled = false;
};

// ---------- 任务 ----------
async function loadTasks() {
  const { tasks } = await api("GET", "/api/tasks");
  $("taskList").innerHTML = tasks.map((t) =>
    `<div class="task-row" data-id="${t.id}"><span>#${t.id} ${escapeHtml(t.title)}（${t.kind === "movie" ? "电影" : "电视剧"}）</span><span>${escapeHtml(t.status)}</span></div>`).join("")
    || '<p class="muted">暂无任务</p>';
  $("taskList").querySelectorAll(".task-row").forEach((row) => {
    row.onclick = async () => {
      const { task } = await api("GET", "/api/tasks/" + row.dataset.id);
      $("taskDetail").classList.remove("hidden");
      const lines = (task.detail.log || []).join("\n");
      const result = task.detail.result ? "\n结果：" + JSON.stringify(task.detail.result, null, 2) : "";
      const err = task.detail.error ? "\n错误：" + task.detail.error : "";
      $("taskLog").textContent = lines + result + err;
    };
  });
}
$("refreshTasks").onclick = loadTasks;

// ---------- 设置 ----------
async function loadSettings() {
  const { settings } = await api("GET", "/api/settings");
  $("setPansouBase").value = settings.pansou_base || "";
  $("setPansouUser").value = settings.pansou_username || "";
  $("setMinVideo").value = settings.min_video_mb || 30;
  $("setCheckLimit").value = settings.check_limit || 10;
  $("setCheckAlive").checked = settings.check_alive === "1";
  window._fidNames = { movie: settings.movie_name || "", tv: settings.tv_name || "" };
  fillFolderSelect($("setMovieFid"), settings.movie_fid, settings.movie_name);
  fillFolderSelect($("setTvFid"), settings.tv_fid, settings.tv_name);
  $("verifyQuarkMsg").textContent = settings.has_quark_cookie ? `已配置 Cookie（尾号 ${settings.quark_cookie_tail}）` : "尚未配置 Cookie";
}

function fillFolderSelect(sel, fid, name) {
  sel.innerHTML = "";
  if (fid) {
    const opt = document.createElement("option");
    opt.value = fid; opt.textContent = name || fid; opt.selected = true;
    sel.appendChild(opt);
  }
}

$("verifyQuark").onclick = async () => {
  $("verifyQuarkMsg").textContent = "验证中…";
  try {
    // 先把页面上新填的 Cookie 存进去再验
    await saveSettingsCore();
    const { root_folders } = await api("POST", "/api/verify/quark", {});
    for (const [selId, key] of [["setMovieFid", "movie"], ["setTvFid", "tv"]]) {
      const sel = $(selId);
      const current = sel.value;
      sel.innerHTML = "";
      root_folders.forEach((f) => {
        const opt = document.createElement("option");
        opt.value = f.fid; opt.textContent = f.name;
        if (f.fid === current) opt.selected = true;
        sel.appendChild(opt);
      });
      sel.dataset.names = JSON.stringify(Object.fromEntries(root_folders.map((f) => [f.fid, f.name])));
    }
    $("verifyQuarkMsg").textContent = "Cookie 有效，已读取根目录，请在下拉里选电影/电视剧目录后保存";
  } catch (e) { $("verifyQuarkMsg").textContent = "验证失败：" + e.message; }
};

$("verifyPansou").onclick = async () => {
  $("verifyPansouMsg").textContent = "验证中…";
  try {
    await saveSettingsCore();
    const r = await api("POST", "/api/verify/pansou", {});
    $("verifyPansouMsg").textContent = r.ok ? "pansou 正常：" + r.message : "pansou 异常：" + r.message;
  } catch (e) { $("verifyPansouMsg").textContent = "验证失败：" + e.message; }
};

async function saveSettingsCore() {
  const movieSel = $("setMovieFid"), tvSel = $("setTvFid");
  const namesOf = (sel) => {
    try { return JSON.parse(sel.dataset.names || "{}")[sel.value] || ""; } catch { return ""; }
  };
  return api("POST", "/api/settings", {
    pansou_base: $("setPansouBase").value.trim(),
    pansou_username: $("setPansouUser").value.trim(),
    pansou_password: $("setPansouPass").value,
    quark_cookie: $("setQuarkCookie").value.trim(),
    movie_fid: movieSel.value, tv_fid: tvSel.value,
    movie_name: namesOf(movieSel) || window._fidNames?.movie || "",
    tv_name: namesOf(tvSel) || window._fidNames?.tv || "",
    min_video_mb: $("setMinVideo").value || "30",
    check_limit: $("setCheckLimit").value || "10",
    check_alive: $("setCheckAlive").checked ? "1" : "0",
  });
}

$("saveSettings").onclick = async () => {
  try { await saveSettingsCore(); $("saveSettingsMsg").textContent = "已保存"; }
  catch (e) { $("saveSettingsMsg").textContent = "保存失败：" + e.message; }
};

$("changePassword").onclick = async () => {
  const pw = $("setNewPassword").value;
  if (!pw) return;
  await api("POST", "/api/settings/password", { password: pw });
  alert("密码已修改，下次登录用新密码");
};

// ---------- 状态 ----------
async function refreshStatusDots() {
  try {
    const s = await api("GET", "/api/status");
    $("dotPansou").className = "dot " + (s.pansou.ok ? "ok" : "bad");
    $("dotQuark").className = "dot " + (s.quark.ok ? "ok" : "bad");
    return s;
  } catch { return null; }
}

async function loadStatus() {
  $("statusBox").innerHTML = '<p class="muted">检查中…</p>';
  const s = await refreshStatusDots();
  if (!s) { $("statusBox").innerHTML = '<p class="error">状态获取失败</p>'; return; }
  const ka = s.keepalive || {};
  const kaText = ka.at
    ? `${ka.ok ? "✅" : "❌"} ${new Date(ka.at * 1000).toLocaleString()} ${escapeHtml(ka.message || "")}`
    : "尚无记录（启动后几分钟内首次执行，之后约每 24 小时一次）";
  $("statusBox").innerHTML = `<div class="card status-card">
    pansou：${s.pansou.ok ? "✅" : "❌"} ${escapeHtml(s.pansou.message)}<br>
    夸克：${s.quark.ok ? "✅" : "❌"} ${escapeHtml(s.quark.message)}<br>
    夸克 Cookie 保活：${kaText}<br>
    任务：共 ${s.tasks.total}，完成 ${s.tasks.done}，失败 ${s.tasks.failed}</div>`;
}
$("refreshStatus").onclick = loadStatus;

// 启动：先试着拉状态判断登录态
(async () => {
  try { await api("GET", "/api/settings"); showApp(); }
  catch { showLogin(); }
})();
