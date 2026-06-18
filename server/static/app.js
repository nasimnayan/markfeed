"use strict";

const $ = (id) => document.getElementById(id);

let pollTimer = null;
let activeJobId = null;
let batchPollTimer = null;
let batchState = null;

const MAX_BATCH_FILES = 10;
const IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"];
const isImageName = (name) => IMAGE_EXTS.some((ext) => name.toLowerCase().endsWith(ext));

// ---- element refs --------------------------------------------------------
const form = $("upload-form");
const fileInput = $("file");
const dropzone = $("dropzone");
const dzText = $("dz-text");
const selectedFilesList = $("selected-files-list");
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

const batchCard = $("batch-card");
const batchList = $("batch-list");
const batchSummary = $("batch-summary");
const batchDownloadAll = $("batch-download-all");

let pdfInfo = { page_count: null, extraction_cap: null }; // for the current file

// Build a capped FileList (DataTransfer is the standard way to construct one).
function capFileList(fileList, max) {
  if (fileList.length <= max) return fileList;
  const dt = new DataTransfer();
  for (let i = 0; i < max; i++) dt.items.add(fileList[i]);
  return dt.files;
}

// ---- file selection: dropzone label + page-range visibility --------------
fileInput.addEventListener("change", async () => {
  let files = fileInput.files;
  pdfInfo = { page_count: null, extraction_cap: null };

  if (files.length > MAX_BATCH_FILES) {
    alert(`You selected ${files.length} files — only the first ${MAX_BATCH_FILES} will be converted.`);
    files = capFileList(files, MAX_BATCH_FILES);
    fileInput.files = files;
  }

  if (files.length === 0) {
    dzText.innerHTML = "Drag &amp; drop files here or <strong>click to upload</strong> <span class=\"hint\">(up to 10 at once)</span>";
    dropzone.classList.remove("has-file");
    pagesField.style.display = "";
    $("layout-field").style.display = "";
    $("preprocess-field").style.display = "";
    $("searchable-field").style.display = "";
    hide(selectedFilesList);
    selectedFilesList.innerHTML = "";
    convertBtn.textContent = "Convert to Markdown";
    return;
  }

  dropzone.classList.add("has-file");

  if (files.length === 1) {
    const f = files[0];
    dzText.innerHTML = `Selected: <strong>${escapeHtml(f.name)}</strong>`;
    hide(selectedFilesList);
    selectedFilesList.innerHTML = "";
    convertBtn.textContent = "Convert to Markdown";

    const isPdf = f.name.toLowerCase().endsWith(".pdf");
    const isImage = isImageName(f.name);
    pagesField.style.display = isPdf ? "" : "none"; // page range only applies to PDFs
    // Layout / OCR extraction and scan enhancement apply to scanned PDFs and to
    // images (both go through OCR); they're meaningless for docx/csv/excel.
    $("layout-field").style.display = (isPdf || isImage) ? "" : "none";
    $("preprocess-field").style.display = (isPdf || isImage) ? "" : "none";
    $("searchable-field").style.display = (isPdf || isImage) ? "" : "none";

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
    return;
  }

  // batch mode: multiple files share one set of options; convert each file in full.
  dzText.innerHTML = `Selected: <strong>${files.length} files</strong>`;
  selectedFilesList.innerHTML = "";
  for (const f of files) {
    const li = document.createElement("li");
    li.textContent = f.name;
    selectedFilesList.appendChild(li);
  }
  show(selectedFilesList);
  convertBtn.textContent = `Convert ${files.length} files`;

  // page range doesn't apply across a batch — each file converts in full
  // (still subject to the per-file layout-mode page cap, applied server-side).
  pagesField.style.display = "none";
  $("layout-field").style.display = "";
  $("preprocess-field").style.display = "";
  $("searchable-field").style.display = "";
  $("layout-cap-note").classList.add("hidden");
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

// ---- presets: one-click option bundles for common tasks --------------------
const PRESETS = {
  standard: { use_layout: false, preprocess: true, make_searchable: false, gen_toc: false, dpi: "300", all_pages: true },
  research: { use_layout: true,  preprocess: true, make_searchable: true,  gen_toc: false, dpi: "300", all_pages: true },
  policy:   { use_layout: true,  preprocess: true, make_searchable: false, gen_toc: true,  dpi: "300", all_pages: true },
  meeting:  { use_layout: true,  preprocess: true, make_searchable: false, gen_toc: true,  dpi: "300", all_pages: true },
};

function applyPreset(name) {
  const p = PRESETS[name];
  if (!p) return; // "Custom" — leave the user's current choices alone
  // Premium-only options stay off on the Free plan even if the preset wants them.
  $("use_layout").checked = p.use_layout && isPremium();
  $("preprocess").checked = p.preprocess;
  $("make_searchable").checked = p.make_searchable && isPremium();
  $("gen_toc").checked = p.gen_toc;
  $("dpi").value = p.dpi;
  $("all_pages").checked = p.all_pages;
  // Fire dependent handlers so the page-range row + extraction page cap update.
  $("all_pages").dispatchEvent(new Event("change"));
  useLayoutCb.dispatchEvent(new Event("change"));
}

$("preset").addEventListener("change", () => applyPreset($("preset").value));

// ---- preset cards: drive the hidden <select>; click active = back to Custom
function syncPresetCards(value) {
  document.querySelectorAll("#preset-grid .preset-card").forEach((c) =>
    c.classList.toggle("active", value !== "" && c.dataset.preset === value)
  );
}
document.querySelectorAll("#preset-grid .preset-card").forEach((card) => {
  card.addEventListener("click", () => {
    const sel = $("preset");
    const next = sel.value === card.dataset.preset ? "" : card.dataset.preset;
    sel.value = next;
    sel.dispatchEvent(new Event("change")); // runs applyPreset
    syncPresetCards(next);
  });
});

// ---- Free / Premium plan toggle ------------------------------------------
// Display-only gating: Free hides the premium controls; Premium reveals them.
// No auth/payments — switching to Free also forces premium options off so a
// previously-set option (e.g. via a preset) can't be submitted while hidden.
let plan = "free";
function isPremium() { return plan === "premium"; }
function setPlan(next) {
  plan = next === "premium" ? "premium" : "free";
  document.body.classList.toggle("plan-premium", isPremium());
  document.body.classList.toggle("plan-free", !isPremium());
  document.querySelectorAll("#plan-toggle .plan-opt").forEach((b) =>
    b.classList.toggle("active", b.dataset.plan === plan)
  );
  if (!isPremium()) {
    let changed = false;
    if (useLayoutCb.checked) { useLayoutCb.checked = false; changed = true; }
    if ($("make_searchable").checked) $("make_searchable").checked = false;
    if (changed) useLayoutCb.dispatchEvent(new Event("change")); // reset page cap
  }
}
document.querySelectorAll("#plan-toggle .plan-opt").forEach((b) =>
  b.addEventListener("click", () => setPlan(b.dataset.plan))
);
setPlan("free"); // default plan on load

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
  if (fileInput.files.length > 1) {
    await submitBatch();
  } else {
    await submitFormData(buildFormData(false));
  }
});

