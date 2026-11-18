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
// 第一步：查影片（元数据条目）；第二步：选中条目再找资源（pansou）。
// 也保留「直接搜资源」：跳过条目、用原始关键词走老流程兜底。
let planTitleHint = "";  // 选中条目/直搜时带入计划的片名
let planKindHint = "";   // 选中条目的类型（movie/tv），用于自动勾选

$("searchBtn").onclick = async () => {
  const kw = $("kw").value.trim();
  if (!kw) return;
  $("searchBtn").disabled = true;
  $("searchMsg").textContent = "正在查影片条目（TMDB + 豆瓣）…";
  $("metaResults").innerHTML = ""; $("candidates").innerHTML = "";
  $("pickBox").classList.add("hidden"); $("planBox").classList.add("hidden");
  try {
    const { items, notes } = await api("GET", "/api/meta/search?q=" + encodeURIComponent(kw));
    $("metaAttribution").classList.remove("hidden");
    $("searchMsg").textContent = items.length
      ? `找到 ${items.length} 个条目，选一个再「找资源」；都不对可用「直接搜资源」`
      : "没查到条目，可用「直接搜资源」按原关键词找";
    if (notes && notes.length) $("searchMsg").textContent += "（" + notes.join("；") + "）";
    items.forEach((it) => {
      const card = document.createElement("div");
      card.className = "meta-card";
      const kindText = it.kind === "tv" ? "电视剧" : "电影";
      const srcText = it.source === "tmdb" ? "TMDB" : "豆瓣";
      const rating = it.rating ? `<span class="badge ok">★ ${it.rating}</span>` : "";
      card.innerHTML = `
        ${it.poster ? `<img class="meta-poster" src="${escapeHtml(it.poster)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : '<div class="meta-poster meta-noposter">无海报</div>'}
        <div class="meta-info">
          <div class="title">${escapeHtml(it.title)}${rating}</div>
          <div class="muted">${escapeHtml(it.original_title || "")} ${it.year ? "· " + escapeHtml(it.year) : ""} · ${kindText} · ${srcText}</div>
          <div class="muted meta-overview">${escapeHtml(it.overview || "")}</div>
        </div>`;
      const btn = document.createElement("button");
      btn.textContent = "找资源";
      btn.className = "primary";
      btn.onclick = () => runResourceSearch(it.title, it);
      card.appendChild(btn);
      $("metaResults").appendChild(card);
    });
  } catch (e) { $("searchMsg").textContent = "查影片失败：" + e.message + "；可用「直接搜资源」"; }
  $("searchBtn").disabled = false;
};

$("directSearchBtn").onclick = () => {
  const kw = $("kw").value.trim();
  if (kw) runResourceSearch(kw, null);
};

async function runResourceSearch(kw, metaItem) {
  planTitleHint = metaItem ? metaItem.title : kw;
  planKindHint = metaItem ? metaItem.kind : "";
  $("searchBtn").disabled = true; $("directSearchBtn").disabled = true;
  $("searchMsg").textContent = "搜索资源中（pansou 并发查多个源，可能要十几秒）…";
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
        $("pickTitle").value = planTitleHint || kw;
        if (planKindHint) {
          const radio = document.querySelector(`input[name="kind"][value="${planKindHint}"]`);
          if (radio) radio.checked = true;
        }
        $("pickBox").classList.remove("hidden");
        $("planBox").classList.add("hidden");
        $("pickBox").scrollIntoView({ behavior: "smooth" });
      };
      div.appendChild(btn);
      $("candidates").appendChild(div);
    });
  } catch (e) { $("searchMsg").textContent = "搜索失败：" + e.message; }
  $("searchBtn").disabled = false; $("directSearchBtn").disabled = false;
}

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
window._folderSel = { movie: { fid: "", name: "" }, tv: { fid: "", name: "" } };

function setFolderSel(kind, fid, name) {
  window._folderSel[kind] = { fid: fid || "", name: name || "" };
  $(kind === "movie" ? "setMovieFid" : "setTvFid").value = fid || "";
  $(kind === "movie" ? "movieFidName" : "tvFidName").textContent = name || "未选择";
}

async function loadSettings() {
  const { settings } = await api("GET", "/api/settings");
  $("setPansouBase").value = settings.pansou_base || "";
  $("setPansouUser").value = settings.pansou_username || "";
  $("setMinVideo").value = settings.min_video_mb || 30;
  $("setCheckLimit").value = settings.check_limit || 10;
  $("setCheckAlive").checked = settings.check_alive === "1";
  setFolderSel("movie", settings.movie_fid, settings.movie_name);
  setFolderSel("tv", settings.tv_fid, settings.tv_name);
  if (settings.has_tmdb_key) $("tmdbKeyMsg").textContent = "TMDB API Key 已配置（不改留空即可）。在 themoviedb.org 注册后于「设置 → API」免费申请。";
  $("verifyQuarkMsg").textContent = settings.has_quark_cookie ? `已配置 Cookie（尾号 ${settings.quark_cookie_tail}）` : "尚未配置 Cookie";
}

$("verifyQuark").onclick = async () => {
  $("verifyQuarkMsg").textContent = "验证中…";
  try {
    // 先把页面上新填的 Cookie 存进去再验
    await saveSettingsCore();
    await api("POST", "/api/verify/quark", {});
    $("verifyQuarkMsg").textContent = "Cookie 有效，点「选择…」可逐级浏览子目录";
  } catch (e) { $("verifyQuarkMsg").textContent = "验证失败：" + e.message; }
};

// ---------- 目录浏览器（支持逐级进入子文件夹） ----------
let picker = null; // {kind, stack: [{fid, name}]}

async function openPicker(kind) {
  // 新填了 Cookie 先存再浏览，避免拿旧 Cookie 读目录
  await saveSettingsCore().catch(() => {});
  picker = { kind, stack: [{ fid: "0", name: "根目录" }] };
  $("pickerTitle").textContent = kind === "movie" ? "选择电影目录" : "选择电视剧目录";
  $("folderPicker").classList.remove("hidden");
  await renderPicker();
}

async function renderPicker() {
  const crumbs = $("pickerCrumbs");
  crumbs.innerHTML = "";
  picker.stack.forEach((seg, idx) => {
    const btn = document.createElement("button");
    btn.className = "ghost";
    btn.textContent = seg.name;
    btn.onclick = async () => { picker.stack = picker.stack.slice(0, idx + 1); await renderPicker(); };
    crumbs.appendChild(btn);
    if (idx < picker.stack.length - 1) crumbs.appendChild(document.createTextNode(" / "));
  });
  const top = picker.stack[picker.stack.length - 1];
  $("pickerChoose").textContent = `选此文件夹（${top.name}）`;
  $("pickerList").innerHTML = '<p class="muted">加载中…</p>';
  $("pickerMsg").textContent = "";
  try {
    const { folders } = await api("GET", "/api/quark/folders?fid=" + encodeURIComponent(top.fid));
    if (!folders.length) {
      $("pickerList").innerHTML = '<p class="muted">（没有子文件夹，可直接选此文件夹）</p>';
      return;
    }
    $("pickerList").innerHTML = "";
    folders.forEach((f) => {
      const row = document.createElement("div");
      row.className = "picker-row";
      row.textContent = "📁 " + f.name;
      row.onclick = async () => { picker.stack.push({ fid: f.fid, name: f.name }); await renderPicker(); };
      $("pickerList").appendChild(row);
    });
  } catch (e) { $("pickerMsg").textContent = "读取目录失败：" + e.message; $("pickerList").innerHTML = ""; }
}

$("pickMovie").onclick = () => openPicker("movie");
$("pickTv").onclick = () => openPicker("tv");
$("pickerCancel").onclick = () => { $("folderPicker").classList.add("hidden"); picker = null; };
$("pickerChoose").onclick = () => {
  if (!picker) return;
  const top = picker.stack[picker.stack.length - 1];
  const path = picker.stack.map((s) => s.name).join(" / ");
  setFolderSel(picker.kind, top.fid, path);
  $("folderPicker").classList.add("hidden");
  picker = null;
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
  return api("POST", "/api/settings", {
    pansou_base: $("setPansouBase").value.trim(),
    pansou_username: $("setPansouUser").value.trim(),
    pansou_password: $("setPansouPass").value,
    tmdb_api_key: $("setTmdbKey").value.trim(),
    quark_cookie: $("setQuarkCookie").value.trim(),
    movie_fid: window._folderSel.movie.fid, tv_fid: window._folderSel.tv.fid,
    movie_name: window._folderSel.movie.name,
    tv_name: window._folderSel.tv.name,
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
