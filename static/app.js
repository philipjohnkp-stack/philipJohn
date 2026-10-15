"use strict";
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const status = document.getElementById("status");
let currentReport = null;
let emailReady = false;
let busy = false;
let catalog = {};
let selectedTable = null;
let tableRequest = 0;
let tablePage = 0;
let recognition = null;

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
  const readAloud = document.getElementById("read-aloud");
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!("speechSynthesis" in window)) {
    readAloud.disabled = true;
    readAloud.parentElement.title = "Speech playback is not supported in this browser.";
  }
  readAloud.addEventListener("change", () => {
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
  voice.addEventListener("click", () => {
    if (active) { recognition.stop(); return; }
    if (busy) { notice.textContent = "Wait for the current answer before recording."; return; }
    prefix = document.getElementById("question").value.trim();
    notice.textContent = "Your browser may use an online speech recognition service.";
    voice.disabled = true;
    try { recognition.start(); }
    catch (error) {
      voice.disabled = false;
      notice.textContent = "Voice input could not start. Please try again.";
      console.error("Voice input could not start:", error.name);
    }
  });
  recognition.onstart = () => {
    active = true;
    voice.disabled = false;
    voice.classList.add("recording");
    voice.setAttribute("aria-label", "Stop voice input");
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
    notice.textContent = event.error === "not-allowed" ? "Microphone access was not allowed. You can still type your question." : "Voice input stopped. Please try again or type your question.";
  };
  recognition.onend = () => {
    active = false;
    voice.disabled = false;
    clearInterval(interval);
    voice.classList.remove("recording");
    voice.setAttribute("aria-label", "Start voice input");
    if (!notice.textContent.includes("stopped") && !notice.textContent.includes("not allowed")) {
      notice.textContent = "Review your question, then select Run.";
    }
  };
  window.addEventListener("pagehide", () => {
    recognition.abort();
    clearInterval(interval);
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  });
}

function grid(columns, rows) {
  const table = element("table");
  const header = element("tr");
  columns.forEach(name => header.append(element("th", name)));
  table.append(header);
  rows.forEach(row => {
    const tr = element("tr");
    row.forEach(value => tr.append(element("td", value === null ? "" : String(value))));
    table.append(tr);
  });
  return table;
}

async function loadTable(database, name, offset = 0) {
  const serial = ++tableRequest;
  selectedTable = { database, name };
  const modal = document.getElementById("table-modal");
  document.getElementById("table-title").textContent = `${database}.${name}`;
  document.getElementById("table-page-info").textContent = "Loading records...";
  document.getElementById("table-data").replaceChildren();
  if (!modal.open) modal.showModal();
  document.getElementById("previous-page").disabled = true;
  document.getElementById("next-page").disabled = true;
  try {
    const data = await api(`/api/table?database=${encodeURIComponent(database)}&table=${encodeURIComponent(name)}&offset=${offset}`);
    if (serial !== tableRequest) return;
    tablePage = data.offset;
    document.getElementById("table-data").replaceChildren(grid(data.columns, data.rows));
    document.getElementById("table-structure").replaceChildren(grid(
      ["Column", "Type", "Key", "Reference"],
      data.structure.map(column => [column.name, column.type, column.key, column.references || ""])
    ));
    document.getElementById("table-page-info").textContent = data.total ? `Rows ${data.offset + 1}-${data.next_offset} of ${data.total}` : "This table has no rows.";
    document.getElementById("previous-page").disabled = data.offset === 0;
    document.getElementById("next-page").disabled = !data.has_more;
    document.getElementById("next-page").dataset.offset = data.next_offset;
  } catch (error) {
    if (serial === tableRequest) document.getElementById("table-page-info").textContent = error.message;
  }
}

function showTables() {
  const database = document.getElementById("database-select").value;
  document.getElementById("workspace-name").textContent = database || "All databases";
  const list = document.getElementById("table-list");
  list.replaceChildren();
  Object.entries(catalog).filter(([name]) => !database || name === database).forEach(([name, tables]) => {
    if (!database) list.append(element("p", name, "table-group"));
    Object.keys(tables).forEach(table => {
      const button = element("button", table, "table-link");
      button.addEventListener("click", () => loadTable(name, table));
      list.append(button);
    });
  });
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!response.headers.get("content-type")?.includes("application/json")) {
    throw new Error("The server could not complete the request. Please try again.");
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The request could not be completed.");
  return data;
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

async function preview(id) {
  status.textContent = "";
  const snapshot = await api(`/api/reports/${id}`);
  const report = snapshot.document;
  await api(`/api/reports/${id}/preview`, {});
  currentReport = id;
  const paper = document.getElementById("report-preview");
  paper.replaceChildren();
  paper.append(element("h2", report.title), element("p", report.created_at.slice(0, 10), "muted"),
    element("p", report.question), element("p", report.summary));
  section(paper, "Findings", report.findings);
  section(paper, "Suggested business actions", report.actions);
  section(paper, "Limitations", report.limitations);
  if (report.chart) {
    const chart = element("img");
    chart.src = `/api/reports/${id}/chart.svg`; chart.alt = report.chart.title; chart.className = "chart";
    paper.append(chart);
  }
  const table = element("table");
  const heading = element("tr");
  report.data.columns.slice(0, 6).forEach(name => heading.append(element("th", name)));
  table.append(heading);
  report.data.rows.slice(0, 10).forEach(row => {
    const tr = element("tr");
    row.slice(0, 6).forEach(value => tr.append(element("td", value === null ? "" : String(value))));
    table.append(tr);
  });
  const scroll = element("div", undefined, "table-scroll");
  scroll.append(table); paper.append(element("h3", "Returned data"), scroll);
  paper.append(element("p", "Preview: up to 10 returned rows and 6 columns.", "muted"));
  document.getElementById("download-report").href = `/api/reports/${id}/pdf?download=1`;
  const send = document.getElementById("email-report");
  if (send) send.disabled = !emailReady || ["sent", "sending", "unknown"].includes(snapshot.mail_status);
  document.getElementById("mail-status").textContent = send && !emailReady ? "Configure Gmail in the owner settings before sending." : "";
  document.getElementById("report-modal").showModal();
}

async function renderMessage(message) {
  const card = element("article", undefined, `message ${message.role}`);
  card.append(element("p", message.content, "message-text"));
  document.getElementById("messages").append(card);
  document.getElementById("welcome").hidden = true;
  if (message.report_id) {
    const { document: report } = await api(`/api/reports/${message.report_id}`);
    card.prepend(element("h2", report.title));
    if (report.chart) {
      const chart = element("img");
      chart.src = `/api/reports/${message.report_id}/chart.svg`;
      chart.alt = report.chart.title;
      chart.className = "chart";
      card.append(chart);
    }
    section(card, "Key findings", report.findings);
    section(card, "Business actions", report.actions);
    const details = element("details");
    details.append(element("summary", "Data & limitations"));
    section(details, "Scope", report.limitations);
    const wrap = element("div", undefined, "table-scroll");
    const table = element("table");
    const header = element("tr");
    report.data.columns.forEach(name => header.append(element("th", name)));
    table.append(header);
    report.data.rows.slice(0, 20).forEach(row => {
      const tr = element("tr");
      row.forEach(value => tr.append(element("td", value === null ? "" : String(value))));
      table.append(tr);
    });
    wrap.append(table); details.append(wrap);
    details.append(element("p", "Showing up to 20 returned rows.", "muted"));
    const numeric = report.profile.columns.filter(column => column.numeric);
    numeric.forEach(column => details.append(element("p", `${column.name}: min ${column.minimum}, max ${column.maximum}, mean ${column.mean}, median ${column.median}, missing ${column.missing}.`, "muted")));
    card.append(details);
    const button = element("button", "Preview business report", "report-button");
    button.addEventListener("click", () => preview(message.report_id).catch(error => { status.textContent = error.message; }));
    card.append(button);
  }
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
  document.getElementById("sidebar-toggle").addEventListener("click", event => {
    const collapsed = document.body.classList.toggle("sidebar-collapsed");
    event.currentTarget.setAttribute("aria-expanded", String(!collapsed));
    event.currentTarget.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
    event.currentTarget.textContent = collapsed ? "\u203a" : "\u2039";
  });
  api("/api/catalog").then(data => {
    catalog = data.databases;
    const selector = document.getElementById("database-select");
    Object.keys(catalog).forEach(database => {
      const option = element("option", database);
      option.value = database;
      selector.append(option);
    });
    showTables();
  }).catch(error => { status.textContent = error.message; });
  document.getElementById("database-select").addEventListener("change", showTables);
  document.getElementById("close-table").addEventListener("click", () => {
    tableRequest++;
    document.getElementById("table-modal").close();
  });
  document.getElementById("previous-page").addEventListener("click", () => loadTable(selectedTable.database, selectedTable.name, Math.max(0, tablePage - 50)));
  document.getElementById("next-page").addEventListener("click", event => loadTable(selectedTable.database, selectedTable.name, Number(event.target.dataset.offset)));
  api("/api/state").then(async data => {
    emailReady = data.email_ready;
    showRecentChats(data);
    for (const message of data.messages) await renderMessage(message);
  }).catch(error => { status.textContent = error.message; });
  document.getElementById("question-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (busy) return;
    const input = document.getElementById("question");
    const question = input.value.trim();
    if (!question) return;
    busy = true;
    if (recognition) recognition.abort();
    document.getElementById("submit").disabled = true;
    document.getElementById("new-chat").disabled = true;
    input.value = "";
    status.textContent = "Working on your question...";
    try {
      const result = await api("/api/chat", { question, mode: document.querySelector('input[name="mode"]:checked').value, database: document.getElementById("database-select").value });
      await renderMessage({ role: "user", content: result.question });
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
      status.textContent = error.message;
    } finally {
      busy = false;
      document.getElementById("submit").disabled = false;
      document.getElementById("new-chat").disabled = false;
      input.focus();
    }
  });
  document.getElementById("question").addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      document.getElementById("question-form").requestSubmit();
    }
  });
  document.getElementById("new-chat").addEventListener("click", async () => {
    try { await api("/api/new", {}); location.reload(); }
    catch (error) { status.textContent = error.message; }
  });
  document.getElementById("close-report").addEventListener("click", () => document.getElementById("report-modal").close());
  document.getElementById("email-report")?.addEventListener("click", async event => {
    event.target.disabled = true;
    const notice = document.getElementById("mail-status");
    notice.textContent = "Sending the reviewed report...";
    try {
      const result = await api(`/api/reports/${currentReport}/email`, {});
      notice.textContent = result.message;
    } catch (error) {
      notice.textContent = error.message;
    }
  });
}
