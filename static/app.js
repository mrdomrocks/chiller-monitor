const S = {
  meta: null,
  sites: [],
  siteId: null,
  site: null,
  live: null,
  view: "plant",
  pointId: null,
  customise: false,
};

let shellReady = false;
let busy = false;
let toastTimer = 0;
let compressorKey = "";

const FC = { coil: 1, discrete: 2, holding: 3, input: 4 };
const BASE = { coil: 1, discrete: 10001, input: 30001, holding: 40001 };
const WIDGETS = [["value", "Value"], ["gauge", "Gauge"], ["status", "Status lamp"], ["alarm", "Alarm"], ["setpoint", "Setpoint"], ["hidden", "Hidden"]];
const LAYOUT = [
  ["faceplate", "Chiller display"],
  ["mimic", "Water diagram"],
  ["compressors", "Compressors"],
  ["readings", "Flow and pressure"],
  ["status", "Status lamps"],
  ["outputs", "Writable outputs"],
  ["profile", "Register map"],
  ["table", "Live values"],
];

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

async function api(path, options = {}) {
  const opts = { ...options };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    opts.body = JSON.stringify(opts.body);
  }
  const response = await fetch(path, opts);
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!response.ok) {
    const detail = data && data.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg || JSON.stringify(item)).join(", ")
      : detail || response.statusText;
    throw new Error(message);
  }
  return data;
}

function toast(message, ok = false) {
  const el = document.getElementById("toast");
  el.hidden = !message;
  el.textContent = message || "";
  el.className = ok ? "toast ok" : "toast";
  clearTimeout(toastTimer);
  if (message) toastTimer = setTimeout(() => { el.hidden = true; }, 4500);
}

function pointById(id) {
  return S.site?.points.find((point) => point.id === id) || null;
}

function bound(role) {
  const id = S.site?.bindings?.[role];
  return id ? pointById(id) : null;
}

function readingFor(id) {
  if (!id || !S.live || S.live.site_id !== S.siteId) return null;
  return S.live.values?.[id] || null;
}

function connected() {
  return Boolean(S.live && S.live.site_id === S.siteId && S.live.modbus?.state === "polling");
}

function sessionOpen() {
  return Boolean(S.live && S.live.site_id === S.siteId && S.live.modbus?.state !== "idle");
}

async function guard(work) {
  if (busy) return;
  busy = true;
  paintLive();
  try {
    await work();
  } catch (error) {
    toast(error.message || String(error));
  } finally {
    busy = false;
    paintLive();
  }
}

function ensureShell() {
  if (shellReady) return;
  document.getElementById("app").innerHTML = `
    <header class="top">
      <div class="brand">
        <span class="mark">RUT</span>
        <div>
          <strong>Chiller Monitor</strong>
          <small>Modbus TCP</small>
        </div>
      </div>
      <label class="site-pick">Site
        <select id="siteSelect"></select>
      </label>
      <div class="conn" id="connPill">
        <span class="lamp" id="connLamp"></span>
        <span id="connText">Offline</span>
      </div>
      <div class="top-actions">
        <button type="button" class="primary" id="connectBtn" data-action="toggle-connect">Connect</button>
        <button type="button" data-action="add-site">New site</button>
      </div>
    </header>
    <p class="update-banner" id="updateBanner" hidden>
      A newer Chiller Monitor is on GitHub.
      <button type="button" data-action="install-update">Download and install</button>
    </p>
    <nav class="tabs" id="tabs">
      <button type="button" data-view="plant" aria-selected="true">Plant</button>
      <button type="button" data-view="map" aria-selected="false">Register map</button>
      <button type="button" data-view="link" aria-selected="false">Connection</button>
      <button type="button" data-view="mapper" aria-selected="false">Mapper</button>
    </nav>
    <main id="main"></main>
    <div id="modal" class="modal" hidden>
      <form id="newSiteForm" class="panel">
        <h2>New site</h2>
        <p class="help">A site is one chiller behind one RUT. The chilled-water map is loaded so you can edit addresses rather than start from a blank list.</p>
        <label>Name <input name="name" required maxlength="80" placeholder="Plant room 2"></label>
        <div class="form-actions" style="margin-top:12px">
          <button class="primary" type="submit">Create</button>
          <button type="button" data-action="close-modal">Cancel</button>
        </div>
      </form>
    </div>
    <div id="toast" class="toast" hidden></div>
  `;
  shellReady = true;
  document.addEventListener("click", onClick);
  document.addEventListener("submit", onSubmit);
  document.addEventListener("change", onChange);
  document.addEventListener("input", onInput);
}

function siteListRank(site) {
  const match = /^demo-(\d+)$/.exec(site.id || "");
  return match ? Number(match[1]) : 1000;
}

function fillSiteSelect() {
  const select = document.getElementById("siteSelect");
  select.replaceChildren();
  const sites = [...S.sites]
    .filter((site) => site.id !== "demo")
    .sort((a, b) => siteListRank(a) - siteListRank(b) || a.name.localeCompare(b.name));
  if (!sites.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No sites yet";
    select.appendChild(option);
    return;
  }
  for (const site of sites) {
    const option = document.createElement("option");
    option.value = site.id;
    option.textContent = site.name;
    select.appendChild(option);
  }
  select.value = S.siteId || "";
}

function paintHeader() {
  const lamp = document.getElementById("connLamp");
  const text = document.getElementById("connText");
  const button = document.getElementById("connectBtn");
  if (!lamp) return;
  lamp.className = "lamp";
  if (!S.site) {
    text.textContent = "No site";
  } else if (!S.live || S.live.site_id !== S.siteId) {
    text.textContent = "Offline";
  } else if (S.live.modbus.state === "polling") {
    lamp.classList.add("ok");
    const age = S.live.polled_at ? `${((Date.now() - S.live.polled_at) / 1000).toFixed(1)}s` : "";
    text.textContent = age ? `Live · ${age}` : "Live";
  } else if (S.live.modbus.state === "connecting") {
    lamp.classList.add("wait");
    text.textContent = "Connecting";
  } else if (S.live.modbus.state === "error") {
    lamp.classList.add("bad");
    text.textContent = "No data";
  } else {
    text.textContent = "Offline";
  }
  const open = sessionOpen();
  button.textContent = busy ? "Working…" : open ? "Disconnect" : "Connect";
  button.disabled = busy || !S.site;
  for (const sizeButton of document.querySelectorAll("[data-action='demo-size']")) {
    const active = Boolean(S.live?.simulator_running && S.live.site_id === `demo-${sizeButton.dataset.count}`);
    sizeButton.setAttribute("aria-pressed", active ? "true" : "false");
    sizeButton.disabled = busy;
  }
  for (const tab of document.querySelectorAll("#tabs button")) {
    tab.setAttribute("aria-selected", tab.dataset.view === S.view ? "true" : "false");
  }
}

function render() {
  const drawOpen = Boolean(document.querySelector(".customise details[open]"));
  compressorKey = "";
  ensureShell();
  fillSiteSelect();
  paintHeader();
  document.body.classList.toggle("customising", Boolean(S.customise && S.view === "plant" && S.site));
  const main = document.getElementById("main");
  if (S.view === "mapper") renderMapper(main);
  else if (!S.site) {
    main.innerHTML = `
      <section class="welcome">
        <h1>Watch a chiller through the RUT</h1>
        <p>Join the chiller network on this laptop, then Chiller Monitor opens the same Modbus socket Modbus Monitor uses. Modbus TCP is for the RUT’s translating gateway. RTU over TCP is for a raw serial-over-IP tunnel. Customise display on the plant page chooses what the HMI shows. The register map holds addresses and scaling.</p>
        <div class="actions">
          <button class="primary" type="button" data-action="demo-size" data-count="1">Single compressor</button>
          <button type="button" data-action="demo-size" data-count="2">Two compressors</button>
          <button type="button" data-action="add-site">Create a site</button>
        </div>
      </section>`;
  } else if (S.view === "map") renderMap(main);
  else if (S.view === "link") renderLink(main);
  else renderPlant(main);
  if (drawOpen) {
    const details = document.querySelector(".customise details");
    if (details) details.open = true;
  }
  paintLive();
  syncMapperWatch();
}

function layoutOn(key) {
  return S.site?.layout?.[key] !== false;
}

function renderPlant(main) {
  const site = S.site;
  const customise = S.customise ? customiseBar(site) : "";
  const mimic = mimicHtml(site);
  const compressors = compressorSectionShown() ? `<section class="compressor-bank">
      <div class="section-head">
        <div>
          <h2>Compressors</h2>
          <p class="muted" id="compressorSummary"></p>
        </div>
        <div class="comp-count" id="compressorStepper" hidden>
          <span class="kicker">Fitted</span>
          ${compressorIndexes().map((n) => `<button type="button" data-action="write-count" data-count="${n}" data-requires-connection aria-label="Show ${n} compressors">${n}</button>`).join("")}
        </div>
      </div>
      ${S.customise ? compressorSlots() : ""}
      <div class="compressors" id="compressorGrid"></div>
    </section>` : "";
  const readings = readingsHtml();
  const status = statusHtml();
  const outputs = outputsHtml();
  const table = layoutOn("table") ? `<div class="table-wrap">
      <table>
        <thead><tr><th>Point</th><th>Value</th><th>Raw</th><th>Quality</th></tr></thead>
        <tbody>${tableRows()}</tbody>
      </table>
    </div>` : "";
  main.innerHTML = `
    <p class="demo-flag" id="demoFlag" hidden>Demo on this computer.</p>
    ${controllerSheet() ? "" : `<div class="alarm-banner" id="alarmBanner" hidden></div>`}
    <div class="plant-head">
      <div>
        <h1 id="plantTitle">${esc(plantTitle())}</h1>
        <p>${esc(site.name)} · ${esc(site.location || "Location not set")} · unit ${esc(site.unit_id)} · ${esc(protocolLabel(site.protocol))} · ${esc(site.modbus_host)}:${esc(site.modbus_port)}</p>
      </div>
      <div class="plant-tools">
        <p class="muted" id="commsDetail"></p>
        ${S.customise ? "" : `<button type="button" data-action="customise">Customise display</button>`}
      </div>
    </div>
    ${customise}
    ${layoutOn("faceplate") ? faceplateHtml() : ""}
    ${controllerSheet() ? "" : heroHtml()}
    ${mimic}
    ${compressors}
    ${readings}
    ${status}
    ${outputs}
    ${profileHtml()}
    ${table}`;
}

function plantTitle() {
  const point = bound("chiller_name");
  if (!point || point.dtype !== "string") return "Chiller";
  const reading = readingFor(point.id);
  const text = reading && reading.quality === "good" ? String(reading.value ?? "").trim() : "";
  return text || "Chiller";
}

function heroRolesShown() {
  const roles = layoutOn("faceplate")
    ? ["setpoint"]
    : ["supply_temp", "return_temp", "setpoint", "capacity"];
  if (S.customise) return roles;
  return roles.filter((role) => bound(role));
}

function heroHtml() {
  const roles = heroRolesShown();
  if (!roles.length) return "";
  return `<section class="hero">${roles.map(heroCard).join("")}</section>`;
}

function loadPoint() {
  return bound("capacity") || bound("comp_1_load");
}

function faultPoints() {
  const named = new Set(["general_alarm", "unit_active_status"]);
  return (S.site?.points || [])
    .filter((point) => point.enabled && (named.has(point.id) || /^alarm_message/.test(point.id)))
    .sort((a, b) => a.address_number - b.address_number || (a.bit ?? -1) - (b.bit ?? -1));
}

