"use strict";

const $ = (id) => document.getElementById(id);

let pollTimer = null;

// ---- element refs --------------------------------------------------------
const form = $("upload-form");
const fileInput = $("file");
const dropzone = $("dropzone");
const dzText = $("dz-text");
const pagesField = $("pages-field");
const pageRangeRow = $("page-range-row");
const allPagesCb = $("all_pages");
const convertBtn = $("convert-btn");

const progressCard = $("progress-card");
const progressFilename = $("progress-filename");
const progressStatus = $("progress-status");
const progressFill = $("progress-fill");
const progressText = $("progress-text");

const errorCard = $("error-card");
const errorMessage = $("error-message");
const retryBtn = $("retry-btn");

const resultsCard = $("results-card");
const useLayoutCb = $("use_layout");

let pdfInfo = { page_count: null, extraction_cap: null }; // for the current file

// ---- file selection: dropzone label + page-range visibility --------------
fileInput.addEventListener("change", async () => {
  const f = fileInput.files[0];
  pdfInfo = { page_count: null, extraction_cap: null };
  if (!f) {
    dzText.innerHTML = "Click to choose a <strong>.pdf</strong> or <strong>.docx</strong> file";
    dropzone.classList.remove("has-file");
    pagesField.style.display = "";
    $("layout-field").style.display = "";
    return;
  }
  dzText.innerHTML = `Selected: <strong>${escapeHtml(f.name)}</strong>`;
  dropzone.classList.add("has-file");
  const isPdf = f.name.toLowerCase().endsWith(".pdf");
  pagesField.style.display = isPdf ? "" : "none"; // page range only applies to PDFs
  $("layout-field").style.display = isPdf ? "" : "none"; // extraction is PDF-only

  if (isPdf) {
    try {
      const fd = new FormData();
      fd.append("file", f);
      pdfInfo = await (await fetch("/api/pdf-info", { method: "POST", body: fd })).json();
    } catch {
      pdfInfo = { page_count: null, extraction_cap: null };
    }
  }
  applyLayoutCap();
});

// ---- extraction-mode page cap -------------------------------------------
function applyLayoutCap() {
  const on = useLayoutCb.checked;
  const note = $("layout-cap-note");
  const cap = pdfInfo.extraction_cap;
  const total = pdfInfo.page_count;

  if (on && cap != null) {
    // Force a bounded range: uncheck "all pages", reveal range, clamp inputs.
    if (allPagesCb.checked) {
      allPagesCb.checked = false;
      allPagesCb.dispatchEvent(new Event("change"));
    }
    allPagesCb.disabled = true;
    if (!$("start_page").value) $("start_page").value = 1;
    const start = parseInt($("start_page").value, 10) || 1;
    const maxEnd = Math.min(total, start + cap - 1);
    $("end_page").max = maxEnd;
    $("start_page").max = total;
    if (!$("end_page").value || parseInt($("end_page").value, 10) > maxEnd) {
      $("end_page").value = maxEnd;
    }
    note.textContent = `Diagram + table mode converts up to ${cap} pages per run (this PDF has ${total}). Do a long book in ${cap}-page chunks.`;
    note.classList.remove("hidden");
  } else {
    allPagesCb.disabled = false;
    note.classList.add("hidden");
  }
}

useLayoutCb.addEventListener("change", applyLayoutCap);
$("start_page").addEventListener("change", () => { if (useLayoutCb.checked) applyLayoutCap(); });

// drag & drop onto the dropzone
["dragover", "dragenter"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("has-file"); })
);
dropzone.addEventListener("dragleave", () => {
  if (!fileInput.files[0]) dropzone.classList.remove("has-file");
});
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  if (e.dataTransfer.files.length) {
    fileInput.files = e.dataTransfer.files;
    fileInput.dispatchEvent(new Event("change"));
  }
});

// ---- all-pages toggle ----------------------------------------------------
allPagesCb.addEventListener("change", () => {
  pageRangeRow.classList.toggle("hidden", allPagesCb.checked);
  $("all-pages-help").textContent = allPagesCb.checked
    ? "All pages will be converted. Uncheck to pick a page range (useful to test a few pages of a long book first)."
    : "Choose the range of pages to convert.";
});

// ---- submit --------------------------------------------------------------
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  await submitFormData(buildFormData(false));
});

