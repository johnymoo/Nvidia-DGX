const state = { csrf: "", status: null, operation: null, receiptTimer: null };

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function textNode(tag, value, className = "") {
  const node = document.createElement(tag);
  node.textContent = value ?? "";
  if (className) node.className = className;
  return node;
}

function stateBadge(value) {
  return textNode("span", value, `state state-${String(value).toLowerCase()}`);
}

function addLines(cell, values) {
  const lines = values.length ? values : ["-"];
  lines.forEach((value, index) => {
    if (index) cell.appendChild(document.createElement("br"));
    cell.appendChild(document.createTextNode(value));
  });
}

function pathList(values) {
  const node = document.createElement("div");
  const grouped = new Map();
  [...new Set(values)].forEach(value => {
    const name = value.split("/").filter(Boolean).pop() || value;
    grouped.set(name, [...(grouped.get(name) || []), value]);
  });
  if (!grouped.size) {
    node.textContent = "-";
    return node;
  }
  [...grouped.entries()].forEach(([name, paths], index) => {
    if (index) node.appendChild(document.createElement("br"));
    const item = document.createElement("span");
    item.textContent = name;
    item.title = paths.join("\n");
    node.appendChild(item);
  });
  return node;
}

function renderTable(target, headers, rows) {
  clear(target);
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  headers.forEach(header => headRow.appendChild(textNode("th", header)));
  head.appendChild(headRow);
  const body = document.createElement("tbody");
  rows.forEach(cells => {
    const row = document.createElement("tr");
    cells.forEach(content => {
      const cell = document.createElement("td");
      if (content instanceof Node) cell.appendChild(content);
      else if (Array.isArray(content)) addLines(cell, content.map(String));
      else cell.textContent = content ?? "";
      row.appendChild(cell);
    });
    body.appendChild(row);
  });
  table.append(head, body);
  target.appendChild(table);
}

function renderStatus(documentValue) {
  state.status = documentValue;
  const summary = document.getElementById("summary");
  clear(summary);
  ["Running", "Partial", "Stopped", "Degraded"].forEach(name => {
    const metric = document.createElement("div");
    metric.className = "metric";
    metric.append(textNode("strong", documentValue.models.filter(model => model.state === name).length), textNode("span", name));
    summary.appendChild(metric);
  });
  const rows = documentValue.models.map(model => {
    const identity = document.createElement("div");
    const title = textNode("div", model.display_name, "model-name");
    if (model.protected) title.appendChild(textNode("span", "PROTECTED", "protected"));
    identity.append(title, textNode("div", model.id, "model-id"));
    if (!model.operable) identity.appendChild(textNode("div", model.availability.reason, "availability"));
    const actions = document.createElement("div");
    actions.className = "actions";
    if (model.operable) {
      ["start", "stop", "restart"].forEach(action => {
        const button = textNode("button", action);
        button.dataset.model = model.id;
        button.dataset.action = action;
        button.dataset.protected = model.protected ? "true" : "false";
        actions.appendChild(button);
      });
    } else {
      actions.textContent = "Read only";
    }
    return [
      identity,
      stateBadge(model.state),
      model.deployments.map(item => `${item.host}: ${item.state}`),
      model.endpoints.map(item => `${item.host} ${item.bind}:${item.port}/${item.protocol}`),
      pathList(model.deployments.flatMap(item => item.config_files)),
      actions,
    ];
  });
  renderTable(document.getElementById("models"), ["Model", "State", "Hosts", "Endpoints", "Compose", "Actions"], rows);
  renderTable(
    document.getElementById("unmanaged"),
    ["Project", "State", "Host", "Compose"],
    documentValue.unmanaged.map(item => [item.project, stateBadge("Unmanaged"), item.host, pathList(item.config_files)]),
  );
}

async function loadStatus() {
  const sync = document.getElementById("sync-state");
  sync.textContent = "Refreshing";
  try {
    renderStatus(await request("/api/v1/status"));
    sync.textContent = "Live";
  } catch (error) {
    sync.textContent = "Unavailable";
    toast(error.message, true);
  }
}

async function loadPorts() {
  const host = document.getElementById("host-filter").value;
  const data = await request(`/api/v1/ports${host ? `?host=${encodeURIComponent(host)}` : ""}`);
  renderTable(
    document.getElementById("ports"),
    ["Host", "Protocol", "Bind", "Port", "Process"],
    data.listeners.map(item => [item.host, item.protocol, item.bind, item.port, item.process || "-"]),
  );
}