function faultTripped(point, reading) {
  if (!point || !reading || reading.quality !== "good") return false;
  if (point.dtype === "bool" || point.function === "coil" || point.function === "discrete" || typeof reading.value === "boolean") {
    return Boolean(reading.value);
  }
  if (typeof reading.value === "number") return reading.value !== 0;
  if (typeof reading.value === "string") return reading.value.trim() !== "";
  return false;
}

function shownFault(point, reading) {
  if (!reading || reading.quality !== "good") return "";
  if (reading.message) return String(reading.message);
  if (point.id === "unit_active_status") return "";
  if (point.id === "general_alarm" || /^alarm_message/.test(point.id)) {
    return faultTripped(point, reading) ? point.name : "";
  }
  return "";
}

function controllerSheet() {
  return Boolean(S.site?.points?.some((point) => point.id === "water_outlet"));
}

function analogPointTile(point, title, roleId) {
  if (!point) {
    return `<article class="face-tile missing">
      <span class="kicker">${esc(title)}</span>
      <b>Not assigned</b>
      ${roleId ? slotSelect(roleId) : ""}
    </article>`;
  }
  const numeric = point.dtype !== "bool" && point.function !== "coil" && point.function !== "discrete";
  return `<article class="face-tile" data-card="${esc(point.id)}">
    <span class="kicker">${esc(title)}</span>
    <span class="face-point">${esc(point.name)}</span>
    <div class="figure"><b data-value="${esc(point.id)}">—</b><small>${esc(point.unit)}</small></div>
    ${numeric ? `<div class="bar"><span data-bar="${esc(point.id)}"></span></div>` : ""}
    ${roleId ? slotSelect(roleId) : ""}
  </article>`;
}

function analogTile(roleId, title) {
  return analogPointTile(bound(roleId), title, roleId);
}

function loadTile() {
  const point = loadPoint();
  const slots = `${slotSelect("capacity")}${slotSelect("comp_1_load")}`;
  if (!point) {
    return `<article class="face-tile missing">
      <span class="kicker">Compressor</span>
      <b>Not assigned</b>
      <p class="muted">Operational percentage. Assign the load register for this controller.</p>
      ${slots}
    </article>`;
  }
  return `<article class="face-tile" data-card="${esc(point.id)}">
    <span class="kicker">Compressor</span>
    <span class="face-point">${esc(point.name)} · operational %</span>
    <div class="figure"><b data-value="${esc(point.id)}">—</b><small>${esc(point.unit || "%")}</small></div>
    <div class="bar"><span data-bar="${esc(point.id)}"></span></div>
    ${slots}
  </article>`;
}

function runtimeLine(index) {
  const hour = pointById(`run_time_comp${index}_hour`);
  const minute = pointById(`run_time_comp${index}_min`);
  if (!hour && !minute) return "";
  return `<p class="run-time" data-runtime="${index}"><span class="kicker">Run time</span> <b data-runtime-text="${index}">—</b></p>`;
}

function runPointTile(point, title, roleId, runtimeIndex) {
  if (!point) {
    return `<article class="face-tile missing">
      <span class="kicker">${esc(title)}</span>
      <b>Not assigned</b>
      ${roleId ? slotSelect(roleId) : ""}
    </article>`;
  }
  return `<article class="face-tile lamp-card" data-lamp="${esc(point.id)}">
    <span class="lamp"></span>
    <div>
      <span class="kicker">${esc(title)}</span>
      <span class="face-point">${esc(point.name)}</span>
      <strong data-value="${esc(point.id)}">—</strong>
      ${runtimeIndex ? runtimeLine(runtimeIndex) : ""}
      ${roleId ? slotSelect(roleId) : ""}
    </div>
  </article>`;
}

function runTile(roleId, title) {
  return runPointTile(bound(roleId), title, roleId);
}

function compressorOperationTiles() {
  const slots = compressorView().slots.filter((slot) => slot.run);
  if (!slots.length) {
    return bound("compressor") ? runPointTile(bound("compressor"), "Compressor", "compressor", 1) : "";
  }
  const many = slots.length > 1;
  return slots.map((slot) => runPointTile(
    slot.run,
    many ? `Compressor ${slot.index}` : "Compressor",
    `comp_${slot.index}_run`,
    slot.index,
  )).join("");
}

function extraCircuitPressures() {
  const used = new Set([bound("low_pressure")?.id, bound("high_pressure")?.id].filter(Boolean));
  return [
    ["comp_2_suction_pressure", "2# Suction"],
    ["comp_2_discharge_pressure", "2# Discharge"],
  ].map(([id, title]) => {
    const point = pointById(id);
    if (!point || used.has(point.id) || point.widget === "hidden") return "";
    used.add(point.id);
    return analogPointTile(point, title);
  }).join("");
}

function alarmFace(withDescription) {
  const point = bound("alarm");
  const lamp = point
    ? `<article class="face-alarm-lamp lamp-card" data-lamp="${esc(point.id)}">
        <span class="lamp"></span>
        <div>
          <span class="kicker">Alarm</span>
          <span class="face-point">${esc(point.name)}</span>
          <strong data-alarm-summary>—</strong>
          ${slotSelect("alarm")}
        </div>
      </article>`
    : `<article class="face-alarm-lamp missing">
        <span class="kicker">Alarm</span>
        <b>Not assigned</b>
        ${slotSelect("alarm")}
      </article>`;
  const faults = faultPoints().map((fault) => `
    <li data-fault="${esc(fault.id)}" hidden>
      <strong data-fault-text="${esc(fault.id)}"></strong>
    </li>`).join("");
  const heading = withDescription ? "Description" : "Fault from the controller";
  const empty = withDescription ? "No alarm description." : "No fault from the controller.";
  const kind = withDescription ? ` data-kind="description"` : "";
  return `<div class="face-alarm">
    ${lamp}
    <div class="fault-box" id="faultBox"${kind}>
      <span class="kicker">${heading}</span>
      <p class="fault-clear" id="faultClear">${empty}</p>
      <ul class="fault-list">${faults}</ul>
    </div>
  </div>`;
}

function faceplateHtml() {
  if (controllerSheet()) {
    return `<section class="faceplate" id="faceplate">
      <div class="section-head">
        <div>
          <h2>Chiller display</h2>
          <p class="muted">Inlet and outlet temperature, compressor operation and run time, pump running, suction and discharge pressure, and the alarm description.</p>
        </div>
      </div>
      <div class="face-grid">
        ${analogTile("return_temp", "Inlet")}
        ${analogTile("supply_temp", "Outlet")}
        ${compressorOperationTiles()}
        ${runTile("evap_pump", "Pump")}
        ${analogTile("low_pressure", "Suction")}
        ${analogTile("high_pressure", "Discharge")}
        ${extraCircuitPressures()}
      </div>
      ${alarmFace(true)}
    </section>`;
  }
  return `<section class="faceplate" id="faceplate">
    <div class="section-head">
      <div>
        <h2>Chiller display</h2>
        <p class="muted">Outlet and inlet temperatures (flow and return), compressor load, high and low pressure, and the pump run state.</p>
      </div>
    </div>
    <div class="face-grid">
      ${analogTile("supply_temp", "Flow · outlet")}
      ${analogTile("return_temp", "Return · inlet")}
      ${loadTile()}
      ${runTile("evap_pump", "Pump")}
      ${analogTile("high_pressure", "High pressure")}
      ${analogTile("low_pressure", "Low pressure")}
    </div>
    ${alarmFace()}
  </section>`;
}

function faceplateOwnedIds() {
  if (!layoutOn("faceplate")) return new Set();
  const ids = new Set();
  const take = (point) => { if (point) ids.add(point.id); };
  take(bound("supply_temp"));
  take(bound("return_temp"));
  take(bound("evap_pump"));
  take(bound("high_pressure"));
  take(bound("low_pressure"));
  if (controllerSheet()) {
    const slots = compressorView().slots.filter((slot) => slot.run);
    const indexes = new Set(slots.map((slot) => slot.index));
    if (!indexes.size && bound("compressor")) indexes.add(1);
    for (const slot of slots) take(slot.run);
    for (const index of indexes) {
      take(pointById(`run_time_comp${index}_hour`));
      take(pointById(`run_time_comp${index}_min`));
    }
    take(pointById("comp_2_suction_pressure"));
    take(pointById("comp_2_discharge_pressure"));
    take(bound("alarm"));
    for (const point of faultPoints()) ids.add(point.id);
    return ids;
  }
  take(loadPoint());
  take(bound("alarm"));
  for (const point of faultPoints()) ids.add(point.id);
  return ids;
}

function loopShown(inletRole, outletRole) {
  if (S.customise) return true;
  return Boolean(bound(inletRole) || bound(outletRole));
}

function mimicHtml(site) {
  if (!layoutOn("mimic")) return "";
  const cold = loopShown("return_temp", "supply_temp")
    ? loop("cold", "return_temp", site.evap_label || "Evaporator", "evap_label", "supply_temp")
    : "";
  const hot = loopShown("condenser_in", "condenser_out")
    ? loop("hot", "condenser_in", site.cond_label || "Condenser", "cond_label", "condenser_out")
    : "";
  if (!cold && !hot) return "";
  return `<section class="mimic" id="mimic">${cold}${hot}</section>`;
}

function readingsHtml() {
  if (!layoutOn("readings")) return "";
  const roles = ["flow", "pressure"].filter((role) => S.customise || bound(role));
  if (!roles.length) return "";
  return `<section class="side-reads">${roles.map(readout).join("")}</section>`;
}

function compressorSectionShown() {
  if (!layoutOn("compressors")) return false;
  if (S.customise) return true;
  return compressorView().state !== "empty";
}

function statusHtml() {
  if (!layoutOn("status")) return "";
  const cards = lampCards();
  if (!cards) {
    if (!S.customise) return "";
    return `<h2 class="kicker" style="margin:6px 0">Status</h2><p class="muted">No status or alarm points. Set a point’s widget to Status or Alarm.</p>`;
  }
  return `<h2 class="kicker" style="margin:6px 0">Status</h2><section class="lamps" id="lamps">${cards}</section>`;
}

function outputsHtml() {
  if (!layoutOn("outputs")) return "";
  const cards = controlCards();
  if (!cards) {
    if (!S.customise) return "";
    return `<h2 class="kicker" style="margin:6px 0">Writable outputs</h2><p class="muted">No writable outputs. In the register map, mark a holding register or coil as writable and it will show up here.</p>`;
  }
  return `<h2 class="kicker" style="margin:6px 0">Writable outputs</h2><section class="controls" id="controls">${cards}</section>`;
}

function claimedPointIds() {
  const ids = faceplateOwnedIds();
  const take = (point) => { if (point) ids.add(point.id); };
  take(bound("chiller_name"));
  for (const role of heroRolesShown()) take(bound(role));
  if (layoutOn("mimic")) {
    if (loopShown("return_temp", "supply_temp")) {
      take(bound("return_temp"));
      take(bound("supply_temp"));
    }
    if (loopShown("condenser_in", "condenser_out")) {
      take(bound("condenser_in"));
      take(bound("condenser_out"));
    }
  }
  if (layoutOn("readings")) {
    for (const role of ["flow", "pressure"]) {
      if (S.customise || bound(role)) take(bound(role));
    }
  }
  if (layoutOn("status")) {
    for (const point of visiblePoints()) {
      if (point.widget === "status" || point.widget === "alarm") ids.add(point.id);
    }
  }
  if (layoutOn("outputs")) {
    for (const point of visiblePoints()) {
      if (point.writable) ids.add(point.id);
    }
  }
  if (compressorSectionShown() && compressorView().state !== "empty") {
    take(bound("compressor_count"));
    for (const index of compressorIndexes()) {
      take(bound(`comp_${index}_load`));
      take(bound(`comp_${index}_run`));
    }
  }
  return ids;
}

