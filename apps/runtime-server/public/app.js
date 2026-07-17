const traceList = document.querySelector("#trace-list");
const detail = document.querySelector("#detail");
const template = document.querySelector("#trace-item-template");
const healthDot = document.querySelector("#health-dot");
const healthText = document.querySelector("#health-text");
let selectedTraceId;
let activeFilters = new URLSearchParams();

document.querySelector("#refresh").addEventListener("click", () => void refresh());
document.querySelector("#trace-filters").addEventListener("submit", (event) => {
  event.preventDefault();
  activeFilters = formFilters(new FormData(event.currentTarget));
  void refresh();
});
document.querySelector("#clear-filters").addEventListener("click", () => {
  document.querySelector("#trace-filters").reset();
  activeFilters = new URLSearchParams();
  void refresh();
});

async function refresh() {
  try {
    const [health, tracePayload] = await Promise.all([
      requestJson("/health"),
      requestJson(traceListPath()),
    ]);
    healthDot.className = "ok";
    healthText.textContent = "Runtime online";
    document.querySelector("#trace-count").textContent = formatNumber(health.traces);
    document.querySelector("#event-count").textContent = formatNumber(health.events);
    renderTraces(tracePayload.traces);
  } catch (error) {
    healthDot.className = "error";
    healthText.textContent = "Runtime unavailable";
    showError(error);
  }
}

function renderTraces(traces) {
  traceList.replaceChildren();
  if (traces.length === 0) {
    const empty = element("p", "empty-list");
    empty.textContent = "No executions yet. Run npm run demo to create the first trace.";
    traceList.append(empty);
    return;
  }
  for (const trace of traces) {
    const fragment = template.content.cloneNode(true);
    const button = fragment.querySelector("button");
    button.dataset.status = trace.status;
    button.dataset.traceId = trace.traceId;
    if (trace.traceId === selectedTraceId) button.classList.add("selected");
    fragment.querySelector("strong").textContent = trace.name;
    const dimensions = [...trace.frameworks, ...trace.providers, ...trace.models].slice(0, 2);
    fragment.querySelector("small").textContent = [
      trace.serviceName,
      ...dimensions,
      shortId(trace.traceId),
    ].join(" · ");
    fragment.querySelector(".duration").textContent = formatDuration(trace.durationMs);
    button.addEventListener("click", () => void selectTrace(trace.traceId));
    traceList.append(fragment);
  }
}

async function selectTrace(traceId) {
  selectedTraceId = traceId;
  for (const button of traceList.querySelectorAll(".trace-item")) {
    button.classList.toggle("selected", button.dataset.traceId === traceId);
  }
  detail.setAttribute("aria-busy", "true");
  try {
    renderDetail(await requestJson(`/api/traces/${encodeURIComponent(traceId)}`));
  } catch (error) {
    showError(error);
  } finally {
    detail.removeAttribute("aria-busy");
  }
}

function renderDetail(trace) {
  const { summary, events } = trace;
  detail.replaceChildren();

  const header = element("header", "trace-header");
  const titleBox = document.createElement("div");
  const eyebrow = element("p", "eyebrow");
  eyebrow.textContent = summary.serviceName.toUpperCase();
  const title = document.createElement("h2");
  title.textContent = summary.name;
  const id = document.createElement("p");
  id.textContent = summary.traceId;
  titleBox.append(eyebrow, title, id);
  const badge = element("span", `badge ${summary.status}`);
  badge.textContent = summary.status;
  const actions = element("div", "trace-actions");
  const exportButton = document.createElement("button");
  exportButton.type = "button";
  exportButton.textContent = "Export";
  exportButton.addEventListener("click", () => void exportTrace(summary.traceId));
  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "danger";
  deleteButton.textContent = "Delete";
  deleteButton.addEventListener("click", () => void deleteTrace(summary.traceId));
  actions.append(badge, exportButton, deleteButton);
  header.append(titleBox, actions);

  const metrics = element("div", "trace-metrics");
  metrics.append(
    metric(formatDuration(summary.durationMs), "duration"),
    metric(String(summary.eventCount), "events"),
    metric(String(summary.errorCount), "errors"),
    metric(String(summary.relationshipCount), "relationships"),
  );

  const timeline = element("section", "timeline");
  const timelineTitle = document.createElement("h3");
  timelineTitle.textContent = "Execution timeline";
  timeline.append(timelineTitle);
  for (const eventData of events) timeline.append(eventRow(eventData));
  const relationships = relationshipGraph(events);
  detail.append(header, metrics, ...(relationships === undefined ? [] : [relationships]), causalTree(events), timeline);
}