async function preview(model, action, isProtected) {
  const confirmation = isProtected ? `PROTECTED ${action} ${model}` : model;
  try {
    const plan = await request(`/api/v1/models/${encodeURIComponent(model)}/${action}`, {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Model-Platform-CSRF": state.csrf},
      body: JSON.stringify({confirm: confirmation, dry_run: true, allow_protected: isProtected}),
    });
    state.operation = {model, action, isProtected, confirmation};
    document.getElementById("dialog-title").textContent = `${action} ${model}`;
    document.getElementById("operation-preview").textContent = JSON.stringify(plan, null, 2);
    document.getElementById("confirmation-label").textContent = `Confirm: ${confirmation}`;
    document.getElementById("confirmation").value = "";
    const protectedRow = document.getElementById("protected-row");
    protectedRow.hidden = !isProtected;
    document.getElementById("allow-protected").checked = false;
    document.getElementById("operation-dialog").showModal();
  } catch (error) {
    renderOperationError(error.message);
  }
}

function renderReceipt(receipt) {
  const panel = document.getElementById("operation-state");
  panel.hidden = false;
  document.getElementById("receipt-title").textContent = `${receipt.action} ${receipt.model}`;
  document.getElementById("receipt-status").textContent = receipt.status;
  document.getElementById("receipt-id").textContent = receipt.id;
  document.getElementById("receipt-detail").textContent = JSON.stringify({
    commands: receipt.commands || [],
    observed: receipt.observed || null,
    lock_release: receipt.lock_release || null,
    error: receipt.error || null,
  }, null, 2);
}

function renderOperationError(message) {
  const panel = document.getElementById("operation-state");
  panel.hidden = false;
  document.getElementById("receipt-title").textContent = "Operation failed";
  document.getElementById("receipt-status").textContent = "failed";
  document.getElementById("receipt-id").textContent = "";
  document.getElementById("receipt-detail").textContent = message;
  toast(message, true);
}

async function pollReceipt(receiptId) {
  clearTimeout(state.receiptTimer);
  try {
    const receipt = await request(`/api/v1/receipts/${encodeURIComponent(receiptId)}`);
    renderReceipt(receipt);
    if (["queued", "running"].includes(receipt.status)) {
      state.receiptTimer = setTimeout(() => pollReceipt(receiptId), 1000);
    } else {
      localStorage.removeItem("modelPlatformReceipt");
      await loadStatus();
    }
  } catch (error) {
    renderOperationError(error.message);
  }
}

async function executeOperation(event) {
  event.preventDefault();
  const {model, action, isProtected} = state.operation;
  const confirmation = document.getElementById("confirmation").value;
  const allowProtected = document.getElementById("allow-protected").checked;
  const button = document.getElementById("execute");
  button.disabled = true;
  button.textContent = "Submitting";
  try {
    const receipt = await request(`/api/v1/models/${encodeURIComponent(model)}/${action}`, {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Model-Platform-CSRF": state.csrf},
      body: JSON.stringify({confirm: confirmation, dry_run: false, allow_protected: isProtected && allowProtected}),
    });
    document.getElementById("operation-dialog").close();
    localStorage.setItem("modelPlatformReceipt", receipt.id);
    renderReceipt(receipt);
    pollReceipt(receipt.id);
  } catch (error) {
    renderOperationError(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Execute";
  }
}

function toast(message, isError = false) {
  const node = document.getElementById("toast");
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.classList.add("visible");
  setTimeout(() => node.classList.remove("visible"), 5000);
}

document.addEventListener("click", event => {
  const action = event.target.closest("[data-action]");
  if (action) preview(action.dataset.model, action.dataset.action, action.dataset.protected === "true");
  const tab = event.target.closest(".tab");
  if (tab) {
    document.querySelectorAll(".tab,.view").forEach(node => node.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(`${tab.dataset.view}-view`).classList.add("active");
    if (tab.dataset.view === "ports") loadPorts().catch(error => toast(error.message, true));
  }
});

document.getElementById("refresh").addEventListener("click", loadStatus);
document.getElementById("host-filter").addEventListener("change", () => loadPorts().catch(error => toast(error.message, true)));
document.getElementById("execute").addEventListener("click", executeOperation);

Promise.all([request("/api/v1/session"), request("/api/v1/status")]).then(([session, status]) => {
  state.csrf = session.csrf;
  renderStatus(status);
  document.getElementById("sync-state").textContent = "Live";
  const receiptId = localStorage.getItem("modelPlatformReceipt");
  if (receiptId) pollReceipt(receiptId);
}).catch(error => toast(error.message, true));
