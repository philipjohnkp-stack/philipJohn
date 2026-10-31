"use strict";
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const status = document.getElementById("status");
let currentReport = null;
let emailReady = false;
let busy = false;
let recognition = null;

function showWorking(target, text) {
  const dots = document.createElement("span");
  dots.className = "working-dots";
  dots.setAttribute("aria-hidden", "true");
  target.replaceChildren(document.createTextNode(text), dots);
  let count = 0;
  const timer = setInterval(() => {
    count = count % 7 + 1;
    dots.textContent = ".".repeat(count);
  }, 300);
  return () => clearInterval(timer);
}

function showSearching() {
  const bubble = document.createElement("article");
  bubble.className = "message assistant searching-bubble";
  bubble.setAttribute("role", "status");
  bubble.setAttribute("aria-label", "Sage is searching");
  const label = document.createElement("span");
  label.textContent = "Sage is searching";
  const dots = document.createElement("span");
  dots.className = "searching-dots";
  dots.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 3; i += 1) dots.append(document.createElement("span"));
  bubble.append(label, dots);
  document.getElementById("messages").append(bubble);
  const welcome = document.getElementById("welcome");
  const welcomeWasHidden = welcome.hidden;
  welcome.hidden = true;
  bubble.scrollIntoView({ behavior: "smooth", block: "end" });
  return () => {
    if (!bubble.isConnected) return;
    bubble.remove();
    if (!document.querySelector("#messages .message")) welcome.hidden = welcomeWasHidden;
  };
}

function showRecentChats(data) {
  const list = document.getElementById("recent-chats");
  list.replaceChildren();
  if (!data.recent_chats.length) {
    list.append(element("p", "Your conversations will appear here.", "muted"));
  }
  data.recent_chats.forEach(chat => {
    const button = element("button", chat.title, "recent-chat");
    button.title = chat.title;
    if (chat.id === data.chat_id) button.setAttribute("aria-current", "page");
    button.addEventListener("click", async () => {
      if (busy) return;
      try {
        await api("/api/chat/switch", { chat_id: chat.id });
        location.reload();
      } catch (error) { status.textContent = error.message; }
    });
    list.append(button);
  });
}

function configureVoice() {
  const voice = document.getElementById("voice-input");
  const notice = document.getElementById("voice-status");
  const timer = document.getElementById("voice-time");
  const voiceState = document.getElementById("voice-state");
  const readAloud = document.getElementById("read-aloud");
  const readAloudState = document.getElementById("read-aloud-state");
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!("speechSynthesis" in window)) {
    readAloud.disabled = true;
    readAloud.checked = false;
    readAloud.parentElement.title = "Speech playback is not supported in this browser.";
  }
  readAloudState.textContent = readAloud.checked ? "ON" : "OFF";
  readAloud.addEventListener("change", () => {
    readAloudState.textContent = readAloud.checked ? "ON" : "OFF";
    if (!readAloud.checked && "speechSynthesis" in window) window.speechSynthesis.cancel();
  });
  if (!Recognition) {
    voice.disabled = true;
    notice.textContent = "Voice input is not supported in this browser.";
    return;
  }
  recognition = new Recognition();
  recognition.lang = "en-US";
  recognition.interimResults = true;
  recognition.continuous = false;
  let active = false;
  let interval;
  let prefix = "";
  function setRecording(recording) {
    active = recording;
    voice.disabled = false;
    voice.classList.toggle("recording", recording);
    voice.setAttribute("aria-pressed", String(recording));
    voice.setAttribute("aria-label", recording ? "Stop voice input" : "Start voice input");
    voiceState.textContent = recording ? "ON" : "OFF";
    if (!recording) clearInterval(interval);
  }
  voice.addEventListener("click", () => {
    if (active) { recognition.stop(); return; }
    if (busy) { notice.textContent = "Wait for the current answer before recording."; return; }
    prefix = document.getElementById("question").value.trim();
    notice.textContent = "Your browser may use an online speech recognition service.";
    voice.disabled = true;
    try { recognition.start(); }
    catch (error) {
      setRecording(false);
      notice.textContent = "Voice input could not start. Please try again.";
      console.error("Voice input could not start:", error.name);
    }
  });
  recognition.onstart = () => {
    setRecording(true);
    timer.textContent = "00:00";
    const started = Date.now();
    interval = setInterval(() => {
      const seconds = Math.floor((Date.now() - started) / 1000);
      timer.textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
    }, 1000);
  };
  recognition.onresult = event => {
    const transcript = Array.from(event.results).map(result => result[0].transcript).join(" ");
    document.getElementById("question").value = (prefix ? prefix + " " : "") + transcript;
  };
  recognition.onerror = event => {
    setRecording(false);
    notice.textContent = event.error === "not-allowed" ? "Microphone access was not allowed. You can still type your question." : "Voice input stopped. Please try again or type your question.";
  };
  recognition.onend = () => {
    setRecording(false);
    if (!notice.textContent.includes("stopped") && !notice.textContent.includes("not allowed")) {
      notice.textContent = "Review your question, then select Run.";
    }
  };
  window.addEventListener("pagehide", () => {
    recognition.abort();
    setRecording(false);
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  });
}