function buildFormData(forceNoLayout) {
  const fd = new FormData(form);
  fd.set("use_layout", forceNoLayout ? "false" : ($("use_layout").checked ? "true" : "false"));
  // Checkboxes are absent from FormData when unchecked, so set the value explicitly.
  fd.set("preprocess", $("preprocess").checked ? "true" : "false");
  fd.set("make_searchable", $("make_searchable").checked ? "true" : "false");
  fd.set("gen_toc", $("gen_toc").checked ? "true" : "false");
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
  hide(batchCard);
  stopBatchPolling();
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

// ---- batch upload ("auto mode") -------------------------------------------
async function submitBatch() {
  const files = Array.from(fileInput.files).slice(0, MAX_BATCH_FILES);
  if (!files.length) return;

  convertBtn.disabled = true;
  stopPolling();
  hide(progressCard);
  hide(errorCard);
  hide(resultsCard);

  const batchId = `b${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  batchState = { batchId, items: [] };
  show(batchCard);
  hide(batchDownloadAll);
  batchSummary.textContent = `Uploading ${files.length} files…`;
  renderBatchPanel();

  const lang = $("lang").value;
  const dpi = $("dpi").value;
  const useLayout = useLayoutCb.checked ? "true" : "false";
  const preprocess = $("preprocess").checked ? "true" : "false";
  const makeSearchable = $("make_searchable").checked ? "true" : "false";
  const genToc = $("gen_toc").checked ? "true" : "false";
  const preset = $("preset").value;

  for (const file of files) {
    const item = { filename: file.name, jobId: null, status: "uploading", done: 0, total: 0, message: null };
    batchState.items.push(item);
    renderBatchPanel();

    const fd = new FormData();
    fd.append("file", file);
    fd.append("lang", lang);
    fd.append("dpi", dpi);
    fd.append("use_layout", useLayout);
    fd.append("preprocess", preprocess);
    fd.append("make_searchable", makeSearchable);
    fd.append("gen_toc", genToc);
    fd.append("preset", preset);
    fd.append("batch_id", batchId);

    try {
      const res = await fetch("/api/jobs", { method: "POST", body: fd });
      if (!res.ok) throw new Error((await res.text()) || `Upload failed (${res.status})`);
      const { job_id } = await res.json();
      item.jobId = job_id;
      item.status = "queued";
    } catch (err) {
      item.status = "error";
      item.message = err.message;
    }
    renderBatchPanel();
  }

  convertBtn.disabled = false;
  loadRecentJobs();
  startBatchPolling();
}

function dotClass(status) {
  return status === "uploading" ? "queued" : status;
}

function renderBatchPanel() {
  if (!batchState) return;
  batchList.innerHTML = "";
  let doneCount = 0;
  let terminalCount = 0;

  for (const item of batchState.items) {
    const li = document.createElement("li");
    li.className = "batch-item";

    const name = document.createElement("span");
    name.className = "batch-item-name";
    name.innerHTML = `<span class="r-dot ${dotClass(item.status)}"></span>${escapeHtml(item.filename)}`;
    li.appendChild(name);

    if (item.status === "error" || item.status === "crashed") {
      const err = document.createElement("span");
      err.className = "batch-item-error";
      err.title = item.message || "";
      err.textContent = item.message || "Failed";
      li.appendChild(err);
    } else if (item.status === "done") {
      const view = document.createElement("button");
      view.type = "button";
      view.className = "batch-item-view";
      view.textContent = "View";
      view.addEventListener("click", () => loadResults(item.jobId, item.filename));
      li.appendChild(view);
    } else {
      const prog = document.createElement("span");
      prog.className = "batch-item-progress";
      if (item.status === "running") {
        prog.textContent = item.total ? `Page ${item.done} of ${item.total}` : "Running…";
      } else if (item.status === "queued") {
        prog.textContent = "Queued…";
      } else {
        prog.textContent = "Uploading…";
      }
      li.appendChild(prog);
    }

    batchList.appendChild(li);
    if (item.status === "done") doneCount++;
    if (item.status === "done" || item.status === "error" || item.status === "crashed") terminalCount++;
  }

  const total = batchState.items.length;
  batchSummary.textContent = terminalCount === total
    ? `${doneCount} of ${total} converted successfully.`
    : `${terminalCount} of ${total} finished…`;

  if (terminalCount === total && doneCount > 0) {
    batchDownloadAll.href = `/api/batch/${batchState.batchId}/download`;
    show(batchDownloadAll);
  } else {
    hide(batchDownloadAll);
  }
}

function startBatchPolling() {
  stopBatchPolling();
  batchPollTimer = setInterval(pollBatch, 1500);
  pollBatch();
}

function stopBatchPolling() {
  if (batchPollTimer) clearInterval(batchPollTimer);
  batchPollTimer = null;
}

async function pollBatch() {
  if (!batchState) { stopBatchPolling(); return; }
  let allTerminal = true;

  for (const item of batchState.items) {
    if (item.status === "done" || item.status === "error" || item.status === "crashed") continue;
    if (!item.jobId) continue;
    allTerminal = false;
    try {
      const res = await fetch(`/api/jobs/${item.jobId}`);
      if (res.ok) {
        const s = await res.json();
        item.status = s.status;
        item.done = s.done;
        item.total = s.total;
        item.message = s.message;
      }
    } catch { /* keep previous status, retry next tick */ }
  }

  renderBatchPanel();
  if (allTerminal) {
    stopBatchPolling();
    loadRecentJobs();
  }
}

// ---- polling -------------------------------------------------------------
function startPolling(jobId) {
  activeJobId = jobId;
  liveFollow = true;
  cmp.live = false;
  show(progressCard);
  hide(errorCard);
  hide(resultsCard);
  hide(batchCard);
  stopBatchPolling();
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
    if (s.status === "running" && s.file_type === "pdf" && s.done > 0) {
      updateLiveCompare(jobId);
    }
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
  activeJobId = jobId;
  exitLiveMode();
  show(resultsCard);
  $("results-title").textContent = filename ? `Result — ${filename}` : "Result";

  const previewRes = await fetch(`/api/jobs/${jobId}/preview`);
  $("preview-content").innerHTML = await previewRes.text();

  const mdRes = await fetch(`/api/jobs/${jobId}/markdown`);
  $("raw-md").value = await mdRes.text();
  $("download-md").href = `/api/jobs/${jobId}/markdown`;
  $("download-zip").href = `/api/jobs/${jobId}/download`;
  $("download-zip-top").href = `/api/jobs/${jobId}/download`;
  $("download-chunks").href = `/api/jobs/${jobId}/chunks.json`;

  // Searchable PDF is optional — only show the button if this job produced one.
  const searchableUrl = `/api/jobs/${jobId}/searchable.pdf`;
  try {
    const head = await fetch(searchableUrl, { method: "HEAD" });
    if (head.ok) { $("download-searchable").href = searchableUrl; show($("searchable-card")); }
    else hide($("searchable-card"));
  } catch { hide($("searchable-card")); }

  const statsRes = await fetch(`/api/jobs/${jobId}/stats`);
  renderStats(await statsRes.json());

  await loadCompare(jobId);

  activateTab("preview");
}

// ---- compare & verify ----------------------------------------------------
let cmp = { jobId: null, pages: [], idx: 0, mode: "rendered", live: false };
let liveFollow = true; // auto-jump to the newest page until the user navigates back

// Live, during-conversion compare: poll the pages finished so far and show the
// newest one side-by-side with its original scan.
async function updateLiveCompare(jobId) {
  let data;
  try {
    data = await (await fetch(`/api/jobs/${jobId}/live`)).json();
  } catch {
    return;
  }
  const pages = data.pages || [];
  if (!pages.length) return;

  enterLiveMode();
  cmp.jobId = jobId;
  cmp.pages = pages;
  cmp.mode = cmp.mode || "rendered";
  $("cmp-total").textContent = pages.length;
  $("cmp-page-input").max = pages.length;

  if (liveFollow || cmp.idx >= pages.length) {
    showComparePage(pages.length - 1);
  }
}

function setSecondaryTabs(visible) {
  // During live conversion only the compare tab is meaningful; the full preview,
  // stats and download are only ready once the whole document finishes.
  ["preview", "stats", "download"].forEach((name) => {
    const btn = document.querySelector(`.tab[data-tab="${name}"]`);
    if (btn) btn.classList.toggle("hidden", !visible);
  });
}

function enterLiveMode() {
  if (cmp.live) return;
  cmp.live = true;
  show(resultsCard);
  $("results-title").textContent = "Converting… live preview";
  $("compare-tab-btn").classList.remove("hidden");
  $("live-banner").classList.remove("hidden");
  setSecondaryTabs(false);
  activateTab("compare");
}

function exitLiveMode() {
  cmp.live = false;
  $("live-banner").classList.add("hidden");
  setSecondaryTabs(true);
}

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

  // OCR confidence (whole-page OCR pages only): badge + highlighted view.
  const conf = data.conf;
  const confBtn = $("cmp-conf");
  const badge = $("cmp-conf-badge");
  if (conf && conf.mean != null) {
    $("cmp-confhtml").innerHTML = conf.html || "";
    confBtn.classList.remove("hidden");
    badge.textContent = `OCR ${conf.mean}%` + (conf.low ? ` · ${conf.low} low-confidence` : "");
    badge.className = "conf-badge " + (conf.mean >= 85 ? "good" : conf.mean >= 70 ? "ok" : "poor");
    badge.classList.remove("hidden");
  } else {
    confBtn.classList.add("hidden");
    badge.classList.add("hidden");
    if (cmp.mode === "conf") setCompareMode("rendered"); // page has no conf — fall back
  }
}

function setCompareMode(mode) {
  cmp.mode = mode;
  $("cmp-rendered").classList.toggle("active", mode === "rendered");
  $("cmp-raw").classList.toggle("active", mode === "raw");
  $("cmp-conf").classList.toggle("active", mode === "conf");
  $("cmp-md").classList.toggle("hidden", mode !== "rendered");
  $("cmp-rawtext").classList.toggle("hidden", mode !== "raw");
  $("cmp-confhtml").classList.toggle("hidden", mode !== "conf");
}

// In live mode, navigating to the newest page resumes auto-follow; going back
// pauses it so the page doesn't jump out from under the user mid-read.
function liveNavTo(idx) {
  if (cmp.live) liveFollow = idx >= cmp.pages.length - 1;
  showComparePage(idx);
}
$("cmp-prev").addEventListener("click", () => liveNavTo(cmp.idx - 1));
$("cmp-next").addEventListener("click", () => liveNavTo(cmp.idx + 1));
$("cmp-page-input").addEventListener("change", () => {
  const n = parseInt($("cmp-page-input").value, 10);
  if (!isNaN(n)) liveNavTo(Math.min(Math.max(1, n), cmp.pages.length) - 1);
});
$("cmp-rendered").addEventListener("click", () => setCompareMode("rendered"));
$("cmp-raw").addEventListener("click", () => setCompareMode("raw"));
$("cmp-conf").addEventListener("click", () => setCompareMode("conf"));

function renderStats(stats) {
  const cols = ["word_count", "char_count", "char_count_no_spaces", "image_count", "table_count", "formula_count"];
  const labelCol = stats.label_col || "page";
  const rows = stats.rows || [];
  const hasConf = rows.some((r) => r.mean_conf != null); // OCR pages only
  const totals = stats.totals || {};

  // ---- headline metric cards (mirrors the design's 3-up summary) ----
  const unit = labelCol === "page" ? "Pages" : "Sections";
  const confVals = rows.map((r) => r.mean_conf).filter((v) => v != null);
  const avgConf = confVals.length ? Math.round(confVals.reduce((a, b) => a + b, 0) / confVals.length) : null;
  const confClass = avgConf == null ? "" : avgConf >= 85 ? "good" : avgConf >= 70 ? "ok" : "poor";
  const metric = (ico, val, label, sub, cls = "") =>
    `<div class="metric-card"><span class="metric-ico">${ico}</span>` +
    `<div class="metric-val ${cls}">${val}</div>` +
    `<div class="metric-label">${label}</div><div class="metric-sub">${sub}</div></div>`;
  const icoDoc = "<svg viewBox='0 0 24 24'><path d='M7 3h7l5 5v13H7zM14 3v5h5' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linejoin='round'/></svg>";
  const icoBrain = "<svg viewBox='0 0 24 24'><circle cx='12' cy='12' r='3' fill='none' stroke='currentColor' stroke-width='1.6'/><path d='M12 2v3m0 14v3m10-10h-3M5 12H2' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round'/></svg>";
  const icoText = "<svg viewBox='0 0 24 24'><path d='M5 6h14M5 12h14M5 18h9' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round'/></svg>";
  let html = '<div class="metric-grid">';
  html += metric(icoDoc, rows.length, `${unit} Processed`, "Successfully converted.");
  html += metric(icoBrain, avgConf == null ? "—" : avgConf + "%", "OCR Confidence", avgConf == null ? "Not applicable (digital/text)." : "Average across pages.", confClass);
  html += metric(icoText, (totals.word_count ?? 0).toLocaleString(), "Words Extracted", "Total across the document.");
  html += "</div>";

  html += '<h3 class="section-label">Per-' + (labelCol === "page" ? "page" : "section") + ' detail</h3>';
  html += '<div class="stats-wrap"><table class="stats-table"><thead><tr>';
  html += `<th>${labelCol === "page" ? "Page" : "Section / Sheet"}</th><th>Source</th>`;
  for (const c of cols) html += `<th>${prettyCol(c)}</th>`;
  if (hasConf) html += "<th>Avg Conf</th>";
  html += "</tr></thead><tbody>";
  for (const row of rows) {
    html += "<tr>";
    html += `<td>${escapeHtml(String(row[labelCol] ?? ""))}</td>`;
    html += `<td>${escapeHtml(String(row.source ?? ""))}</td>`;
    for (const c of cols) html += `<td>${row[c] ?? 0}</td>`;
    if (hasConf) html += `<td>${row.mean_conf != null ? row.mean_conf + "%" : "—"}</td>`;
    html += "</tr>";
  }
  const t = stats.totals || {};
  html += '<tr class="total-row"><td>TOTAL</td><td></td>';
  for (const c of cols) html += `<td>${t[c] ?? 0}</td>`;
  if (hasConf) html += "<td></td>";
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
  for (const j of jobs.slice(0, 10)) {
    const li = document.createElement("li");
    li.innerHTML =
      `<button type="button" class="r-delete" title="Delete this conversion">&times;</button>` +
      `<span class="r-name"><span class="r-dot ${j.status}"></span>${escapeHtml(j.filename || j.job_id)}</span>` +
      `<span class="r-meta">${j.status} · ${(j.created_at || "").replace("T", " ")}</span>`;
    li.addEventListener("click", () => openJob(j));
    li.querySelector(".r-delete").addEventListener("click", (e) => {
      e.stopPropagation();
      deleteJob(j.job_id);
    });
    list.appendChild(li);
  }
}

async function deleteJob(jobId) {
  if (!confirm("Delete this conversion and its files? This can't be undone.")) return;
  try {
    const res = await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || "Could not delete this job.");
      return;
    }
  } catch {
    alert("Could not delete this job.");
    return;
  }
  if (activeJobId === jobId) {
    stopPolling();
    hide(progressCard); hide(resultsCard); hide(errorCard);
    activeJobId = null;
  }
  loadRecentJobs();
}

function openJob(j) {
  stopPolling();
  stopBatchPolling();
  hide(batchCard);
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