function buildFormData(forceNoLayout) {
  const fd = new FormData(form);
  fd.set("use_layout", forceNoLayout ? "false" : ($("use_layout").checked ? "true" : "false"));
  // all-pages => omit range so backend converts everything
  if (allPagesCb.checked || !$("start_page").value) fd.delete("start_page");
  if (allPagesCb.checked || !$("end_page").value) fd.delete("end_page");
  fd.delete("all_pages");
  return fd;
}

async function submitFormData(fd) {
  if (!fileInput.files[0]) return;
  convertBtn.disabled = true;
  hide(errorCard);
  hide(resultsCard);
  try {
    const res = await fetch("/api/jobs", { method: "POST", body: fd });
    if (!res.ok) throw new Error((await res.text()) || `Upload failed (${res.status})`);
    const { job_id } = await res.json();
    startPolling(job_id);
    loadRecentJobs();
  } catch (err) {
    showError(err.message, false);
  } finally {
    convertBtn.disabled = false;
  }
}

// ---- polling -------------------------------------------------------------
function startPolling(jobId) {
  show(progressCard);
  hide(errorCard);
  hide(resultsCard);
  progressFill.style.width = "0%";
  progressText.textContent = "Queued…";
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => pollStatus(jobId), 1500);
  pollStatus(jobId);
}

async function pollStatus(jobId) {
  let s;
  try {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) return;
    s = await res.json();
  } catch { return; }

  progressFilename.textContent = s.filename || "";
  progressStatus.textContent = s.status;

  if (s.status === "running" || s.status === "queued") {
    const pct = s.total ? Math.round((s.done / s.total) * 100) : 0;
    progressFill.style.width = pct + "%";
    progressText.textContent = s.status === "queued"
      ? "Waiting for an earlier job to finish…"
      : `Page ${s.done} of ${s.total}  ·  ${pct}%`;
  } else if (s.status === "done") {
    stopPolling();
    progressFill.style.width = "100%";
    hide(progressCard);
    loadResults(jobId, s.filename);
    loadRecentJobs();
  } else if (s.status === "error" || s.status === "crashed") {
    stopPolling();
    hide(progressCard);
    showError(s.message || "Conversion failed.", s.suggest_retry_without_layout);
    loadRecentJobs();
  }
}

function stopPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer = null; }

// ---- error / retry -------------------------------------------------------
function showError(message, canRetry) {
  errorMessage.textContent = message;
  canRetry ? show(retryBtn) : hide(retryBtn);
  show(errorCard);
}

retryBtn.addEventListener("click", async () => {
  if (!fileInput.files[0]) {
    showError("Please re-select the file and convert again with layout off.", false);
    return;
  }
  $("use_layout").checked = false;
  await submitFormData(buildFormData(true));
});

// ---- results -------------------------------------------------------------
async function loadResults(jobId, filename) {
  show(resultsCard);
  $("results-title").textContent = filename ? `Result — ${filename}` : "Result";

  const previewRes = await fetch(`/api/jobs/${jobId}/preview`);
  $("preview-content").innerHTML = await previewRes.text();

  const mdRes = await fetch(`/api/jobs/${jobId}/markdown`);
  $("raw-md").value = await mdRes.text();
  $("download-md").href = `/api/jobs/${jobId}/markdown`;
  $("download-zip").href = `/api/jobs/${jobId}/download`;
  $("download-zip-top").href = `/api/jobs/${jobId}/download`;

  const statsRes = await fetch(`/api/jobs/${jobId}/stats`);
  renderStats(await statsRes.json());

  await loadCompare(jobId);

  activateTab("preview");
}

// ---- compare & verify ----------------------------------------------------
let cmp = { jobId: null, pages: [], idx: 0, mode: "rendered" };

async function loadCompare(jobId) {
  cmp = { jobId, pages: [], idx: 0, mode: cmp.mode || "rendered" };
  let data;
  try {
    data = await (await fetch(`/api/jobs/${jobId}/compare`)).json();
  } catch {
    data = { pages: [] };
  }
  cmp.pages = data.pages || [];
  const hasCompare = cmp.pages.length > 0;
  $("compare-tab-btn").classList.toggle("hidden", !hasCompare);
  if (!hasCompare) return;

  $("cmp-total").textContent = cmp.pages.length;
  $("cmp-page-input").max = cmp.pages.length;
  showComparePage(0);
}