function relationshipGraph(events) {
  const relationships = events.filter((eventData) => (
    eventData.type === "agent.handoff.start" || eventData.type === "agent.delegation.start"
  ));
  if (relationships.length === 0) return undefined;
  const ends = new Map(events
    .filter((eventData) => (
      eventData.type === "agent.handoff.end" || eventData.type === "agent.delegation.end"
    ))
    .map((eventData) => [eventData.spanId, eventData]));
  const section = element("section", "relationship-graph");
  const title = document.createElement("h3");
  title.textContent = "Agent relationships";
  section.append(title);
  for (const start of relationships) {
    const attributes = start.attributes;
    const kind = String(attributes["causentra.agent.relationship.kind"] ?? "handoff");
    const from = String(attributes["causentra.agent.from.name"] ?? "unknown source");
    const to = String(attributes["causentra.agent.to.name"] ?? "unknown target");
    const end = ends.get(start.spanId);
    const card = element("article", "relationship");
    card.dataset.status = end?.status ?? "unset";
    const source = element("strong", "relationship-agent");
    source.textContent = from;
    const arrow = element("span", "relationship-arrow");
    arrow.textContent = kind === "delegation" ? "delegates →" : "hands off →";
    const target = element("strong", "relationship-agent");
    target.textContent = to;
    const metadata = element("small", "relationship-meta");
    metadata.textContent = [
      kind,
      String(attributes["framework.name"] ?? "portable contract"),
      formatDuration(end?.durationMs),
      end?.status ?? "running",
    ].join(" · ");
    card.append(source, arrow, target, metadata);
    section.append(card);
  }
  return section;
}

function causalTree(events) {
  const section = element("section", "causal-tree");
  const title = document.createElement("h3");
  title.textContent = "Causal execution tree";
  section.append(title);
  const operations = buildOperations(events);
  const maximumDuration = Math.max(0, ...operations.map((operation) => operation.durationMs ?? 0));
  for (const operation of operations) {
    const row = element("article", "operation");
    row.dataset.status = operation.status;
    row.style.setProperty("--depth", String(operation.depth));
    const marker = element("span", "operation-marker");
    const copy = element("div", "operation-copy");
    const name = document.createElement("strong");
    name.textContent = operation.name;
    const metadata = document.createElement("small");
    metadata.textContent = operation.family;
    copy.append(name, metadata);
    const duration = element("span", "duration");
    duration.textContent = formatDuration(operation.durationMs);
    row.append(marker, copy, duration);
    if (operation.status === "error") {
      const flag = element("span", "operation-flag error");
      flag.textContent = "failed";
      row.append(flag);
    } else if (operation.durationMs === maximumDuration && operations.length > 1) {
      const flag = element("span", "operation-flag");
      flag.textContent = "slowest";
      row.append(flag);
    }
    section.append(row);
  }
  return section;
}