async function api(path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  const response = await fetch(path, {
    signal: controller.signal,
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : body instanceof FormData
      ? { "X-CSRF-Token": csrf } : { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body)
  }).catch(error => {
    throw new Error(error.name === "AbortError" ? "The server took too long to respond. Please try again." : "Could not reach the server. Please try again.");
  }).finally(() => clearTimeout(timer));
  if (!response.headers.get("content-type")?.includes("application/json")) {
    throw new Error("The server could not complete the request. Please try again.");
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The request could not be completed.");
  return data;
}

async function configurePrivateWorkspace(data) {
  const selector = document.getElementById("private-source");
  if (!selector) return;
  const notice = document.getElementById("workbook-status");
  const form = document.getElementById("workbook-upload");
  const remove = document.getElementById("delete-workbook");
  const sources = await api("/api/sources");
  selector.replaceChildren();
  sources.sources.forEach(source => {
    const option = element("option", source.label);
    option.value = source.id;
    selector.append(option);
  });
  selector.value = data.source === "none" ? "general" : data.source;
  if (!selector.value) selector.value = "general";
  selector.disabled = false;
  remove.disabled = !selector.value.startsWith("upload:");
  document.getElementById("database-status").textContent = sources.database_enabled
    ? (data.local_mode
      ? "Local MySQL socket configured. Read-only permissions and database scope are checked before use."
      : "Database configured. Read-only permissions and TLS are checked before use.")
    : "Database not enabled. General / SQL help explains questions without executing queries. Upload a workbook for Excel calculations.";

  async function changeSource(source) {
    await api("/api/new", { source });
    location.reload();
  }
  selector.addEventListener("change", async () => {
    if (busy) {
      selector.value = data.source;
      notice.textContent = "Wait for the current operation before changing sources.";
      return;
    }
    busy = true;
    selector.disabled = true;
    try { await changeSource(selector.value); }
    catch (error) {
      notice.textContent = error.message;
      selector.value = data.source;
      selector.disabled = false;
      busy = false;
    }
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy) return;
    const file = document.getElementById("workbook-file").files[0];
    if (!file || file.size > 20 * 1024 * 1024 || !file.name.toLowerCase().endsWith(".xlsx")) {
      notice.textContent = "Choose one .xlsx workbook of at most 20 MB.";
      return;
    }
    busy = true;
    form.querySelector("button").disabled = selector.disabled = true;
    notice.textContent = "Validating and uploading workbook...";
    try {
      const body = new FormData();
      body.append("file", file);
      const result = await api("/api/uploads", body);
      await changeSource(result.sources[0].id);
    } catch (error) {
      notice.textContent = error.message;
      busy = false;
      form.querySelector("button").disabled = selector.disabled = false;
    }
  });
  remove.addEventListener("click", async () => {
    if (busy || !selector.value.startsWith("upload:")) return;
    if (!confirm("Delete this workbook, all its worksheets, and saved analyses? This cannot be undone.")) return;
    busy = true;
    remove.disabled = true;
    try {
      await api("/api/uploads/delete", { source: selector.value, confirm: true });
      location.reload();
    } catch (error) {
      notice.textContent = error.message;
      busy = false;
      remove.disabled = false;
    }
  });
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function section(card, title, values) {
  if (!values.length) return;
  card.append(element("h3", title));
  const list = element("ul");
  values.forEach(value => list.append(element("li", value)));
  card.append(list);
}

function updateMode() {
  const analysis = document.querySelector('input[name="mode"]:checked').value === "analysis";
  document.getElementById("messages").hidden = false;
  document.getElementById("executive-dashboard").hidden = !analysis;
  document.getElementById("welcome").hidden = analysis || document.getElementById("messages").children.length > 0;
}

async function preview(id) {
  status.textContent = "";
  const snapshot = await api(`/api/reports/${id}`);
  const report = snapshot.document;
  await api(`/api/reports/${id}/preview`, {});
  currentReport = id;
  const selector = document.getElementById("pdf-chart");
  selector.value = "none";
  Array.from(selector.options).forEach(option => { option.disabled = option.value !== "none" && !report.chart; });
  document.getElementById("chart-status").textContent = report.chart ? "Choose a chart to include in your PDF." : "Charts need at least two comparable numeric values.";
  document.getElementById("recipient-email").value = "";
  const paper = document.getElementById("report-preview");
  paper.replaceChildren();
  paper.append(element("h2", report.title.toUpperCase()), element("p", report.created_at.slice(0, 10), "muted"),
    element("p", report.question), element("p", report.summary));
  section(paper, "Findings", report.findings);
  section(paper, "Suggested business actions", report.actions);
  section(paper, "Limitations", report.limitations);
  if (report.chart) {
    const chart = element("img");
    chart.id = "pdf-chart-preview";
    chart.hidden = true;
    chart.alt = report.chart.title; chart.className = "chart";
    paper.append(chart);
  }
  document.getElementById("download-report").href = `/api/reports/${id}/pdf?download=1&chart=none`;
  const excelDownload = document.getElementById("download-excel");
  excelDownload.hidden = !report.excel;
  if (report.excel) excelDownload.href = `/api/reports/${id}/xlsx`;
  else excelDownload.removeAttribute("href");
  const send = document.getElementById("email-report");
  if (send) send.disabled = !emailReady || ["sent", "sending", "unknown"].includes(snapshot.mail_status);
  document.getElementById("mail-status").textContent = !emailReady
    ? "Email delivery is unavailable. Please contact the site owner or download the PDF."
    : { sent: "This report has already been sent.", sending: "This report is being sent.", unknown: "Delivery could not be confirmed. Check your inbox before contacting the site owner." }[snapshot.mail_status] || "";
  document.getElementById("report-modal").showModal();
}

let pendingSnip = null;
let snipText = "";
let snipVersion = 0;
let readingSnip = false;

function clearSnip() {
  snipVersion += 1;
  pendingSnip = null;
  snipText = "";
  readingSnip = false;
  const box = document.getElementById("snip-preview");
  if (!box) return;
  box.replaceChildren();
  box.hidden = true;
}

// Thumbnail that opens full size in a new tab so text in the snip stays readable.
function snipImage(src) {
  const link = document.createElement("a");
  link.href = src;
  link.target = "_blank";
  link.rel = "noopener";
  link.title = "Click to view full size";
  const img = document.createElement("img");
  img.src = src;
  img.alt = "Pasted snip";
  img.className = "snip-thumb";
  link.append(img);
  return link;
}

async function renderMessage(message) {
  const card = element("article", undefined, `message ${message.role}`);
  card.append(element("p", message.content, "message-text"));
  document.getElementById("messages").append(card);
  document.getElementById("welcome").hidden = true;
  if (message.report_id) {
    const { document: report } = await api(`/api/reports/${message.report_id}`);
    if (report.processing) card.append(element("p", report.processing, "muted"));
    const detailed = report.display_mode === "analysis" || report.display_mode === undefined;
    if (detailed) {
      section(card, "Key findings", report.findings);
      section(card, "Business actions", report.actions);
    }
    const details = element("details");
    details.append(element("summary", "Limitations"));
    section(details, "Scope", report.limitations);
    if (report.limitations.length) card.append(details);
    const button = element("button", undefined, "report-button pdf-icon");
    button.title = "PDF options: download, charts, and email";
    button.setAttribute("aria-label", "PDF options: download, charts, and email");
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("viewBox", "0 0 24 24");
    icon.setAttribute("width", "22");
    icon.setAttribute("height", "22");
    icon.setAttribute("aria-hidden", "true");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M6 2h8l4 4v16H6z M14 2v5h4 M9 12h6 M9 16h6");
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "1.7");
    icon.append(path);
    button.append(icon);
    button.addEventListener("click", () => preview(message.report_id).catch(error => { status.textContent = error.message; }));
    card.append(button);
    const email = button.cloneNode(true);
    email.classList.add("email-icon");
    email.title = "Email PDF";
    email.setAttribute("aria-label", "Email PDF");
    email.querySelector("path").setAttribute("d", "M3 5h18v14H3z M3 5l9 7 9-7");
    const openEmail = () => preview(message.report_id)
      .then(() => document.getElementById("recipient-email").focus())
      .catch(error => { status.textContent = error.message; });
    email.addEventListener("click", openEmail);
    card.append(email);
    if (report.display_mode === "analysis") {
      const dashboard = element("article", undefined, "executive-report");
      dashboard.append(element("p", "EXECUTIVE DASHBOARD", "eyebrow"), element("h2", report.title.toUpperCase()),
        element("p", report.question, "muted"), element("p", report.summary, "message-text"));
      if (report.chart) {
        const chart = element("img");
        chart.src = `/api/reports/${message.report_id}/chart.svg`;
        chart.alt = report.chart.title;
        chart.className = "chart";
        dashboard.append(chart);
      }
      section(dashboard, "Key findings", report.findings);
      section(dashboard, "Suggested actions", report.actions);
      if (report.limitations.length) dashboard.append(details.cloneNode(true));
      const pdf = button.cloneNode(true);
      pdf.addEventListener("click", () => preview(message.report_id).catch(error => { status.textContent = error.message; }));
      dashboard.append(pdf);
      const dashboardEmail = email.cloneNode(true);
      dashboardEmail.addEventListener("click", openEmail);
      dashboard.append(dashboardEmail);
      document.getElementById("executive-dashboard").replaceChildren(dashboard);
    }
  }
  updateMode();
}

