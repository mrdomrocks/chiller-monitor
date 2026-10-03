const S = {
  meta: null,
  sites: [],
  siteId: null,
  site: null,
  live: null,
  view: "plant",
  pointId: null,
};

let shellReady = false;
let busy = false;
let toastTimer = 0;
let compressorKey = "";

const FC = { coil: 1, discrete: 2, holding: 3, input: 4 };
const BASE = { coil: 1, discrete: 10001, input: 30001, holding: 40001 };

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
        <button type="button" id="demoBtn" data-action="demo">Demo chiller</button>
        <button type="button" data-action="add-site">New site</button>
      </div>
    </header>
    <nav class="tabs" id="tabs">
      <button type="button" data-view="plant" aria-selected="true">Plant</button>
      <button type="button" data-view="map" aria-selected="false">Register map</button>
      <button type="button" data-view="link" aria-selected="false">Connection</button>
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

function fillSiteSelect() {
  const select = document.getElementById("siteSelect");
  select.replaceChildren();
  if (!S.sites.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No sites yet";
    select.appendChild(option);
    return;
  }
  for (const site of S.sites) {
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
  const demo = document.getElementById("demoBtn");
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
  demo.textContent = S.live?.simulator_running ? "Stop demo" : "Demo chiller";
  demo.disabled = busy;
  for (const tab of document.querySelectorAll("#tabs button")) {
    tab.setAttribute("aria-selected", tab.dataset.view === S.view ? "true" : "false");
  }
}

function render() {
  compressorKey = "";
  ensureShell();
  fillSiteSelect();
  paintHeader();
  const main = document.getElementById("main");
  if (!S.site) {
    main.innerHTML = `
      <section class="welcome">
        <h1>Watch a chiller through the RUT</h1>
        <p>Join the chiller network on this laptop, then this page opens Modbus TCP to the controller. On site that is the RUT Wi-Fi. Away from site, use the laptop’s existing remote connection first. Addresses, scaling, and which values can be written are edited in the register map.</p>
        <div class="actions">
          <button class="primary" type="button" data-action="demo">Start the demo chiller</button>
          <button type="button" data-action="add-site">Create a site</button>
        </div>
      </section>`;
    return;
  }
  if (S.view === "map") renderMap(main);
  else if (S.view === "link") renderLink(main);
  else renderPlant(main);
  paintLive();
}

function renderPlant(main) {
  const site = S.site;
  main.innerHTML = `
    <p class="demo-flag" id="demoFlag" hidden>Demo controller on this computer. Supply temperature alarms above its high limit so the banner can be checked.</p>
    <div class="alarm-banner" id="alarmBanner" hidden></div>
    <div class="plant-head">
      <div>
        <h1>${esc(site.name)}</h1>
        <p>${esc(site.location || "Location not set")} · unit ${esc(site.unit_id)} · ${esc(site.modbus_host)}:${esc(site.modbus_port)}</p>
      </div>
      <p class="muted" id="commsDetail"></p>
    </div>
    <section class="hero">${["supply_temp", "return_temp", "setpoint", "capacity"].map(heroCard).join("")}</section>
    <section class="mimic" id="mimic">
      ${loop("cold", "return_temp", site.evap_label || "Evaporator", "supply_temp")}
      ${loop("hot", "condenser_in", site.cond_label || "Condenser", "condenser_out")}
    </section>
    <section class="compressor-bank">
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
      <div class="compressors" id="compressorGrid"></div>
    </section>
    <section class="side-reads">
      ${readout("flow")}
      ${readout("pressure")}
    </section>
    <h2 class="kicker" style="margin:6px 0">Status</h2>
    <section class="lamps" id="lamps">${lampCards()}</section>
    <h2 class="kicker" style="margin:6px 0">Writable outputs</h2>
    <section class="controls" id="controls">${controlCards()}</section>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Point</th><th>Value</th><th>Raw</th><th>Quality</th></tr></thead>
        <tbody>${tableRows()}</tbody>
      </table>
    </div>`;
}

function heroCard(roleId) {
  const meta = S.meta.roles.find((role) => role.id === roleId);
  const point = bound(roleId);
  if (!point) {
    return `<article class="hero-card missing"><span class="kicker">${esc(meta.label)}</span><b>Not assigned</b></article>`;
  }
  return `<article class="hero-card" data-card="${esc(point.id)}">
    <span class="kicker">${esc(point.name)}</span>
    <div class="figure"><b data-value="${esc(point.id)}">—</b><small>${esc(point.unit)}</small></div>
    <div class="bar"><span data-bar="${esc(point.id)}"></span></div>
    <svg class="spark" viewBox="0 0 120 32" preserveAspectRatio="none" aria-hidden="true"><polyline data-spark="${esc(point.id)}" points=""></polyline></svg>
  </article>`;
}

function loop(kind, inletRole, vessel, outletRole) {
  return `<div class="loop ${kind}">
    ${node(inletRole)}
    <div class="pipe"></div>
    <div class="vessel"><strong>${esc(vessel)}</strong></div>
    <div class="pipe"></div>
    ${node(outletRole)}
  </div>`;
}

function node(roleId) {
  const meta = S.meta.roles.find((role) => role.id === roleId);
  const point = bound(roleId);
  if (!point) return `<div class="node"><span class="kicker">${esc(meta.label)}</span><b>—</b></div>`;
  return `<div class="node" data-card="${esc(point.id)}">
    <span class="kicker">${esc(point.name)}</span>
    <b data-value="${esc(point.id)}">—</b>
    <small>${esc(point.unit)}</small>
  </div>`;
}

function readout(roleId) {
  const meta = S.meta.roles.find((role) => role.id === roleId);
  const point = bound(roleId);
  if (!point) return `<article class="readout"><span class="kicker">${esc(meta.label)}</span><b>—</b></article>`;
  return `<article class="readout" data-card="${esc(point.id)}">
    <span class="kicker">${esc(point.name)}</span>
    <div class="figure"><b data-value="${esc(point.id)}">—</b><small>${esc(point.unit)}</small></div>
  </article>`;
}

function visiblePoints() {
  return S.site.points.filter((point) => point.enabled && point.widget !== "hidden");
}

function lampCards() {
  const points = visiblePoints().filter((point) => point.widget === "status" || point.widget === "alarm");
  if (!points.length) return `<p class="muted">No status or alarm points. Set a point’s widget to Status or Alarm.</p>`;
  return points.map((point) => `
    <article class="lamp-card" data-lamp="${esc(point.id)}">
      <span class="lamp"></span>
      <div><strong>${esc(point.name)}</strong><div data-value="${esc(point.id)}">—</div></div>
    </article>`).join("");
}

function controlCards() {
  const points = visiblePoints().filter((point) => point.writable);
  if (!points.length) {
    return `<p class="muted">No writable outputs. In the register map, mark a holding register or coil as writable and it will show up here.</p>`;
  }
  return points.map((point) => {
    const body = point.dtype === "bool" || point.function === "coil"
      ? `<div class="toggle" data-toggles="${esc(point.id)}">
          <button type="button" data-requires-connection data-action="write-bool" data-point="${esc(point.id)}" data-flag="true">${esc(point.on_label)}</button>
          <button type="button" data-requires-connection data-action="write-bool" data-point="${esc(point.id)}" data-flag="false">${esc(point.off_label)}</button>
        </div>`
      : `<form data-write-point="${esc(point.id)}" class="write-row">
          <input name="value" type="number" step="any" placeholder="${esc(point.unit)}">
          <button class="primary" type="submit" data-requires-connection>Apply</button>
        </form>`;
    return `<article class="control"><span class="kicker">${esc(point.group)}</span><strong>${esc(point.name)}</strong><div data-value="${esc(point.id)}">—</div>${body}</article>`;
  }).join("");
}

function tableRows() {
  return visiblePoints().map((point) => `
    <tr data-action="edit-point" data-point="${esc(point.id)}">
      <td>${esc(point.name)}<div class="muted">${esc(point.group)} · ${esc(addressLabel(point))}</div></td>
      <td class="num"><span data-value="${esc(point.id)}">—</span> ${esc(point.unit)}</td>
      <td class="raw" data-raw="${esc(point.id)}">—</td>
      <td><span class="tag" data-quality="${esc(point.id)}">—</span></td>
    </tr>`).join("");
}

function addressLabel(point) {
  const prefix = { holding: "4x", input: "3x", coil: "0x", discrete: "1x" }[point.function];
  return `${prefix} ${point.address_number}${point.bit === null || point.bit === undefined ? "" : " bit " + point.bit}`;
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
  const flag = document.getElementById("demoFlag");
  if (flag) flag.hidden = !(S.live && S.live.demo && S.live.site_id === S.siteId);
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
  const banner = document.getElementById("alarmBanner");
  if (banner && S.site) {
    const alarms = visiblePoints().filter((point) => {
      const reading = readingFor(point.id);
      return reading && reading.quality === "good" && reading.alarm;
    });
    banner.hidden = alarms.length === 0;
    banner.textContent = alarms.length ? `Alarm · ${alarms.map((point) => point.name).join(", ")}` : "";
  }
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
    <section class="panel">
      <div class="section-head"><h2>Plant display</h2></div>
      <p class="help">Bind each slot on the plant page to a point. Renaming the point changes the label the operator sees. Vessel names are for the diagram only. Compressor cards follow the fitted-compressors register: a machine that reports 2 shows two loads, and a larger machine shows the extra circuits, up to six.</p>
      <form id="hmiForm">
        <div class="bindings">
          <label>Evaporator label <input name="evap_label" value="${esc(site.evap_label)}"></label>
          <label>Heat-rejection label <input name="cond_label" value="${esc(site.cond_label)}"></label>
        </div>
        ${bindingSections(site)}
        <button class="primary" type="submit">Save labels</button>
      </form>
    </section>
    <div class="toolbar">
      <input id="pointSearch" type="search" placeholder="Filter points">
      <div class="actions">
        <button type="button" data-action="add-point">Add point</button>
        <button type="button" data-action="export">Export map</button>
        <label class="inline">Import <input id="importFile" type="file" accept="application/json,.json"></label>
        <button type="button" class="danger" data-action="template">Reload chiller template</button>
      </div>
    </div>
    <div class="split">
      <div class="point-list" id="pointList">${pointButtons()}</div>
      <section class="panel" id="pointPanel">${point ? pointForm(point) : "<p>Add a point to begin.</p>"}</section>
    </div>`;
  wireHint();
}

function bindingSections(site) {
  const sections = [];
  for (const role of S.meta.roles) {
    const name = role.section || "Plant";
    let section = sections.find((item) => item.name === name);
    if (!section) {
      section = { name, roles: [] };
      sections.push(section);
    }
    section.roles.push(role);
  }
  return sections.map((section) => `
    <fieldset class="bind-section">
      <legend>${esc(section.name)}</legend>
      <div class="bindings">
        ${section.roles.map((role) => `<label>${esc(role.label)}
          <select data-binding="${esc(role.id)}">${pointOptions(site.bindings[role.id])}</select>
        </label>`).join("")}
      </div>
    </fieldset>`).join("");
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
  const dtype = ["bool", "uint16", "int16", "uint32", "int32", "float32", "float64"];
  const areas = [["holding", "Holding (4x)"], ["input", "Input (3x)"], ["coil", "Coil (0x)"], ["discrete", "Discrete (1x)"]];
  const widgets = [["value", "Value"], ["gauge", "Gauge"], ["status", "Status lamp"], ["alarm", "Alarm"], ["setpoint", "Setpoint"], ["hidden", "Hidden"]];
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
      <label>Unit <input name="unit" maxlength="16" value="${esc(point.unit)}"></label>
      <label>Widget ${select("widget", widgets, point.widget)}</label>
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
      <label>Sample raw words <input id="sampleRaw" placeholder="72 or 17184, 0"></label>
      <div class="form-actions" style="align-items:end">
        <button type="button" data-action="preview">Decode sample</button>
        <span id="previewOut"></span>
      </div>
    </div>
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

function renderLink(main) {
  const site = S.site;
  main.innerHTML = `
    <section class="panel">
      <h2>Modbus TCP</h2>
      <p class="help">Same connection Modbus Monitor uses. This program does not log into a VPN. Put the laptop on the network first, then enter the controller’s IP, port 502, and unit id.</p>
      <p class="help">On site, join the RUT Wi-Fi or the site LAN. The address is the RUT LAN address when it is gatewaying the chiller, or the chiller’s own address when the controller speaks Modbus TCP. Away from site, connect the laptop over the internet or mobile data the way you already do, then use that same IP. Connect reopens the socket if the Wi-Fi drops.</p>
      <form id="linkForm">
        <div class="form-grid">
          <label>Site name <input name="name" required maxlength="80" value="${esc(site.name)}"></label>
          <label>Location <input name="location" maxlength="120" value="${esc(site.location)}"></label>
          <label>IP address <input name="modbus_host" required value="${esc(site.modbus_host)}"></label>
          <label>Port <input name="modbus_port" type="number" min="1" max="65535" value="${esc(site.modbus_port)}"></label>
          <label>Unit id <input name="unit_id" type="number" min="0" max="255" value="${esc(site.unit_id)}"></label>
          <label>Response timeout (s) <input name="timeout_s" type="number" min="0.2" max="30" step="0.1" value="${esc(site.timeout_s)}"></label>
          <label>Retries <input name="retries" type="number" min="1" max="10" step="1" value="${esc(site.retries ?? 3)}"></label>
          <label>Link timeout (s) <input name="link_timeout_s" type="number" min="1" max="120" step="1" value="${esc(site.link_timeout_s ?? 30)}"></label>
          <label>Poll (ms) <input name="poll_ms" type="number" min="200" max="60000" step="100" value="${esc(site.poll_ms)}"></label>
        </div>
        <label>Notes <textarea name="notes">${esc(site.notes)}</textarea></label>
        <div class="form-actions" style="margin-top:12px">
          <button class="primary" type="submit">Save connection</button>
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
  if (action === "demo") {
    await guard(async () => {
      if (S.live?.simulator_running) {
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
  } else if (form.id === "hmiForm") {
    event.preventDefault();
    await guard(async () => {
      S.site = await api(`/api/sites/${S.site.id}/hmi`, {
        method: "PUT",
        body: {
          bindings: S.site.bindings,
          evap_label: form.elements.evap_label.value,
          cond_label: form.elements.cond_label.value,
        },
      });
      toast("Display saved", true);
    });
  } else if (form.dataset.writePoint) {
    event.preventDefault();
    const point = pointById(form.dataset.writePoint);
    const value = Number(form.elements.value.value);
    if (!point || !Number.isFinite(value)) {
      toast("Enter a number to write");
      return;
    }
    const unit = point.unit ? ` ${point.unit}` : "";
    if (!confirm(`Write ${value}${unit} to ${point.name} on the controller?`)) return;
    await guard(async () => {
      await api(`/api/sites/${S.site.id}/write`, {
        method: "POST",
        body: { point_id: point.id, value },
      });
      form.elements.value.value = "";
      toast(`Wrote ${point.name}`, true);
    });
  }
}

async function onChange(event) {
  const target = event.target;
  if (target.id === "siteSelect") {
    S.siteId = target.value || null;
    S.pointId = null;
    if (S.siteId) S.site = await api(`/api/sites/${S.siteId}`);
    else S.site = null;
    render();
    return;
  }
  if (target.dataset.binding && S.site) {
    S.site.bindings[target.dataset.binding] = target.value || null;
    try {
      S.site = await api(`/api/sites/${S.site.id}/hmi`, {
        method: "PUT",
        body: { bindings: S.site.bindings },
      });
      toast("Binding saved", true);
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
  if (event.target.form && event.target.form.id === "pointForm") wireHint();
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

async function boot() {
  ensureShell();
  S.meta = await api("/api/meta");
  S.live = await api("/api/live");
  await refreshSites(S.live.site_id);
  connectSocket();
  setInterval(() => { keepFresh(); }, 1000);
}

boot().catch((error) => {
  ensureShell();
  toast(error.message || "Could not load the monitor");
});