function profilePoints() {
  const claimed = claimedPointIds();
  return S.site.points
    .filter((point) => point.enabled && point.widget !== "hidden" && !claimed.has(point.id))
    .sort((a, b) => a.sort - b.sort || a.name.localeCompare(b.name));
}

function profileGroups(points) {
  const groups = [];
  const byName = new Map();
  for (const point of points) {
    const name = point.group || "General";
    if (!byName.has(name)) {
      const group = { name, points: [] };
      byName.set(name, group);
      groups.push(group);
    }
    byName.get(name).points.push(point);
  }
  return groups;
}

function profileWrite(point) {
  if (point.dtype === "bool" || point.function === "coil") {
    return `<div class="toggle" data-toggles="${esc(point.id)}">
      <button type="button" data-requires-connection data-action="write-bool" data-point="${esc(point.id)}" data-flag="true">${esc(point.on_label)}</button>
      <button type="button" data-requires-connection data-action="write-bool" data-point="${esc(point.id)}" data-flag="false">${esc(point.off_label)}</button>
    </div>`;
  }
  return settingForm(point);
}

function profileCard(point) {
  const id = esc(point.id);
  if (point.widget === "status" || point.widget === "alarm") {
    return `<article class="lamp-card profile-card" data-lamp="${id}" data-card="${id}">
      <span class="lamp"></span>
      <div>
        <strong>${esc(point.name)}</strong>
        <div data-value="${id}">—</div>
        <p class="muted profile-detail" data-detail="${id}"></p>
        ${point.writable ? profileWrite(point) : ""}
      </div>
    </article>`;
  }
  const numeric = point.dtype !== "bool" && point.function !== "coil";
  const gauge = point.widget === "gauge" || point.widget === "setpoint";
  return `<article class="profile-card" data-card="${id}">
    <span class="kicker">${esc(point.name)}</span>
    <div class="figure"><b data-value="${id}">—</b><small>${esc(point.unit)}</small></div>
    ${gauge && numeric ? `<div class="bar"><span data-bar="${id}"></span></div>` : ""}
    ${numeric ? `<svg class="spark" viewBox="0 0 120 32" preserveAspectRatio="none" aria-hidden="true"><polyline data-spark="${id}" points=""></polyline></svg>` : ""}
    <div class="profile-meta"><span class="tag" data-quality="${id}">—</span></div>
    <p class="muted profile-detail" data-detail="${id}"></p>
    ${point.writable ? profileWrite(point) : ""}
  </article>`;
}

function profileHtml() {
  if (!layoutOn("profile")) return "";
  const points = profilePoints();
  if (!points.length) {
    if (!S.customise) return "";
    return `<section class="profile-hmi"><h2>Register map</h2><p class="muted">Every enabled point is already drawn on the diagram above.</p></section>`;
  }
  const groups = profileGroups(points).map((group) => `
    <section class="profile-group">
      <h3 class="kicker">${esc(group.name)}</h3>
      <div class="profile-grid">${group.points.map(profileCard).join("")}</div>
    </section>`).join("");
  return `<section class="profile-hmi" id="profileHmi">
    <div class="section-head">
      <div>
        <h2>Register map</h2>
        <p class="muted" id="profileLead">Connect to read these points from the chiller over ${esc(protocolLabel(S.site.protocol))}.</p>
      </div>
    </div>
    ${groups}
  </section>`;
}

function customiseBar(site) {
  const sections = LAYOUT.map(([key, label]) => `
    <label class="inline"><input type="checkbox" data-layout="${key}"${layoutOn(key) ? " checked" : ""}> ${esc(label)}</label>`).join("");
  const drawn = site.points.filter((point) => point.enabled).map((point) => `
    <label>${esc(point.name)}
      <select data-widget="${esc(point.id)}">${WIDGETS.map(([value, label]) => `<option value="${esc(value)}"${point.widget === value ? " selected" : ""}>${esc(label)}</option>`).join("")}</select>
    </label>`).join("");
  return `<section class="customise">
    <div class="section-head">
      <div>
        <h2>Display</h2>
        <p class="muted">Choose which parts of this plant page are shown, which point fills each tile, and how that point is drawn. Register map draws every other enabled point from the Modbus profile and fills it when this site is connected. Addresses and scaling stay on the register map. Changes are saved with this site.</p>
      </div>
      <button type="button" class="primary" data-action="customise-done">Done</button>
    </div>
    <div class="check-row">${sections}</div>
    <div class="bindings">
      <label>Chiller name ${slotSelect("chiller_name")}</label>
      <label>Evaporator label <input data-label="evap_label" maxlength="40" value="${esc(site.evap_label || "Evaporator")}"></label>
      <label>Heat-rejection label <input data-label="cond_label" maxlength="40" value="${esc(site.cond_label || "Condenser")}"></label>
    </div>
    <details>
      <summary>How each point is drawn</summary>
      <div class="bindings">${drawn}</div>
    </details>
  </section>`;
}

function compressorSlots() {
  const roles = [
    ["compressor_count", "Fitted compressors"],
    ...compressorIndexes().flatMap((index) => [
      [`comp_${index}_load`, `Compressor ${index} load`],
      [`comp_${index}_run`, `Compressor ${index} run`],
    ]),
  ];
  return `<div class="bindings slot-grid">${roles.map(([role, label]) => `
    <label>${esc(label)} ${slotSelect(role)}</label>`).join("")}</div>`;
}

function slotSelect(roleId) {
  if (!S.customise) return "";
  const options = roleId === "chiller_name"
    ? textPointOptions(S.site.bindings[roleId])
    : pointOptions(S.site.bindings[roleId]);
  return `<select class="slot" data-binding="${esc(roleId)}">${options}</select>`;
}

function textPointOptions(selected) {
  const options = [`<option value="">Not shown</option>`];
  for (const point of S.site.points) {
    if (point.dtype !== "string") continue;
    options.push(`<option value="${esc(point.id)}"${point.id === selected ? " selected" : ""}>${esc(point.name)} · ${esc(addressLabel(point))}</option>`);
  }
  return options.join("");
}

function heroCard(roleId) {
  const meta = S.meta.roles.find((role) => role.id === roleId);
  const point = bound(roleId);
  if (!point) {
    return `<article class="hero-card missing"><span class="kicker">${esc(meta.label)}</span><b>Not assigned</b>${slotSelect(roleId)}</article>`;
  }
  return `<article class="hero-card" data-card="${esc(point.id)}">
    <span class="kicker">${esc(point.name)}</span>
    <div class="figure"><b data-value="${esc(point.id)}">—</b><small>${esc(point.unit)}</small></div>
    <div class="bar"><span data-bar="${esc(point.id)}"></span></div>
    <svg class="spark" viewBox="0 0 120 32" preserveAspectRatio="none" aria-hidden="true"><polyline data-spark="${esc(point.id)}" points=""></polyline></svg>
    ${slotSelect(roleId)}
  </article>`;
}

function loop(kind, inletRole, vessel, labelField, outletRole) {
  const name = S.customise
    ? `<input data-label="${esc(labelField)}" maxlength="40" value="${esc(vessel)}" aria-label="${esc(vessel)} label">`
    : `<strong>${esc(vessel)}</strong>`;
  return `<div class="loop ${kind}">
    ${node(inletRole)}
    <div class="pipe"></div>
    <div class="vessel">${name}</div>
    <div class="pipe"></div>
    ${node(outletRole)}
  </div>`;
}

function node(roleId) {
  const meta = S.meta.roles.find((role) => role.id === roleId);
  const point = bound(roleId);
  if (!point) return `<div class="node"><span class="kicker">${esc(meta.label)}</span><b>—</b>${slotSelect(roleId)}</div>`;
  return `<div class="node" data-card="${esc(point.id)}">
    <span class="kicker">${esc(point.name)}</span>
    <b data-value="${esc(point.id)}">—</b>
    <small>${esc(point.unit)}</small>
    ${slotSelect(roleId)}
  </div>`;
}

function readout(roleId) {
  const meta = S.meta.roles.find((role) => role.id === roleId);
  const point = bound(roleId);
  if (!point) return `<article class="readout"><span class="kicker">${esc(meta.label)}</span><b>—</b>${slotSelect(roleId)}</article>`;
  return `<article class="readout" data-card="${esc(point.id)}">
    <span class="kicker">${esc(point.name)}</span>
    <div class="figure"><b data-value="${esc(point.id)}">—</b><small>${esc(point.unit)}</small></div>
    ${slotSelect(roleId)}
  </article>`;
}

function visiblePoints() {
  return S.site.points.filter((point) => point.enabled && point.widget !== "hidden");
}

function lampCards() {
  const owned = faceplateOwnedIds();
  const points = visiblePoints().filter((point) => (point.widget === "status" || point.widget === "alarm") && !owned.has(point.id));
  if (!points.length) return "";
  return points.map((point) => `
    <article class="lamp-card" data-lamp="${esc(point.id)}">
      <span class="lamp"></span>
      <div><strong>${esc(point.name)}</strong><div data-value="${esc(point.id)}">—</div></div>
    </article>`).join("");
}

function controlCards() {
  const points = visiblePoints().filter((point) => point.writable);
  if (!points.length) return "";
  return points.map((point) => {
    const body = point.dtype === "bool" || point.function === "coil"
      ? `<div class="toggle" data-toggles="${esc(point.id)}">
          <button type="button" data-requires-connection data-action="write-bool" data-point="${esc(point.id)}" data-flag="true">${esc(point.on_label)}</button>
          <button type="button" data-requires-connection data-action="write-bool" data-point="${esc(point.id)}" data-flag="false">${esc(point.off_label)}</button>
        </div>`
      : settingForm(point);
    return `<article class="control"><span class="kicker">${esc(point.group)}</span><strong>${esc(point.name)}</strong><div data-value="${esc(point.id)}">—</div>${body}</article>`;
  }).join("");
}

function tableRows() {
  return visiblePoints().map((point) => `
    <tr data-action="edit-point" data-point="${esc(point.id)}">
      <td>${esc(point.name)}<div class="muted">${esc(point.group)}</div></td>
      <td class="num"><span data-value="${esc(point.id)}">—</span> ${esc(point.unit)}</td>
      <td class="raw" data-raw="${esc(point.id)}">—</td>
      <td><span class="tag" data-quality="${esc(point.id)}">—</span></td>
    </tr>`).join("");
}

function settingForm(point) {
  return `<form data-write-point="${esc(point.id)}" class="write-form">
    <div class="write-row">
      <input name="value" type="number" step="any" placeholder="${esc(point.unit)}" aria-label="New ${esc(point.name)}">
      <button class="primary" type="submit" data-requires-connection>Apply</button>
    </div>
    <p class="muted write-hint">Type a value to see the registers this setting will send. Nothing is written until you apply it.</p>
    <p class="wire-note" data-wire-note hidden></p>
  </form>`;
}

function sheetAddress(point) {
  if ((point.addressing || "modicon") === "protocol") return null;
  const spans = {
    holding: [40001, 49999, 400000],
    input: [30001, 39999, 300000],
    discrete: [10001, 19999, 100000],
    coil: [1, 9999, 0],
  };
  const span = spans[point.function];
  if (!span) return null;
  const number = Number(point.address_number);
  if (!Number.isFinite(number) || number < span[0] || number > span[1]) return null;
  const sheet = span[2] + (number - span[0] + 1);
  return sheet === number ? null : sheet;
}