function buildOperations(events) {
  const starts = events.filter((eventData) => eventData.type.endsWith(".start"));
  const ends = new Map(
    events.filter((eventData) => eventData.type.endsWith(".end"))
      .map((eventData) => [eventData.spanId, eventData]),
  );
  const startIds = new Set(starts.map((eventData) => eventData.spanId));
  const depth = (eventData) => {
    let value = 0;
    let parentId = eventData.parentSpanId;
    const visited = new Set();
    while (parentId && startIds.has(parentId) && !visited.has(parentId)) {
      visited.add(parentId);
      value += 1;
      parentId = starts.find((candidate) => candidate.spanId === parentId)?.parentSpanId;
    }
    return value;
  };
  return starts.map((start) => {
    const end = ends.get(start.spanId);
    const relationship = start.attributes["causentra.agent.relationship.kind"];
    const family = relationship === "handoff" || relationship === "delegation"
      ? `${relationship}: ${String(start.attributes["causentra.agent.from.name"] ?? "?")} → ${String(start.attributes["causentra.agent.to.name"] ?? "?")}`
      : start.type.slice(0, -".start".length);
    return {
      name: start.name,
      family,
      depth: depth(start),
      status: end?.status ?? "unset",
      durationMs: end?.durationMs,
    };
  });
}

async function exportTrace(traceId) {
  try {
    const bundle = await requestJson(`/api/traces/${encodeURIComponent(traceId)}/export`);
    const blob = new Blob([`${JSON.stringify(bundle, null, 2)}\n`], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `causentra-trace-${traceId}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    showError(error);
  }
}

async function deleteTrace(traceId) {
  if (!globalThis.confirm("Delete this local trace permanently?")) return;
  try {
    await requestJson(`/api/traces/${encodeURIComponent(traceId)}`, { method: "DELETE" });
    selectedTraceId = undefined;
    detail.replaceChildren();
    await refresh();
  } catch (error) {
    showError(error);
  }
}

function eventRow(eventData) {
  const row = element("article", "event");
  row.dataset.status = eventData.status;
  if (eventData.parentSpanId) row.style.paddingLeft = "12px";
  const time = document.createElement("time");
  time.textContent = new Date(eventData.timestamp).toLocaleTimeString([], {
    hour12: false,
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
  const marker = element("span", "event-marker");
  const main = element("div", "event-main");
  const name = document.createElement("strong");
  name.textContent = eventData.name;
  const type = document.createElement("small");
  type.textContent = `${eventData.type} · ${shortId(eventData.spanId)}`;
  main.append(name, type);
  const duration = element("span", "duration");
  duration.textContent = formatDuration(eventData.durationMs);
  row.append(time, marker, main, duration);
  if (Object.keys(eventData.attributes).length > 0) {
    const attributes = document.createElement("pre");
    attributes.textContent = JSON.stringify(eventData.attributes, null, 2);
    row.append(attributes);
  }
  return row;
}

function metric(value, label) {
  const box = document.createElement("div");
  const strong = document.createElement("strong");
  strong.textContent = value;
  const span = document.createElement("span");
  span.textContent = label;
  box.append(strong, span);
  return box;
}

async function requestJson(path, init = {}) {
  const response = await fetch(path, {
    ...init,
    headers: { accept: "application/json", ...init.headers },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error?.message ?? `Request failed: ${response.status}`);
  return payload;
}

function showError(error) {
  const message = element("p", "error-message");
  message.textContent = error instanceof Error ? error.message : "Unknown error";
  detail.replaceChildren(message);
}

function element(tag, className) {
  const node = document.createElement(tag);
  node.className = className;
  return node;
}

function formFilters(data) {
  const parameters = new URLSearchParams();
  for (const name of ["q", "status", "framework", "provider", "model", "tool", "session"]) {
    const value = String(data.get(name) ?? "").trim();
    if (value.length > 0) parameters.set(name, value);
  }
  return parameters;
}

function traceListPath() {
  const parameters = new URLSearchParams(activeFilters);
  parameters.set("limit", "100");
  return `/api/traces?${parameters.toString()}`;
}

function shortId(value) { return value.slice(0, 8); }
function formatNumber(value) { return new Intl.NumberFormat().format(value); }
function formatDuration(value) {
  if (value === undefined) return "—";
  if (value < 1_000) return `${value.toFixed(value < 10 ? 1 : 0)} ms`;
  return `${(value / 1_000).toFixed(2)} s`;
}

void refresh();
setInterval(() => void refresh(), 10_000);