const ownerForm = document.getElementById("owner-form");
if (ownerForm) {
  ownerForm.addEventListener("submit", async event => {
    event.preventDefault();
    const input = document.getElementById("owner-password");
    try {
      await api("/api/owner/login", { password: input.value });
      location.assign("/");
    } catch (error) {
      status.textContent = error.message;
    } finally {
      input.value = "";
    }
  });
} else {
  configureVoice();
  const externalAI = document.getElementById("allow-external-ai");
  const clearHistory = document.getElementById("clear-history");
  const historyModal = document.getElementById("history-modal");
  const confirmClear = document.getElementById("confirm-clear-history");
  const cancelClear = document.getElementById("cancel-clear-history");
  const historyStatus = document.getElementById("history-status");
  clearHistory.addEventListener("click", () => {
    if (busy) return;
    historyStatus.textContent = "";
    historyModal.showModal();
  });
  cancelClear.addEventListener("click", () => historyModal.close());
  historyModal.addEventListener("cancel", event => {
    if (busy) event.preventDefault();
  });
  confirmClear.addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    clearHistory.disabled = confirmClear.disabled = cancelClear.disabled = true;
    document.getElementById("submit").disabled = document.getElementById("new-chat").disabled = true;
    if (recognition) recognition.abort();
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    historyStatus.textContent = "Deleting session history...";
    try {
      await api("/api/history/clear", { confirm: true });
      location.reload();
    } catch (error) {
      historyStatus.textContent = error.message;
      busy = false;
      clearHistory.disabled = confirmClear.disabled = cancelClear.disabled = false;
      document.getElementById("submit").disabled = document.getElementById("new-chat").disabled = false;
    }
  });
  document.querySelectorAll('input[name="mode"]').forEach(input => input.addEventListener("change", updateMode));
  document.getElementById("sidebar-toggle").addEventListener("click", event => {
    const collapsed = document.body.classList.toggle("sidebar-collapsed");
    event.currentTarget.setAttribute("aria-expanded", String(!collapsed));
    event.currentTarget.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
    event.currentTarget.textContent = collapsed ? "\u203a" : "\u2039";
  });
  api("/api/state").then(async data => {
    const excelSource = data.source.startsWith("excel:") || data.source.startsWith("upload:");
    const externalAIOption = document.getElementById("external-ai-option");
    if (externalAIOption) externalAIOption.hidden = !excelSource && !data.private_mode;
    if (externalAI) externalAI.checked = false;
    const disclosure = document.getElementById("ai-disclosure");
    if (disclosure) {
      disclosure.hidden = !data.private_mode && !excelSource;
      disclosure.textContent = data.private_mode
        ? "Simple Excel calculations run locally in this Azure app. If you allow Azure OpenAI, your question, recent conversation, source structure, and query results may be sent for processing. Use only data approved for this service; masking does not guarantee anonymization. Permission applies to this question only."
        : excelSource
        ? "Excel answers supported simple counts and totals locally. More complex questions use Azure OpenAI only if you allow it for that question. The original workbook is not uploaded."
        : "";
    }
    emailReady = data.email_ready;
    showRecentChats(data);
    for (const message of data.messages) await renderMessage(message);
    if (data.private_mode) await configurePrivateWorkspace(data);
  }).catch(error => { status.textContent = error.message; }).finally(() => { clearHistory.disabled = busy; });
  document.getElementById("question-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (busy) return;
    const input = document.getElementById("question");
    const typed = input.value.trim();
    if (readingSnip) {
      status.textContent = "Wait for the snip to finish reading, or remove it before sending.";
      return;
    }
    if (pendingSnip && !snipText) {
      status.textContent = "The snip could not be read. Paste the original text, try a clearer image, or remove the snip.";
      return;
    }
    if (!typed && !snipText) {
      status.textContent = "Enter or paste a question before selecting Run.";
      return;
    }
    const question = snipText
      ? `${typed || "Explain this snip."}\n\nText from snip:\n${snipText}`.slice(0, 4000)
      : typed;
    busy = true;
    const snip = pendingSnip;
    if (recognition) recognition.abort();
    document.getElementById("submit").disabled = true;
    document.getElementById("new-chat").disabled = true;
    clearHistory.disabled = true;
    if (externalAI) externalAI.disabled = true;
    input.value = "";
    const stopWorking = showWorking(status, "Working on your question");
    const stopSearching = showSearching();
    let submitted = false;
    try {
      const result = await api("/api/chat", {
        question, mode: document.querySelector('input[name="mode"]:checked').value,
        allow_external_ai: externalAI?.checked || false
      });
      stopSearching();
      submitted = true;
      clearSnip();
      await renderMessage({ role: "user", content: result.question });
      if (snip) document.querySelector("#messages .message.user:last-of-type")?.append(snipImage(snip));
      await renderMessage(result.message);
      showRecentChats(await api("/api/state"));
      if (document.getElementById("read-aloud").checked && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        const speech = new SpeechSynthesisUtterance(result.message.content);
        speech.lang = "en-US";
        speech.onerror = event => {
          if (event.error !== "canceled" && event.error !== "interrupted") {
            document.getElementById("voice-status").textContent = "Speech playback failed. You can still read the answer on screen.";
          }
        };
        window.speechSynthesis.speak(speech);
      }
      status.textContent = "";
      document.getElementById("question-form").scrollIntoView({ behavior: "smooth", block: "end" });
    } catch (error) {
      if (!submitted && !input.value) input.value = snip ? typed : question;
      status.textContent = error.message;
    } finally {
      stopSearching();
      stopWorking();
      if (externalAI) {
        externalAI.checked = false;
        externalAI.disabled = false;
      }
      busy = false;
      document.getElementById("submit").disabled = false;
      document.getElementById("new-chat").disabled = false;
      clearHistory.disabled = false;
      input.focus();
    }
  });
  const snipPreview = document.getElementById("snip-preview");
  document.getElementById("question").addEventListener("paste", event => {
    if (busy) {
      event.preventDefault();
      status.textContent = "Wait for the current answer before pasting another question.";
      return;
    }
    if (event.clipboardData?.getData("text/plain").trim()) {
      clearSnip();
      status.textContent = "";
      return;
    }
    const file = [...(event.clipboardData?.files || [])].find(f => f.type.startsWith("image/"));
    if (!file) return;
    event.preventDefault();
    if (!snipPreview) {
      status.textContent = "Reload the chat page before pasting a snip.";
      return;
    }
    if (file.type !== "image/png") { status.textContent = "Please paste a PNG snip."; return; }
    if (file.size > 2 * 1024 * 1024) { status.textContent = "Snip is too large (max 2 MB)."; return; }
    clearSnip();
    const version = snipVersion;
    readingSnip = true;
    status.textContent = "Reading text in snip...";
    const reader = new FileReader();
    reader.onerror = () => {
      if (snipVersion !== version) return;
      readingSnip = false;
      status.textContent = "The pasted image could not be loaded. Please paste it again.";
    };
    reader.onload = () => {
      if (snipVersion !== version) return;
      pendingSnip = reader.result;
      snipPreview.replaceChildren(snipImage(pendingSnip), element("button", "Remove", "snip-remove"));
      snipPreview.querySelector("button").type = "button";
      snipPreview.querySelector("button").addEventListener("click", () => {
        clearSnip();
        status.textContent = "";
      });
      snipPreview.hidden = false;
      const current = pendingSnip;
      status.textContent = "Reading text in snip...";
      api("/api/ocr", { image: current }).then(result => {
        if (snipVersion !== version) return;
        snipText = result.text.trim();
        status.textContent = snipText ? "Snip text ready; it will be sent with your question." : "No readable text found. Paste the original text or try a larger, clearer image.";
      }).catch(error => {
        if (snipVersion === version) status.textContent = error.message;
      }).finally(() => {
        if (snipVersion === version) readingSnip = false;
      });
    };
    reader.readAsDataURL(file);
  });
  document.getElementById("question").addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      document.getElementById("question-form").requestSubmit();
    }
  });
  document.getElementById("new-chat").addEventListener("click", async () => {
    if (busy) return;
    try { await api("/api/new", {}); location.reload(); }
    catch (error) { status.textContent = error.message; }
  });
  document.getElementById("close-report").addEventListener("click", () => document.getElementById("report-modal").close());
  document.getElementById("pdf-chart").addEventListener("change", event => {
    const kind = event.target.value;
    document.getElementById("download-report").href = `/api/reports/${currentReport}/pdf?download=1&chart=${kind}`;
    const chart = document.getElementById("pdf-chart-preview");
    if (chart) {
      chart.hidden = kind === "none";
      if (kind !== "none") chart.src = `/api/reports/${currentReport}/chart.svg?chart=${kind}`;
    }
  });
  document.getElementById("client-email-form").addEventListener("submit", async event => {
    event.preventDefault();
    const input = document.getElementById("recipient-email");
    const recipient = input.value.trim();
    if (!input.reportValidity()) return;
    if (/[\r\n]/.test(recipient) || !/^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+$/.test(recipient)) {
      document.getElementById("mail-status").textContent = "Enter one valid recipient email address.";
      return;
    }
    const send = document.getElementById("email-report");
    if (send) {
      send.disabled = true;
      const notice = document.getElementById("mail-status");
      notice.textContent = "Sending PDF attachment...";
      try {
        const result = await api(`/api/reports/${currentReport}/email`, {
          recipient, chart: document.getElementById("pdf-chart").value
        });
        notice.textContent = result.message;
      } catch (error) {
        notice.textContent = error.message;
        try {
          const snapshot = await api(`/api/reports/${currentReport}`);
          send.disabled = !emailReady || ["sent", "sending", "unknown"].includes(snapshot.mail_status);
        } catch (refreshError) {
          notice.textContent += ` ${refreshError.message} Reopen PDF options before retrying.`;
        }
      }
      return;
    }
  });
}