function addressLabel(point) {
  const prefix = { holding: "4x", input: "3x", coil: "0x", discrete: "1x" }[point.function];
  const bit = point.bit === null || point.bit === undefined ? "" : ` bit ${point.bit}`;
  const sheet = sheetAddress(point);
  return `${prefix} ${point.address_number}${bit}${sheet ? ` · ${sheet}` : ""}`;
}

function compressorIndexes() {
  const found = (S.meta?.roles || [])
    .map((role) => /^comp_(\d+)_load$/.exec(role.id))
    .filter(Boolean)
    .map((match) => Number(match[1]));
  return found.length ? found.sort((a, b) => a - b) : [1, 2, 3, 4, 5, 6];
}

function compressorView() {
  const indexes = compressorIndexes();
  const limit = indexes.length ? indexes[indexes.length - 1] : 6;
  const countPoint = bound("compressor_count");
  const reading = countPoint ? readingFor(countPoint.id) : null;
  const good = Boolean(reading && reading.quality === "good" && typeof reading.value === "number" && Number.isFinite(reading.value));
  if (countPoint && !good) {
    return { state: "waiting", slots: [], countPoint, reported: null, raw: null };
  }
  if (good) {
    const raw = Math.round(reading.value);
    const shown = Math.max(0, Math.min(limit, raw));
    const slots = [];
    for (const index of indexes) {
      if (index > shown) break;
      slots.push({ index, load: bound(`comp_${index}_load`), run: bound(`comp_${index}_run`) });
    }
    return { state: "live", slots, countPoint, reported: shown, raw };
  }
  const slots = [];
  for (const index of indexes) {
    const load = bound(`comp_${index}_load`);
    const run = bound(`comp_${index}_run`);
    if (load || run) slots.push({ index, load, run });
  }
  return { state: slots.length ? "mapped" : "empty", slots, countPoint: null, reported: slots.length, raw: null };
}

function compressorCard(slot) {
  const title = slot.load?.name || slot.run?.name || `Compressor ${slot.index}`;
  const load = slot.load
    ? `<div class="figure"><b data-value="${esc(slot.load.id)}">—</b><small>${esc(slot.load.unit || "%")}</small></div>
       <div class="bar"><span data-bar="${esc(slot.load.id)}"></span></div>`
    : `<div class="figure"><b>—</b><small>%</small></div>`;
  const run = slot.run
    ? `<div class="state" data-comprun="${esc(slot.run.id)}"><span class="lamp"></span><span data-value="${esc(slot.run.id)}">—</span></div>`
    : "";
  const card = slot.load ? ` data-card="${esc(slot.load.id)}"` : "";
  return `<article class="comp-card"${card}>
    <span class="kicker">${esc(title)}</span>
    ${load}
    ${run}
  </article>`;
}

function paintCompressors() {
  const grid = document.getElementById("compressorGrid");
  const summary = document.getElementById("compressorSummary");
  const stepper = document.getElementById("compressorStepper");
  if (!grid || !S.site) return;
  const view = compressorView();
  const key = [
    view.state,
    view.raw,
    view.reported,
    view.slots.map((slot) => `${slot.index}:${slot.load?.id || ""}:${slot.run?.id || ""}`).join(","),
  ].join("|");
  if (summary) summary.textContent = compressorSummary(view);
  if (stepper) {
    const writable = Boolean(view.countPoint && view.countPoint.writable);
    stepper.hidden = !writable;
    stepper.querySelectorAll("button").forEach((button) => {
      button.setAttribute("aria-pressed", Number(button.dataset.count) === view.reported ? "true" : "false");
    });
  }
  if (key === compressorKey && grid.childElementCount === view.slots.length) return;
  compressorKey = key;
  grid.innerHTML = view.slots.map(compressorCard).join("");
}

function compressorSummary(view) {
  if (view.state === "waiting") return "Waiting for the controller to report how many compressors are fitted.";
  if (view.state === "empty") return "Bind a fitted-compressor count, or each compressor load, in the register map.";
  const count = view.reported;
  const noun = count === 1 ? "compressor" : "compressors";
  if (view.state === "mapped") return `${count} ${noun} on this map.`;
  if (view.raw != null && view.raw > count) return `Controller reports ${view.raw}. Showing ${count}.`;
  if (!count) return "The controller reports no compressors.";
  return `${count} ${noun} fitted`;
}

function paintLive() {
  paintHeader();
  paintCompressors();
  const title = document.getElementById("plantTitle");
  if (title && S.site) title.textContent = plantTitle();
  const flag = document.getElementById("demoFlag");
  if (flag) {
    const showing = Boolean(S.live && S.live.demo && S.live.site_id === S.siteId);
    flag.hidden = !showing;
    if (showing) {
      const sized = /^demo-(\d+)$/.exec(S.live.site_id);
      if (sized) {
        const count = Number(sized[1]);
        const noun = count === 1 ? "compressor" : "compressors";
        flag.textContent = `Demo with ${count} ${noun}.`;
      } else {
        flag.textContent = "Demo controller on this computer. Supply temperature alarms above its high limit so the banner can be checked.";
      }
    }
  }
  const detail = document.getElementById("commsDetail");
  if (detail && S.site) {
    if (!S.live || S.live.site_id !== S.siteId) {
      detail.textContent = "Connect to start reading the controller.";
    } else {
      const vpn = S.live.vpn?.state === "up" || S.live.vpn?.state === "error" ? `${S.live.vpn.detail} · ` : "";
      const rtt = S.live.rtt_ms != null ? ` · ${S.live.rtt_ms} ms` : "";
      detail.textContent = `${vpn}${S.live.modbus.detail || ""}${rtt}`.trim();
    }
  }
  const lead = document.getElementById("profileLead");
  if (lead && S.site) {
    if (!S.live || S.live.site_id !== S.siteId) {
      lead.textContent = `Connect to read these points from the chiller over ${protocolLabel(S.site.protocol)}.`;
    } else if (S.live.modbus.state === "polling") {
      const via = protocolLabel(S.live.modbus.protocol);
      lead.textContent = `Live from ${S.live.modbus.host}:${S.live.modbus.port} over ${via}, unit ${S.live.modbus.unit_id}. Each tile follows a point on this register map.`;
    } else if (S.live.modbus.state === "connecting") {
      lead.textContent = `Opening ${protocolLabel(S.live.modbus.protocol)}…`;
    } else if (S.live.modbus.state === "error") {
      lead.textContent = S.live.modbus.detail || "The controller did not answer.";
    } else {
      lead.textContent = `Connect to read these points from the chiller over ${protocolLabel(S.site.protocol)}.`;
    }
  }
  const banner = document.getElementById("alarmBanner");
  if (banner && S.site) {
    const faults = faultPoints().map((point) => shownFault(point, readingFor(point.id))).filter(Boolean);
    banner.hidden = faults.length === 0;
    banner.textContent = faults.length ? `Alarm · ${faults.join(", ")}` : "";
  }
  document.querySelectorAll("[data-fault]").forEach((el) => {
    const point = pointById(el.dataset.fault);
    const message = point ? shownFault(point, readingFor(el.dataset.fault)) : "";
    el.hidden = !message;
    const text = el.querySelector("[data-fault-text]");
    if (text) text.textContent = message;
  });
  const faultBox = document.getElementById("faultBox");
  const faultClear = document.getElementById("faultClear");
  if (faultBox && faultClear && S.site) {
    const tripped = faultBox.querySelector("[data-fault]:not([hidden])");
    const alarmPoint = bound("alarm");
    const alarmReading = alarmPoint ? readingFor(alarmPoint.id) : null;
    const alarmOn = Boolean(alarmReading && alarmReading.quality === "good" && alarmReading.value);
    faultBox.classList.toggle("tripped", Boolean(tripped) || alarmOn);
    faultClear.hidden = Boolean(tripped);
    const messages = [...faultBox.querySelectorAll("[data-fault]:not([hidden]) strong")].map((el) => el.textContent.trim());
    const summary = document.querySelector("[data-alarm-summary]");
    const connectedHere = Boolean(S.live && S.live.site_id === S.siteId);
    if (summary) {
      if (messages.length || alarmOn) summary.textContent = "Alarm";
      else if (connectedHere && alarmReading && alarmReading.quality === "good") summary.textContent = alarmReading.display || "Normal";
      else summary.textContent = "—";
    }
    const described = faultBox.dataset.kind === "description";
    if (!connectedHere) {
      faultClear.textContent = described
        ? "Connect to read the alarm description from the controller."
        : "Connect to read the alarm message from the controller.";
    } else if (alarmOn) {
      faultClear.textContent = described
        ? "Alarm is on. The controller has not output a description."
        : "Alarm is on. The controller has not output a fault message.";
    } else {
      faultClear.textContent = described ? "No alarm description." : "No fault from the controller.";
    }
  }
  document.querySelectorAll("[data-runtime]").forEach((el) => {
    const index = el.dataset.runtime;
    const text = el.querySelector("[data-runtime-text]");
    if (!text) return;
    const parts = [];
    const hour = readingFor(`run_time_comp${index}_hour`);
    const minute = readingFor(`run_time_comp${index}_min`);
    if (hour && hour.quality === "good") parts.push(`${hour.display} h`);
    if (minute && minute.quality === "good") parts.push(`${minute.display} min`);
    text.textContent = parts.length ? parts.join(" ") : "—";
  });
  if (!S.site) return;
  document.querySelectorAll("[data-value]").forEach((el) => {
    const reading = readingFor(el.dataset.value);
    el.textContent = reading?.display || "—";
  });
  document.querySelectorAll("[data-raw]").forEach((el) => {
    const reading = readingFor(el.dataset.raw);
    el.textContent = reading?.raw?.length ? reading.raw.join(", ") : "—";
  });
  document.querySelectorAll("[data-quality]").forEach((el) => {
    const reading = readingFor(el.dataset.quality);
    const quality = reading?.quality || "bad";
    el.textContent = quality;
    el.className = `tag ${quality}`;
  });
  document.querySelectorAll("[data-detail]").forEach((el) => {
    const reading = readingFor(el.dataset.detail);
    el.textContent = reading?.quality === "good" ? "" : (reading?.detail || "");
  });
  document.querySelectorAll("[data-card]").forEach((el) => {
    const reading = readingFor(el.dataset.card);
    el.classList.toggle("alarm", Boolean(reading && reading.quality === "good" && reading.alarm));
    el.classList.toggle("stale", Boolean(reading && reading.quality !== "good"));
  });
  document.querySelectorAll("[data-bar]").forEach((el) => {
    const point = pointById(el.dataset.bar);
    const reading = readingFor(el.dataset.bar);
    const value = reading?.value;
    if (!point || typeof value !== "number") {
      el.style.width = "0%";
      return;
    }
    const span = point.gauge_max - point.gauge_min;
    const pct = span ? Math.max(0, Math.min(100, ((value - point.gauge_min) / span) * 100)) : 0;
    el.style.width = `${pct}%`;
  });
  document.querySelectorAll("[data-spark]").forEach((el) => {
    const series = S.live && S.live.site_id === S.siteId ? S.live.history?.[el.dataset.spark] : null;
    el.setAttribute("points", sparkPoints(series));
  });
  document.querySelectorAll("[data-comprun]").forEach((el) => {
    const reading = readingFor(el.dataset.comprun);
    const on = Boolean(reading && reading.quality === "good" && reading.value);
    const card = el.closest(".comp-card");
    if (card) card.classList.toggle("off", Boolean(reading && reading.quality === "good" && !reading.value));
    const lamp = el.querySelector(".lamp");
    if (!lamp) return;
    lamp.className = "lamp";
    if (reading?.quality === "good" && on) lamp.classList.add("ok");
    else if (reading?.quality === "stale") lamp.classList.add("wait");
  });
  document.querySelectorAll("[data-lamp]").forEach((el) => {
    const point = pointById(el.dataset.lamp);
    const reading = readingFor(el.dataset.lamp);
    const on = Boolean(reading && reading.value);
    el.classList.toggle("on", Boolean(point && point.widget === "status" && on && reading.quality === "good"));
    el.classList.toggle("alarm-on", Boolean(point && point.widget === "alarm" && on && reading.quality === "good"));
    const lamp = el.querySelector(".lamp");
    lamp.className = "lamp";
    if (reading?.quality === "good" && point?.widget === "alarm") lamp.classList.add(on ? "bad" : "ok");
    else if (reading?.quality === "good" && on) lamp.classList.add("ok");
    else if (reading?.quality === "stale") lamp.classList.add("wait");
  });
  document.querySelectorAll("[data-toggles]").forEach((el) => {
    const reading = readingFor(el.dataset.toggles);
    el.querySelectorAll("button").forEach((button) => {
      const want = button.dataset.flag === "true";
      button.classList.toggle("selected", Boolean(reading && reading.quality === "good" && Boolean(reading.value) === want));
    });
  });
  document.querySelectorAll("tr[data-point]").forEach((row) => {
    const reading = readingFor(row.dataset.point);
    row.classList.toggle("alarm", Boolean(reading && reading.alarm && reading.quality === "good"));
    row.classList.toggle("stale", Boolean(reading && reading.quality !== "good"));
  });
  const liveLink = Boolean(S.live && S.live.site_id === S.siteId && S.live.modbus.state !== "idle");
  document.querySelectorAll("[data-requires-connection]").forEach((el) => {
    el.disabled = !liveLink || busy;
  });
  const mimic = document.getElementById("mimic");
  if (mimic) mimic.classList.toggle("live", connected());
  const vpnState = document.getElementById("vpnState");
  if (vpnState && S.live && S.live.site_id === S.siteId) vpnState.textContent = S.live.vpn?.detail || "";
}