async function showComparePage(idx) {
  if (idx < 0 || idx >= cmp.pages.length) return;
  cmp.idx = idx;
  const p = cmp.pages[idx];

  $("cmp-page-input").value = idx + 1;
  $("cmp-prev").disabled = idx === 0;
  $("cmp-next").disabled = idx === cmp.pages.length - 1;

  // original page image
  $("cmp-img").src = `/api/jobs/${cmp.jobId}/previews/${p.preview}`;

  // converted side
  let data;
  try {
    data = await (await fetch(`/api/jobs/${cmp.jobId}/page/${p.page}`)).json();
  } catch {
    data = { html: "", raw: "" };
  }
  $("cmp-md").innerHTML = data.html || "<em class='muted'>No text detected on this page.</em>";
  $("cmp-rawtext").textContent = data.raw || "";
}

function setCompareMode(mode) {
  cmp.mode = mode;
  $("cmp-rendered").classList.toggle("active", mode === "rendered");
  $("cmp-raw").classList.toggle("active", mode === "raw");
  $("cmp-md").classList.toggle("hidden", mode !== "rendered");
  $("cmp-rawtext").classList.toggle("hidden", mode !== "raw");
}

$("cmp-prev").addEventListener("click", () => showComparePage(cmp.idx - 1));
$("cmp-next").addEventListener("click", () => showComparePage(cmp.idx + 1));
$("cmp-page-input").addEventListener("change", () => {
  const n = parseInt($("cmp-page-input").value, 10);
  if (!isNaN(n)) showComparePage(Math.min(Math.max(1, n), cmp.pages.length) - 1);
});
$("cmp-rendered").addEventListener("click", () => setCompareMode("rendered"));
$("cmp-raw").addEventListener("click", () => setCompareMode("raw"));

function renderStats(stats) {
  const cols = ["word_count", "char_count", "char_count_no_spaces", "image_count", "table_count", "formula_count"];
  const labelCol = stats.label_col || "page";
  const rows = stats.rows || [];

  let html = '<div class="stats-wrap"><table class="stats-table"><thead><tr>';
  html += `<th>${labelCol === "page" ? "Page" : "Section"}</th><th>Source</th>`;
  for (const c of cols) html += `<th>${prettyCol(c)}</th>`;
  html += "</tr></thead><tbody>";
  for (const row of rows) {
    html += "<tr>";
    html += `<td>${escapeHtml(String(row[labelCol] ?? ""))}</td>`;
    html += `<td>${escapeHtml(String(row.source ?? ""))}</td>`;
    for (const c of cols) html += `<td>${row[c] ?? 0}</td>`;
    html += "</tr>";
  }
  const t = stats.totals || {};
  html += '<tr class="total-row"><td>TOTAL</td><td></td>';
  for (const c of cols) html += `<td>${t[c] ?? 0}</td>`;
  html += "</tr></tbody></table></div>";
  $("stats-content").innerHTML = html;
}

function prettyCol(c) { return c.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase()); }
function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

// ---- tabs ----------------------------------------------------------------
document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => activateTab(tab.dataset.tab))
);
function activateTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
}

// ---- recent jobs ---------------------------------------------------------
async function loadRecentJobs() {
  let jobs;
  try { jobs = await (await fetch("/api/jobs")).json(); } catch { return; }
  const list = $("recent-list");
  list.innerHTML = "";
  $("recent-empty").style.display = jobs.length ? "none" : "";
  for (const j of jobs.slice(0, 40)) {
    const li = document.createElement("li");
    li.innerHTML =
      `<span class="r-name"><span class="r-dot ${j.status}"></span>${escapeHtml(j.filename || j.job_id)}</span>` +
      `<span class="r-meta">${j.status} · ${(j.created_at || "").replace("T", " ")}</span>`;
    li.addEventListener("click", () => openJob(j));
    list.appendChild(li);
  }
}

function openJob(j) {
  stopPolling();
  document.querySelectorAll(".recent-list li").forEach((li) => li.classList.remove("active"));
  if (j.status === "done") {
    hide(progressCard); hide(errorCard);
    loadResults(j.job_id, j.filename);
  } else if (j.status === "error" || j.status === "crashed") {
    hide(progressCard); hide(resultsCard);
    showError(j.message || "Conversion failed.", j.suggest_retry_without_layout);
  } else {
    startPolling(j.job_id);
  }
}

// ---- helpers -------------------------------------------------------------
function show(el) { el.classList.remove("hidden"); }
function hide(el) { el.classList.add("hidden"); }

loadRecentJobs();