function sparkPoints(values) {
  if (!values || values.length < 2) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  return values.map((value, index) => {
    const x = (index / (values.length - 1)) * 120;
    const y = 30 - ((value - min) / span) * 28;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function renderMap(main) {
  const site = S.site;
  if (!S.pointId || !pointById(S.pointId)) S.pointId = site.points[0]?.id || null;
  const point = pointById(S.pointId);
  main.innerHTML = `
    <p class="help">This register map is the Modbus profile. Connect, or choose Start live HMI on the connection page, and the plant page shows each enabled point from the live controller. Match area, address, type, and scale to the controller manual before trusting the numbers. The controller sheet writes holding registers as 400001. The same register is Modicon 40001, shown beside it.</p>
    <div class="toolbar">
      <input id="pointSearch" type="search" placeholder="Filter points">
      <div class="actions">
        <button type="button" data-action="add-point">Add point</button>
        <button type="button" data-action="export">Export map</button>
        <label class="inline">Import <input id="importFile" type="file" accept="application/json,.json"></label>
        <button type="button" data-action="one-compressor">Load 1-compressor list</button>
        <button type="button" data-action="two-compressor">Load 2-compressor list</button>
        <button type="button" class="danger" data-action="template">Reload chiller template</button>
      </div>
    </div>
    <div class="split">
      <div class="point-list" id="pointList">${pointButtons()}</div>
      <section class="panel" id="pointPanel">${point ? pointForm(point) : "<p>Add a point to begin.</p>"}</section>
    </div>`;
  wireHint();
}


function pointOptions(selected) {
  const options = [`<option value="">Not shown</option>`];
  for (const point of S.site.points) {
    options.push(`<option value="${esc(point.id)}"${point.id === selected ? " selected" : ""}>${esc(point.name)} · ${esc(addressLabel(point))}</option>`);
  }
  return options.join("");
}

function pointButtons() {
  return S.site.points.map((point) => `
    <button type="button" data-action="edit-point" data-point="${esc(point.id)}" class="${point.id === S.pointId ? "active" : ""}">
      ${esc(point.name)}
      <small>${esc(point.group)} · ${esc(addressLabel(point))}${point.writable ? " · writable" : ""}</small>
    </button>`).join("");
}

function pointForm(point) {
  const dtype = ["bool", "uint16", "int16", "uint32", "int32", "float32", "float64", "string"];
  const areas = [["holding", "Holding (4x)"], ["input", "Input (3x)"], ["coil", "Coil (0x)"], ["discrete", "Discrete (1x)"]];
  const orders = ["ABCD", "CDAB", "BADC", "DCBA"];
  const select = (name, options, current) => `<select name="${name}">${options.map(([value, label]) => `<option value="${esc(value)}"${value === current ? " selected" : ""}>${esc(label)}</option>`).join("")}</select>`;
  const num = (name, value, step = "any") => `<input name="${name}" type="number" step="${step}" value="${value ?? ""}">`;
  return `<form id="pointForm" data-id="${esc(point.id)}">
    <div class="split-head"><h2>${esc(point.name)}</h2><span class="muted">${esc(point.id)}</span></div>
    <div class="form-grid">
      <label>Name <input name="name" required maxlength="80" value="${esc(point.name)}"></label>
      <label>Group <input name="group" maxlength="40" value="${esc(point.group)}"></label>
      <label>Area ${select("function", areas, point.function)}</label>
      <label>Address style ${select("addressing", [["modicon", "Modicon (40001)"], ["protocol", "Protocol (0-based)"]], point.addressing)}</label>
      <label>Address ${num("address_number", point.address_number, "1")}</label>
      <label>Data type ${select("dtype", dtype.map((item) => [item, item]), point.dtype)}</label>
      <label>Byte order ${select("byte_order", orders.map((item) => [item, item]), point.byte_order)}</label>
      <label>Bit (packed word) <input name="bit" type="number" min="0" max="15" step="1" value="${point.bit ?? ""}" placeholder="empty = whole register"></label>
      <label>Scale ${num("scale", point.scale)}</label>
      <label>Offset ${num("offset", point.offset)}</label>
      <label>Decimals ${num("decimals", point.decimals, "1")}</label>
      <label>Text length <input name="string_chars" type="number" min="1" max="40" step="1" value="${esc(point.string_chars ?? 16)}"></label>
      <label>Unit <input name="unit" maxlength="16" value="${esc(point.unit)}"></label>
      <label>Widget ${select("widget", WIDGETS, point.widget)}</label>
      <label>Gauge min ${num("gauge_min", point.gauge_min)}</label>
      <label>Gauge max ${num("gauge_max", point.gauge_max)}</label>
      <label>Alarm low <input name="alarm_low" type="number" step="any" value="${point.alarm_low ?? ""}"></label>
      <label>Alarm high <input name="alarm_high" type="number" step="any" value="${point.alarm_high ?? ""}"></label>
      <label>Write min <input name="write_min" type="number" step="any" value="${point.write_min ?? ""}"></label>
      <label>Write max <input name="write_max" type="number" step="any" value="${point.write_max ?? ""}"></label>
      <label>On text <input name="on_label" maxlength="24" value="${esc(point.on_label)}"></label>
      <label>Off text <input name="off_label" maxlength="24" value="${esc(point.off_label)}"></label>
    </div>
    <p id="wireHint"></p>
    <div class="check-row">
      ${check("enabled", "Enabled", point.enabled)}
      ${check("writable", "Writable output", point.writable)}
      ${check("force_fc16", "Write with function 16", point.force_fc16)}
      ${check("invert", "Invert boolean", point.invert)}
    </div>
    <label>Notes <textarea name="notes" maxlength="300">${esc(point.notes)}</textarea></label>
    <div class="form-grid" style="margin-top:12px">
      <label>Sample raw words <input id="sampleRaw" placeholder="72 or 16624, 0"></label>
      <div class="form-actions" style="align-items:end">
        <button type="button" data-action="preview">Decode sample</button>
        <span id="previewOut"></span>
      </div>
    </div>
    <div class="form-grid" style="margin-top:12px">
      <label>Try a setting <input id="sampleSetting" type="number" step="any" placeholder="7.5"></label>
      <div class="form-actions" style="align-items:end">
        <button type="button" data-action="preview-setting">Show the registers</button>
      </div>
    </div>
    <p class="help">Type the engineering value, then show the registers. The same note appears under Apply before the controller is written.</p>
    <p id="settingOut" class="wire-note" hidden></p>
    <div class="form-actions" style="margin-top:14px">
      <button class="primary" type="submit">Save point</button>
      <button type="button" data-action="move" data-dir="up">Move up</button>
      <button type="button" data-action="move" data-dir="down">Move down</button>
      <button type="button" class="danger" data-action="delete-point">Delete</button>
    </div>
  </form>`;
}

function check(name, label, on) {
  return `<label class="inline"><input type="checkbox" name="${name}"${on ? " checked" : ""}> ${esc(label)}</label>`;
}

function wireAddress(fn, number, mode) {
  if (mode === "protocol") {
    if (number < 0) throw new Error("Protocol address must be 0 or greater");
    return number;
  }
  const span = fn === "coil" ? [1, 9999] : fn === "discrete" ? [10001, 19999] : fn === "input" ? [30001, 39999] : [40001, 49999];
  if (number < span[0] || number > span[1]) throw new Error(`Use ${span[0]}–${span[1]} for this area`);
  return number - BASE[fn];
}

function wireHint() {
  const form = document.getElementById("pointForm");
  const el = document.getElementById("wireHint");
  if (!form || !el) return;
  try {
    const wire = wireAddress(form.elements.function.value, Number(form.elements.address_number.value), form.elements.addressing.value);
    el.textContent = `On the wire: address ${wire}, function ${FC[form.elements.function.value]}`;
  } catch (error) {
    el.textContent = error.message;
  }
}

function collectPoint(form) {
  const value = (name) => form.elements[name].value;
  const optional = (name) => (value(name) === "" ? null : Number(value(name)));
  return {
    id: form.dataset.id,
    name: value("name").trim(),
    group: value("group").trim(),
    notes: value("notes"),
    function: value("function"),
    addressing: value("addressing"),
    address_number: Number(value("address_number")),
    dtype: value("dtype"),
    byte_order: value("byte_order"),
    bit: optional("bit"),
    scale: Number(value("scale")),
    offset: Number(value("offset")),
    decimals: Number(value("decimals")),
    string_chars: Number(value("string_chars")),
    unit: value("unit"),
    widget: value("widget"),
    gauge_min: Number(value("gauge_min")),
    gauge_max: Number(value("gauge_max")),
    alarm_low: optional("alarm_low"),
    alarm_high: optional("alarm_high"),
    write_min: optional("write_min"),
    write_max: optional("write_max"),
    on_label: value("on_label"),
    off_label: value("off_label"),
    enabled: form.elements.enabled.checked,
    writable: form.elements.writable.checked,
    force_fc16: form.elements.force_fc16.checked,
    invert: form.elements.invert.checked,
  };
}

function protocolLabel(protocol) {
  return protocol === "rtu" ? "RTU over TCP" : "Modbus TCP";
}

function renderLink(main) {
  const site = S.site;
  const protocol = site.protocol === "rtu" ? "rtu" : "tcp";
  const interFrame = site.inter_frame_ms ?? (protocol === "rtu" ? 20 : 0);
  main.innerHTML = `
    <section class="panel">
      <h2>Connection</h2>
      <p class="help">Same connection Modbus Monitor uses. This program does not log into the RUT. Join the network on this laptop first, then open the socket.</p>
      <p class="help">Modbus TCP is for RutOS Services → Modbus → Modbus TCP over Serial Gateway. The router turns each request into RTU on RS485. RTU over TCP is for Services → Serial Utilities → Over IP, with Raw mode on: the router forwards the serial bytes unchanged, and this program sends the RTU frames Modbus Monitor sends when Interface is TCP and Protocol is RTU.</p>
      <p class="help">On site, join the RUT Wi-Fi or the site LAN. The address is the RUT when it is gatewaying the chiller, or the controller when it already speaks Modbus TCP. Away from site, bring up the laptop VPN or RMS path first. A socket that stays quiet for the link timeout is opened again.</p>
      <form id="linkForm">
        <div class="form-grid">
          <label>Site name <input name="name" required maxlength="80" value="${esc(site.name)}"></label>
          <label>Location <input name="location" maxlength="120" value="${esc(site.location)}"></label>
          <label>Protocol <select name="protocol">
            <option value="tcp"${protocol === "tcp" ? " selected" : ""}>Modbus TCP</option>
            <option value="rtu"${protocol === "rtu" ? " selected" : ""}>RTU over TCP</option>
          </select></label>
          <label>IP address <input name="modbus_host" required value="${esc(site.modbus_host)}"></label>
          <label>Port <input name="modbus_port" type="number" min="1" max="65535" value="${esc(site.modbus_port)}"></label>
          <label>Unit id <input name="unit_id" type="number" min="0" max="255" value="${esc(site.unit_id)}"></label>
          <label>Response timeout (s) <input name="timeout_s" type="number" min="0.2" max="30" step="0.1" value="${esc(site.timeout_s)}"></label>
          <label>Retries <input name="retries" type="number" min="1" max="10" step="1" value="${esc(site.retries ?? 3)}"></label>
          <label>Link timeout (s) <input name="link_timeout_s" type="number" min="1" max="120" step="1" value="${esc(site.link_timeout_s ?? 30)}"></label>
          <label>Inter-frame (ms) <input name="inter_frame_ms" type="number" min="0" max="10000" step="1" value="${esc(interFrame)}"></label>
          <label>Poll (ms) <input name="poll_ms" type="number" min="200" max="60000" step="100" value="${esc(site.poll_ms)}"></label>
        </div>
        <p class="help">Inter-frame is the pause between requests. Modbus Monitor’s default is 20 ms, which gives the RUT time to turn the RS485 line around.</p>
        <label>Notes <textarea name="notes">${esc(site.notes)}</textarea></label>
        <div class="form-actions" style="margin-top:12px">
          <button class="primary" type="button" data-action="live-hmi">Start live HMI</button>
          <button type="submit">Save connection</button>
          <button type="button" data-action="test-link">Test Modbus</button>
        </div>
        <p id="testOut"></p>
      </form>
    </section>
    <section class="panel">
      <h2>Remove this site</h2>
      <p class="help">Deletes the saved map from this computer. It does not change the router or the chiller.</p>
      <button type="button" class="danger" data-action="delete-site">Delete site</button>
    </section>`;
}

function linkPayload(form) {
  const value = (name) => form.elements[name].value;
  return {
    name: value("name").trim(),
    location: value("location").trim(),
    notes: value("notes"),
    modbus_host: value("modbus_host").trim(),
    modbus_port: Number(value("modbus_port")),
    unit_id: Number(value("unit_id")),
    timeout_s: Number(value("timeout_s")),
    retries: Number(value("retries")),
    link_timeout_s: Number(value("link_timeout_s")),
    poll_ms: Number(value("poll_ms")),
    protocol: value("protocol") === "rtu" ? "rtu" : "tcp",
    inter_frame_ms: Number(value("inter_frame_ms")),
  };
}

async function refreshSites(selectId) {
  S.sites = await api("/api/sites");
  if (selectId) S.siteId = selectId;
  if (S.siteId && !S.sites.some((site) => site.id === S.siteId)) S.siteId = null;
  if (!S.siteId && S.sites.length) S.siteId = S.sites[0].id;
  if (S.siteId) S.site = await api(`/api/sites/${S.siteId}`);
  else S.site = null;
  render();
}

async function onClick(event) {
  const button = event.target.closest("[data-action], [data-view]");
  if (!button) return;
  if (button.dataset.view) {
    S.view = button.dataset.view;
    render();
    return;
  }
  const action = button.dataset.action;
  if (action && action.startsWith("mapper-")) {
    await onMapperAction(action);
    return;
  }
  if (action === "close-modal") {
    document.getElementById("modal").hidden = true;
    return;
  }
  if (action === "add-site") {
    document.getElementById("modal").hidden = false;
    document.querySelector("#newSiteForm input[name=name]").focus();
    return;
  }
  if (action === "edit-point") {
    S.pointId = button.dataset.point;
    S.view = "map";
    render();
    return;
  }
  if (action === "customise") {
    S.customise = true;
    S.view = "plant";
    render();
    return;
  }
  if (action === "customise-done") {
    S.customise = false;
    render();
    return;
  }
  if (action === "toggle-connect") {
    await guard(async () => {
      if (!S.site) return;
      if (sessionOpen()) {
        S.live = await api(`/api/sites/${S.site.id}/disconnect`, { method: "POST" });
        toast("Disconnected", true);
      } else {
        S.live = await api(`/api/sites/${S.site.id}/connect`, { method: "POST" });
        S.view = "plant";
        render();
        toast("Connected", true);
      }
      paintLive();
    });
    return;
  }
  if (action === "install-update") {
    await guard(async () => {
      const result = await api("/api/update/install", { method: "POST" });
      toast(result.detail || "Installing the update", true);
    });
    return;
  }
  if (action === "demo") {
    await guard(async () => {
      if (S.live?.simulator_running && S.live.site_id === "demo") {
        S.live = await api("/api/demo/stop", { method: "POST" });
        await refreshSites(S.siteId);
        toast("Demo stopped", true);
      } else {
        S.live = await api("/api/demo/start", { method: "POST" });
        await refreshSites("demo");
        S.view = "plant";
        render();
        toast("Demo chiller is running", true);
      }
    });
    return;
  }
  if (action === "demo-size") {
    const count = Number(button.dataset.count);
    await guard(async () => {
      S.live = await api(`/api/demo/compressors/${count}`, { method: "POST" });
      await refreshSites(`demo-${count}`);
      S.view = "plant";
      render();
      const noun = count === 1 ? "compressor" : "compressors";
      toast(`Demo with ${count} ${noun} is running`, true);
    });
    return;
  }
  if (!S.site) return;
  if (action === "add-point") {
    await guard(async () => {
      const result = await api(`/api/sites/${S.site.id}/points`, { method: "POST" });
      S.site = result.site;
      S.pointId = result.point_id;
      S.view = "map";
      render();
    });
  } else if (action === "delete-point") {
    if (!confirm("Delete this point from the map?")) return;
    await guard(async () => {
      S.site = await api(`/api/sites/${S.site.id}/points/${S.pointId}`, { method: "DELETE" });
      S.pointId = S.site.points[0]?.id || null;
      render();
    });
  } else if (action === "move") {
    await guard(async () => {
      S.site = await api(`/api/sites/${S.site.id}/points/${S.pointId}/move`, {
        method: "POST",
        body: { direction: button.dataset.dir },
      });
      render();
    });
  } else if (action === "template") {
    if (!confirm("Replace the register map and display bindings with the chilled-water template?")) return;
    await guard(async () => {
      S.site = await api(`/api/sites/${S.site.id}/template`, { method: "POST" });
      S.pointId = null;
      render();
      toast("Template loaded", true);
    });
  } else if (action === "one-compressor") {
    if (!confirm("Replace this register map with the 1-compressor controller list, 400001 to 400078? Rows the sheet does not list are left out.")) return;
    await guard(async () => {
      S.site = await api(`/api/sites/${S.site.id}/profile/one-compressor`, { method: "POST" });
      S.pointId = null;
      render();
      toast("1-compressor list loaded", true);
    });
  } else if (action === "two-compressor") {
    if (!confirm("Replace this register map with the 2-compressor controller list, 400001 to 401005? Rows the sheet does not list are left out.")) return;
    await guard(async () => {
      S.site = await api(`/api/sites/${S.site.id}/profile/two-compressor`, { method: "POST" });
      S.pointId = null;
      render();
      toast("2-compressor list loaded", true);
    });
  } else if (action === "export") {
    await guard(async () => {
      const map = await api(`/api/sites/${S.site.id}/export`);
      const blob = new Blob([JSON.stringify(map, null, 2)], { type: "application/json" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `${S.site.name.replace(/\s+/g, "-").toLowerCase()}-map.json`;
      link.click();
      URL.revokeObjectURL(link.href);
    });
  } else if (action === "live-hmi") {
    await guard(async () => {
      const form = document.getElementById("linkForm");
      if (form) {
        S.site = await api(`/api/sites/${S.site.id}`, { method: "PUT", body: linkPayload(form) });
      }
      if (!sessionOpen()) {
        S.live = await api(`/api/sites/${S.site.id}/connect`, { method: "POST" });
      }
      S.customise = false;
      S.view = "plant";
      render();
      toast("Live HMI is reading this register map", true);
    });
  } else if (action === "test-link") {
    await guard(async () => {
      const form = document.getElementById("linkForm");
      if (form) {
        S.site = await api(`/api/sites/${S.site.id}`, { method: "PUT", body: linkPayload(form) });
      }
      const result = await api(`/api/sites/${S.site.id}/test`, { method: "POST" });
      const out = document.getElementById("testOut");
      if (out) out.textContent = result.detail;
      toast(result.modbus ? "Modbus responded" : "Modbus test failed", result.modbus);
    });
  } else if (action === "delete-site") {
    if (!confirm(`Delete ${S.site.name}?`)) return;
    await guard(async () => {
      if (sessionOpen()) await api(`/api/sites/${S.site.id}/disconnect`, { method: "POST" });
      await api(`/api/sites/${S.site.id}`, { method: "DELETE" });
      S.siteId = null;
      S.view = "plant";
      await refreshSites();
      toast("Site deleted", true);
    });
  } else if (action === "preview") {
    await guard(async () => {
      const form = document.getElementById("pointForm");
      const raw = document.getElementById("sampleRaw").value.trim();
      const registers = raw ? raw.split(/[,\s]+/).map(Number) : [];
      const result = await api("/api/preview", { method: "POST", body: { point: collectPoint(form), registers } });
      document.getElementById("previewOut").textContent = `${result.display}`;
    });
  } else if (action === "preview-setting") {
    const form = document.getElementById("pointForm");
    const out = document.getElementById("settingOut");
    const raw = document.getElementById("sampleSetting").value.trim();
    const value = Number(raw);
    if (!out) return;
    if (raw === "" || !Number.isFinite(value)) {
      out.hidden = false;
      out.textContent = "Enter a number to see the registers.";
      return;
    }
    await guard(async () => {
      try {
        const plan = await api("/api/write-plan", { method: "POST", body: { point: collectPoint(form), value } });
        out.hidden = false;
        out.textContent = plan.text;
      } catch (error) {
        out.hidden = false;
        out.textContent = error.message;
        throw error;
      }
    });
  } else if (action === "write-count") {
    const point = bound("compressor_count");
    const count = Number(button.dataset.count);
    if (!point || !point.writable || !Number.isInteger(count)) return;
    if (!confirm(`Write ${count} fitted compressors to ${point.name}?`)) return;
    await guard(async () => {
      await api(`/api/sites/${S.site.id}/write`, { method: "POST", body: { point_id: point.id, value: count } });
      toast(`${count} compressors fitted`, true);
    });
  } else if (action === "write-bool") {
    const point = pointById(button.dataset.point);
    const value = button.dataset.flag === "true";
    if (!point || !confirm(`Write ${value ? point.on_label : point.off_label} to ${point.name}?`)) return;
    await guard(async () => {
      await api(`/api/sites/${S.site.id}/write`, { method: "POST", body: { point_id: point.id, value } });
      toast(`Wrote ${point.name}`, true);
    });
  }
}

async function onSubmit(event) {
  const form = event.target;
  if (form.id === "newSiteForm") {
    event.preventDefault();
    await guard(async () => {
      const site = await api("/api/sites", { method: "POST", body: { name: form.elements.name.value } });
      document.getElementById("modal").hidden = true;
      form.reset();
      S.view = "link";
      await refreshSites(site.id);
      toast("Site created. Set the Modbus address, then match the map to the controller.", true);
    });
  } else if (form.id === "linkForm") {
    event.preventDefault();
    await guard(async () => {
      S.site = await api(`/api/sites/${S.site.id}`, { method: "PUT", body: linkPayload(form) });
      const listed = S.sites.find((site) => site.id === S.site.id);
      if (listed) listed.name = S.site.name;
      fillSiteSelect();
      toast("Link saved", true);
    });
  } else if (form.id === "pointForm") {
    event.preventDefault();
    await guard(async () => {
      S.site = await api(`/api/sites/${S.site.id}/points/${form.dataset.id}`, {
        method: "PUT",
        body: collectPoint(form),
      });
      render();
      toast("Point saved", true);
    });
  } else if (form.dataset.writePoint) {
    event.preventDefault();
    const point = pointById(form.dataset.writePoint);
    const value = Number(form.elements.value.value);
    const note = form.querySelector("[data-wire-note]");
    if (!point || !Number.isFinite(value)) {
      toast("Enter a number to write");
      return;
    }
    let plan;
    try {
      plan = await api("/api/write-plan", { method: "POST", body: { point, value } });
    } catch (error) {
      if (note) {
        note.hidden = false;
        note.textContent = error.message;
      }
      toast(error.message);
      return;
    }
    if (note) {
      note.hidden = false;
      note.textContent = plan.text;
    }
    if (!confirm(`${plan.text}\n\nWrite this to ${point.name} on the controller?`)) return;
    await guard(async () => {
      await api(`/api/sites/${S.site.id}/write`, {
        method: "POST",
        body: { point_id: point.id, value },
      });
      form.elements.value.value = "";
      if (note) {
        note.hidden = true;
        note.textContent = "";
      }
      toast(`Wrote ${point.name}`, true);
    });
  }
}

async function onChange(event) {
  const target = event.target;
  if (target.name === "protocol" && target.form && target.form.id === "linkForm") {
    const inter = target.form.elements.inter_frame_ms;
    if (target.value === "rtu" && inter && Number(inter.value) === 0) inter.value = 20;
    return;
  }
  if (target.id === "mapperMapping" || target.id === "mapperReplace") {
    await guard(async () => {
      S.mapper = await api("/api/mapper/settings", {
        method: "PUT",
        body: {
          ...mapperSettingsBody(),
          mapping: document.getElementById("mapperMapping").checked,
          replace: document.getElementById("mapperReplace").checked,
        },
      });
      render();
    });
    return;
  }
  if (target.dataset.mapperField) {
    await saveMapperPoint(target.closest("tr"));
    return;
  }
  if (target.id === "mapperFile" && target.files?.[0]) {
    await guard(async () => {
      const text = await target.files[0].text();
      const replace = document.getElementById("mapperReplace").checked;
      S.mapper = await api(`/api/mapper/recordings/import?replace=${replace ? "true" : "false"}`, {
        method: "POST",
        body: JSON.parse(text),
      });
      render();
      toast(replace ? "Recording replaced the current map" : "Recording saved. The current map was kept", true);
    });
    target.value = "";
    return;
  }
  if (target.id === "siteSelect") {
    const next = target.value || null;
    const sized = /^demo-(\d+)$/.exec(next || "");
    S.pointId = null;
    S.customise = false;
    if (sized && !(S.live?.simulator_running && S.live.site_id === next)) {
      await guard(async () => {
        S.live = await api(`/api/demo/compressors/${sized[1]}`, { method: "POST" });
        await refreshSites(next);
        S.view = "plant";
        render();
        const count = Number(sized[1]);
        const noun = count === 1 ? "compressor" : "compressors";
        toast(`Demo with ${count} ${noun} is running`, true);
      });
      return;
    }
    S.siteId = next;
    if (S.siteId) S.site = await api(`/api/sites/${S.siteId}`);
    else S.site = null;
    render();
    return;
  }
  if (target.dataset.layout && S.site) {
    S.site.layout = { ...(S.site.layout || {}), [target.dataset.layout]: target.checked };
    try {
      S.site = await api(`/api/sites/${S.site.id}/hmi`, {
        method: "PUT",
        body: { layout: S.site.layout },
      });
      render();
    } catch (error) {
      toast(error.message);
    }
    return;
  }
  if (target.dataset.label && S.site) {
    try {
      S.site = await api(`/api/sites/${S.site.id}/hmi`, {
        method: "PUT",
        body: { [target.dataset.label]: target.value },
      });
      render();
      toast("Display saved", true);
    } catch (error) {
      toast(error.message);
    }
    return;
  }
  if (target.dataset.widget && S.site) {
    const point = pointById(target.dataset.widget);
    if (!point) return;
    try {
      S.site = await api(`/api/sites/${S.site.id}/points/${point.id}`, {
        method: "PUT",
        body: { ...point, widget: target.value },
      });
      render();
      toast("Display saved", true);
    } catch (error) {
      toast(error.message);
    }
    return;
  }
  if (target.dataset.binding && S.site) {
    S.site.bindings[target.dataset.binding] = target.value || null;
    try {
      S.site = await api(`/api/sites/${S.site.id}/hmi`, {
        method: "PUT",
        body: { bindings: S.site.bindings },
      });
      render();
      toast("Display saved", true);
    } catch (error) {
      toast(error.message);
    }
    return;
  }
  if (target.id === "importFile" && target.files?.[0]) {
    await guard(async () => {
      const text = await target.files[0].text();
      S.site = await api(`/api/sites/${S.site.id}/import`, { method: "POST", body: JSON.parse(text) });
      S.pointId = null;
      render();
      toast("Map imported", true);
    });
  }
}

function onInput(event) {
  if (event.target.id === "pointSearch") {
    const query = event.target.value.trim().toLowerCase();
    document.querySelectorAll("#pointList button").forEach((button) => {
      button.hidden = query && !button.textContent.toLowerCase().includes(query);
    });
  }
  const form = event.target.form;
  if (form && form.id === "pointForm") wireHint();
  if (form && form.dataset.writePoint && event.target.name === "value") scheduleWritePlan(form);
}

function scheduleWritePlan(form) {
  clearTimeout(form._planTimer);
  form._planTimer = setTimeout(() => showWritePlan(form), 250);
}

async function showWritePlan(form) {
  const note = form.querySelector("[data-wire-note]");
  if (!note) return;
  const raw = form.elements.value.value.trim();
  if (raw === "") {
    note.hidden = true;
    note.textContent = "";
    return;
  }
  const value = Number(raw);
  const point = pointById(form.dataset.writePoint);
  if (!point || !Number.isFinite(value)) {
    note.hidden = false;
    note.textContent = "Enter a number to write.";
    return;
  }
  try {
    const plan = await api("/api/write-plan", { method: "POST", body: { point, value } });
    if (form.elements.value.value.trim() !== raw) return;
    note.hidden = false;
    note.textContent = plan.text;
  } catch (error) {
    if (form.elements.value.value.trim() !== raw) return;
    note.hidden = false;
    note.textContent = error.message;
  }
}

let lastSocketMessage = 0;

function connectSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${proto}://${location.host}/ws`);
  socket.onmessage = (event) => {
    lastSocketMessage = Date.now();
    S.live = JSON.parse(event.data);
    paintLive();
  };
  socket.onclose = () => setTimeout(connectSocket, 1500);
}

async function keepFresh() {
  if (Date.now() - lastSocketMessage > 3000) {
    try {
      S.live = await api("/api/live");
    } catch {
      /* the next tick will try again */
    }
  }
  paintLive();
}

const MAPPER_TYPES = ["bool", "uint16", "int16", "uint32", "int32", "float32", "float64", "string"];
const MAPPER_ORDERS = ["ABCD", "CDAB", "BADC", "DCBA"];
let mapperTimer = 0;

function mapperOptions(values, current) {
  return values.map((item) => `<option${item === current ? " selected" : ""}>${esc(item)}</option>`).join("");
}

function renderMapper(main) {
  const state = S.mapper || {
    settings: { mode: "rtu", port: "", baud: 9600, parity: "N", stopbits: 1, bytesize: 8 },
    ports: [],
    baud_rates: [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200],
    frames: [],
    points: [],
    recordings: [],
    units: [],
    detail: "Loading the mapper.",
  };
  const settings = state.settings || {};
  const ports = state.ports || [];
  const portOptions = [`<option value="">Choose a port</option>`]
    .concat(ports.map((port) => `<option value="${esc(port.device)}"${port.device === settings.port ? " selected" : ""}>${esc(port.device)} — ${esc(port.description)}</option>`))
    .join("");
  const chosenPort = settings.port && !ports.some((port) => port.device === settings.port)
    ? `<option value="${esc(settings.port)}" selected>${esc(settings.port)}</option>`
    : "";
  const baudOptions = (state.baud_rates || [9600]).map((baud) => `<option value="${baud}"${Number(baud) === Number(settings.baud) ? " selected" : ""}>${baud}</option>`).join("");
  const recordings = state.recordings || [];
  const recordingOptions = [`<option value="">Current capture</option>`]
    .concat(recordings.map((item) => `<option value="${esc(item.id)}">${esc(item.name)} (${item.exchanges})</option>`))
    .join("");
  const units = state.units || [];
  const unitOptions = (units.length ? units : [1]).map((unit) => `<option value="${unit}">Unit ${unit}</option>`).join("");
  const rows = (state.points || []).map((point) => `
    <tr data-point="${esc(point.id)}">
      <td>${esc(point.device)}</td>
      <td>${esc(point.function)}</td>
      <td class="num">${esc(point.address_number)}</td>
      <td><input data-mapper-field="name" value="${esc(point.name)}" maxlength="80"></td>
      <td><select data-mapper-field="addressing">
        <option value="protocol"${point.addressing === "protocol" ? " selected" : ""}>Protocol</option>
        <option value="modicon"${point.addressing === "modicon" ? " selected" : ""}>Modicon</option>
      </select></td>
      <td><select data-mapper-field="dtype">${mapperOptions(MAPPER_TYPES, point.dtype)}</select></td>
      <td><select data-mapper-field="byte_order">${mapperOptions(MAPPER_ORDERS, point.byte_order)}</select></td>
      <td><input data-mapper-field="scale" type="number" step="any" value="${esc(point.scale)}"></td>
      <td><input data-mapper-field="offset" type="number" step="any" value="${esc(point.offset)}"></td>
      <td><input data-mapper-field="decimals" type="number" min="0" max="4" value="${esc(point.decimals)}"></td>
      <td><input data-mapper-field="unit" value="${esc(point.unit || "")}" maxlength="16" placeholder="°C" aria-label="Engineering unit"></td>
      <td class="num" data-mapper-value="${esc(point.id)}">${esc(point.display || "—")}</td>
    </tr>`).join("");
  main.innerHTML = `
    <section class="panel" id="mapperRoot">
      <div class="steps">
        <span><b>1 Capture</b> Listen on RS-485</span>
        <span><b>2 Map</b> Name the registers</span>
        <span><b>3 Record</b> Keep the exchanges</span>
        <span><b>4 Replay</b> Serve them to the HMI</span>
      </div>
      <p class="help" id="mapperDetail">${esc(state.detail || "")}</p>
      <h2>Capture</h2>
      <p class="help">Monitor mode observes Modbus RTU or ASCII already on the wire. It does not transmit requests onto the RS-485 network.</p>
      <div class="form-grid">
        <label>Mode
          <select id="mapperMode">
            <option value="rtu"${settings.mode !== "ascii" ? " selected" : ""}>Modbus RTU</option>
            <option value="ascii"${settings.mode === "ascii" ? " selected" : ""}>Modbus ASCII</option>
          </select>
        </label>
        <label>Serial port
          <select id="mapperPort">${portOptions}${chosenPort}</select>
        </label>
        <label>Baud <select id="mapperBaud">${baudOptions}</select></label>
        <label>Parity
          <select id="mapperParity">
            <option${settings.parity === "N" ? " selected" : ""}>N</option>
            <option${settings.parity === "E" ? " selected" : ""}>E</option>
            <option${settings.parity === "O" ? " selected" : ""}>O</option>
          </select>
        </label>
        <label>Data bits
          <select id="mapperBits">
            <option value="8"${Number(settings.bytesize) !== 7 ? " selected" : ""}>8</option>
            <option value="7"${Number(settings.bytesize) === 7 ? " selected" : ""}>7</option>
          </select>
        </label>
        <label>Stop bits
          <select id="mapperStop">
            <option value="1"${Number(settings.stopbits) !== 2 ? " selected" : ""}>1</option>
            <option value="2"${Number(settings.stopbits) === 2 ? " selected" : ""}>2</option>
          </select>
        </label>
      </div>
      <div class="form-actions">
        <button class="primary" type="button" data-action="mapper-start"${state.capturing ? " disabled" : ""}>Start monitor</button>
        <button type="button" data-action="mapper-stop"${state.capturing ? "" : " disabled"}>Stop monitor</button>
        <button type="button" data-action="mapper-clear">Clear</button>
      </div>
      <div class="table-wrap frame-log"><table>
        <thead><tr><th>Role</th><th>Unit</th><th>Function</th><th>Frame</th></tr></thead>
        <tbody id="mapperFrames">${mapperFrameRows(state.frames)}</tbody>
      </table></div>
    </section>
    <section class="panel">
      <h2>Map</h2>
      <p class="help">Mapping stays off until you turn it on. The frame log still runs either way. With Mapping on, each register in a response is added to the map and its value updates.</p>
      <label class="inline"><input type="checkbox" id="mapperMapping"${state.mapping ? " checked" : ""}> Mapping</label>
      <div class="table-wrap"><table class="mapper-table">
        <thead><tr><th>Unit</th><th>Area</th><th>Address</th><th>Name</th><th>Addressing</th><th>Type</th><th>Order</th><th>Scale</th><th>Offset</th><th>Decimals</th><th>Eng. unit</th><th>Value</th></tr></thead>
        <tbody id="mapperPoints">${rows || `<tr><td colspan="12" class="muted">No registers yet. Start the monitor on a live RS-485 network, or load a recording.</td></tr>`}</tbody>
      </table></div>
    </section>
    <section class="panel">
      <div class="split">
        <div>
          <h2>Record</h2>
          <p class="help">Keep the request and response exchanges from the working equipment.</p>
          <div class="form-actions">
            <button type="button" data-action="mapper-record-on"${state.recording ? " disabled" : ""}>Start record</button>
            <button type="button" data-action="mapper-save">Save recording</button>
          </div>
          <label>Name <input id="mapperRecordName" maxlength="80" placeholder="Plant room"></label>
          <p class="muted" id="mapperExchangeCount">${esc(state.exchange_count || 0)} exchanges in this session.</p>
          <label class="inline">Load recording <input id="mapperFile" type="file" accept="application/json,.json"></label>
        </div>
        <div>
          <h2>Replay</h2>
          <p class="help">The emulator answers matching requests with the captured device responses, on this computer only. Replace stays off until you turn it on. Show on plant and Load recording then keep the current map. With Replace on, the captured registers take its place.</p>
          <label class="inline"><input type="checkbox" id="mapperReplace"${state.replace ? " checked" : ""}> Replace</label>
          <div class="form-grid">
            <label>Recording <select id="mapperRecording">${recordingOptions}</select></label>
            <label>Unit <select id="mapperUnit">${unitOptions}</select></label>
            <label>TCP port <input id="mapperReplayPort" type="number" min="0" max="65535" value="1502"></label>
            <label>Site name <input id="mapperSiteName" maxlength="80" value="Mapper replay"></label>
          </div>
          <div class="form-actions">
            <button type="button" data-action="mapper-replay">${state.replaying ? "Restart replay" : "Start replay"}</button>
            <button type="button" data-action="mapper-replay-stop"${state.replaying ? "" : " disabled"}>Stop replay</button>
            <button class="primary" type="button" data-action="mapper-plant">Show on plant</button>
          </div>
          <p class="muted" id="mapperReplay">${state.replaying ? `Emulator 127.0.0.1:${esc(state.replay_port)}` : "Replay is stopped."}</p>
        </div>
      </div>
    </section>`;
}

function mapperFrameRows(frames) {
  const rows = (frames || []).slice(-12).reverse().map((frame) => `
    <tr>
      <td>${esc(frame.role)}</td>
      <td>${esc(frame.unit)}</td>
      <td>${frame.exception ? "exception" : esc(frame.function)}</td>
      <td class="raw">${esc(frame.raw)}</td>
    </tr>`).join("");
  return rows || `<tr><td colspan="4" class="muted">Waiting for frames.</td></tr>`;
}

function mapperSettingsBody() {
  return {
    mode: document.getElementById("mapperMode").value,
    port: document.getElementById("mapperPort").value,
    baud: Number(document.getElementById("mapperBaud").value),
    parity: document.getElementById("mapperParity").value,
    bytesize: Number(document.getElementById("mapperBits").value),
    stopbits: Number(document.getElementById("mapperStop").value),
  };
}

function syncMapperWatch() {
  const want = S.view === "mapper";
  if (want && !mapperTimer) {
    mapperTimer = setInterval(() => { refreshMapper().catch(() => {}); }, 1000);
    refreshMapper().catch(() => {});
  } else if (!want && mapperTimer) {
    clearInterval(mapperTimer);
    mapperTimer = 0;
  }
}

async function refreshMapper() {
  if (S.view !== "mapper") return;
  const next = await api("/api/mapper");
  const previous = S.mapper;
  S.mapper = next;
  const typing = document.activeElement && document.activeElement.closest && document.activeElement.closest("#mapperRoot, .mapper-table, #mapperFile");
  const sameShape = previous
    && previous.capturing === next.capturing
    && previous.replaying === next.replaying
    && previous.recording === next.recording
    && previous.mapping === next.mapping
    && previous.replace === next.replace
    && (previous.points || []).map((point) => point.id).join() === (next.points || []).map((point) => point.id).join()
    && (previous.recordings || []).length === (next.recordings || []).length;
  if (!document.getElementById("mapperRoot") || (!typing && !sameShape)) {
    render();
    return;
  }
  paintMapperLive();
}

function paintMapperLive() {
  const state = S.mapper;
  if (!state) return;
  const detail = document.getElementById("mapperDetail");
  if (detail) detail.textContent = state.detail || "";
  const frames = document.getElementById("mapperFrames");
  if (frames) frames.innerHTML = mapperFrameRows(state.frames);
  const count = document.getElementById("mapperExchangeCount");
  if (count) count.textContent = `${state.exchange_count || 0} exchanges in this session.`;
  const replay = document.getElementById("mapperReplay");
  if (replay) replay.textContent = state.replaying ? `Emulator 127.0.0.1:${state.replay_port}` : "Replay is stopped.";
  for (const point of state.points || []) {
    const cell = document.querySelector(`[data-mapper-value="${CSS.escape(point.id)}"]`);
    if (cell) cell.textContent = point.display || "—";
  }
}

async function saveMapperPoint(row) {
  if (!row) return;
  const value = (name) => row.querySelector(`[data-mapper-field="${name}"]`).value;
  await guard(async () => {
    S.mapper = await api(`/api/mapper/points/${row.dataset.point}`, {
      method: "PUT",
      body: {
        name: value("name"),
        addressing: value("addressing"),
        dtype: value("dtype"),
        byte_order: value("byte_order"),
        scale: Number(value("scale")),
        offset: Number(value("offset")),
        decimals: Number(value("decimals")),
        unit: value("unit"),
      },
    });
    paintMapperLive();
  });
}

async function onMapperAction(action) {
  await guard(async () => {
    if (action === "mapper-start") {
      S.mapper = await api("/api/mapper/capture/start", { method: "POST", body: mapperSettingsBody() });
    } else if (action === "mapper-stop") {
      S.mapper = await api("/api/mapper/capture/stop", { method: "POST" });
    } else if (action === "mapper-clear") {
      S.mapper = await api("/api/mapper/clear", { method: "POST" });
    } else if (action === "mapper-record-on") {
      S.mapper = await api("/api/mapper/record", { method: "POST", body: { enabled: true } });
    } else if (action === "mapper-save") {
      const name = document.getElementById("mapperRecordName").value;
      S.mapper = await api("/api/mapper/recordings", { method: "POST", body: { name } });
      toast("Recording saved", true);
    } else if (action === "mapper-replay" || action === "mapper-replay-stop") {
      if (action === "mapper-replay-stop") {
        S.mapper = await api("/api/mapper/replay/stop", { method: "POST" });
      } else {
        S.mapper = await api("/api/mapper/replay", {
          method: "POST",
          body: {
            recording_id: document.getElementById("mapperRecording").value,
            port: Number(document.getElementById("mapperReplayPort").value),
          },
        });
        toast("Replay emulator is running", true);
      }
    } else if (action === "mapper-plant") {
      const replace = document.getElementById("mapperReplace").checked;
      const result = await api("/api/mapper/plant", {
        method: "POST",
        body: {
          recording_id: document.getElementById("mapperRecording").value,
          port: Number(document.getElementById("mapperReplayPort").value),
          unit: Number(document.getElementById("mapperUnit").value),
          name: document.getElementById("mapperSiteName").value,
          replace,
          site_id: S.siteId || "",
        },
      });
      S.mapper = result.mapper;
      S.live = result.live;
      S.view = "plant";
      await refreshSites(result.site.id);
      toast(replace ? "Plant is reading the replay emulator" : "Plant is reading the replay emulator. The register map was kept", true);
      return;
    }
    render();
  });
}

async function boot() {
  ensureShell();
  S.meta = await api("/api/meta");
  S.live = await api("/api/live");
  await refreshSites(S.live.site_id);
  connectSocket();
  setInterval(() => { keepFresh(); }, 1000);
  checkUpdate();
}

async function checkUpdate() {
  try {
    const info = await api("/api/update");
    const banner = document.getElementById("updateBanner");
    if (banner) banner.hidden = !info.available;
  } catch {
    /* stay on this version when GitHub cannot be reached */
  }
}

boot().catch((error) => {
  ensureShell();
  toast(error.message || "Could not load the monitor");
});
