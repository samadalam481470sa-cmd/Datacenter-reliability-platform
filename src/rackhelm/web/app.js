"use strict";
/*
 * RackHelm FleetOS operator console. Only synthetic demo data is displayed.
 * No browser controls can issue commands to physical equipment.
 * All server-sourced strings are applied with textContent, never innerHTML.
 */
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { overview: null, incidents: [], zone: "Z02", rack: "Z02-R04", inflight: false };
  const severityNames = { critical: "CRITICAL", warning: "WARNING", healthy: "NOMINAL", unknown: "NO DATA" };

  function node(tag, className, value) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (value !== undefined) el.textContent = String(value);
    return el;
  }
  function set(id, value) { $(id).textContent = String(value); }
  function fmt(value, decimals = 1) {
    return typeof value === "number" && Number.isFinite(value)
      ? value.toLocaleString("en-US", {minimumFractionDigits: decimals,maximumFractionDigits:decimals})
      : "—";
  }
  function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.classList.add("visible");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.remove("visible"), 3500);
  }
  async function getJSON(url) {
    const response = await fetch(url, {cache: "no-store", headers: {Accept: "application/json"}});
    if (!response.ok) throw new Error("Request failed (HTTP " + response.status + ")");
    return response.json();
  }
  function createZoneButtons() {
    const bar = $("zone-switch");
    bar.replaceChildren();
    for (const zone of ["Z01", "Z02", "Z03", "Z04"]) {
      const button = node("button", "zone-button" + (state.zone === zone ? " selected" : ""), zone.replace("Z", "ZONE "));
      button.type = "button";
      button.setAttribute("aria-pressed", String(state.zone === zone));
      button.addEventListener("click", () => {
        state.zone = zone;
        if (!state.overview.racks.some(r => r.zone === zone && r.rack_id === state.rack)) {
          state.rack = state.overview.racks.find(r => r.zone === zone)?.rack_id || "";
        }
        createZoneButtons(); renderHeatmap(); selectRack();
        $("scenario-zone").value = zone;
      });
      bar.append(button);
    }
  }
  function renderHeatmap() {
    const mount = $("rack-map");
    mount.replaceChildren();
    const racks = state.overview.racks.filter(r => r.zone === state.zone)
      .sort((a, b) => (a.row - b.row) || (a.position - b.position));
    for (let i = 0; i < racks.length; i++) {
      if (i === 6) mount.append(node("div", "rack-divider"));
      const rack = racks[i];
      const elevated = rack.inlet_c !== null && rack.inlet_c >= rack.temp_limit_c - 2.7;
      const danger = rack.risk >= 70 || (rack.inlet_c !== null && rack.inlet_c >= rack.temp_limit_c);
      const category = rack.inlet_c === null ? "no-data" : danger ? "hot" : elevated || rack.risk >= 35 ? "warn" : "";
      const card = node("button", "rack-tile " + category + (state.rack === rack.rack_id ? " selected" : ""));
      card.type = "button";
      card.setAttribute("aria-label", rack.rack_id + ": " + fmt(rack.inlet_c) + " degrees Celsius; risk " + fmt(rack.risk));
      card.setAttribute("aria-pressed", String(state.rack === rack.rack_id));
      card.append(node("span", "rack-id", rack.rack_id.replace("Z" + state.zone.substring(1) + "-", "")),
                  node("span", "rack-temp", fmt(rack.inlet_c) + "°"));
      const bottom = node("div", "rack-footer");
      bottom.append(node("span", "", rack.rack_type), node("span", "rack-glyph", "▥"));
      card.append(bottom);
      card.addEventListener("click", () => {state.rack = rack.rack_id; renderHeatmap();selectRack();});
      mount.append(card);
    }
  }
  function makeChart(readings, rack) {
    const target = $("sparkline");
    target.replaceChildren();
    if (!readings.length) {
      target.append(node("span", "muted", "No usable historical readings")); return;
    }
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 480 138");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Rack temperature history, last " + readings.length + " samples");
    const t = readings.map(x => x.inlet_c);
    const lo = Math.min(...t, rack.temp_limit_c) - 1;
    const hi = Math.max(...t, rack.temp_limit_c) + 1;
    const x = (i) => 8 + i / Math.max(readings.length - 1, 1) * 464;
    const y = (v) => 111 - ((v - lo) / (hi - lo)) * 89;
    const add = (tag, attrs, text) => {
      const el = document.createElementNS(svgNS, tag);
      Object.entries(attrs).forEach(([name, val]) => el.setAttribute(name, String(val)));
      if (text !== undefined) el.textContent = String(text);
      svg.append(el);
      return el;
    };
    for (let i = 0; i < 3; i++) {
      const cy = 28 + i * 40;
      add("line", {x1:8,x2:472,y1:cy,y2:cy,stroke:"#294052","stroke-width":"1","stroke-dasharray":"3 5"});
    }
    add("line", {x1:8,x2:472,y1:y(rack.temp_limit_c),y2:y(rack.temp_limit_c),stroke:"#e4a461","stroke-width":"1.3","stroke-dasharray":"4 4"});
    add("text", {x:435,y:y(rack.temp_limit_c)-6,fill:"#dda66d","font-size":9}, "LIMIT");
    const pts = t.map((v,i)=>[x(i),y(v)]);
    const d = pts.map((p,i) => (i ? "L" : "M") + p.map(v=>v.toFixed(1)).join(" ")).join(" ");
    const fillPath = d + " L " + pts[pts.length-1][0].toFixed(1) + " 119 L 8 119 Z";
    const defs = document.createElementNS(svgNS,"defs");
    const grad = document.createElementNS(svgNS,"linearGradient");
    grad.setAttribute("id","trend-fill");grad.setAttribute("x1","0");grad.setAttribute("x2","0");grad.setAttribute("y1","0");grad.setAttribute("y2","1");
    const s1 = document.createElementNS(svgNS,"stop");s1.setAttribute("offset","0%");s1.setAttribute("stop-color","#49e2b8");s1.setAttribute("stop-opacity",".25");
    const s2 = document.createElementNS(svgNS,"stop");s2.setAttribute("offset","100%");s2.setAttribute("stop-color","#49e2b8");s2.setAttribute("stop-opacity","0");
    grad.append(s1,s2);defs.append(grad);svg.append(defs);
    add("path",{d:fillPath,fill:"url(#trend-fill)"});
    add("path",{d,fill:"none",stroke:"#62e0b9","stroke-width":"2.4","stroke-linecap":"round","stroke-linejoin":"round"});
    add("circle",{cx:pts[pts.length-1][0],cy:pts[pts.length-1][1],r:4,fill:"#70f3c9",stroke:"#18483f","stroke-width":2});
    add("text",{x:7,y:134,fill:"#819bb2","font-size":9}, "−"+Math.round((readings.length-1)*5)+" min");
    add("text",{x:451,y:134,fill:"#819bb2","font-size":9}, "NOW");
    target.append(svg);
  }
  async function selectRack() {
    const rackId = state.rack;
    const rack = state.overview?.racks.find(r => r.rack_id === rackId);
    if (!rack) return;
    set("selected-rack-heading", rack.rack_id);
    set("selected-rack-sub", rack.zone + " · ROW " + String(rack.row).padStart(2,"0") + " · " + rack.asset_count + " assets");
    set("asset-tag", rack.rack_type);
    set("selected-temp", fmt(rack.inlet_c));
    set("selected-risk", fmt(rack.risk,0));
    set("selected-headroom", fmt(rack.headroom_c) + " °C");
    set("selected-power", fmt(rack.power_kw) + " kW");
    set("selected-fan", rack.fan_rpm === null ? "—" : rack.fan_rpm.toLocaleString("en-US") + " rpm");
    set("selected-eta", rack.eta_to_limit_minutes === null ? "Not projected" : fmt(rack.eta_to_limit_minutes,0) + " min");
    set("trend-direction", (rack.warming_c_per_hour >= 0 ? "+" : "")+fmt(rack.warming_c_per_hour,2) + " °C/h");
    const mount = $("asset-signals");mount.replaceChildren();
    set("signal-count", rack.signals.length);
    if (!rack.signals.length) mount.append(node("span","muted","No flagged conditions for this rack."));
    for (const signal of rack.signals) {
      const item = node("div","signal-entry");
      const content = node("div", "");
      content.append(node("strong","",signal.code.replaceAll("_"," ")),
                     node("small","",signal.reason));
      item.append(node("span","","⚠"),content);mount.append(item);
    }
    try {
      const history = await getJSON("/api/v1/racks/"+encodeURIComponent(rackId)+"/history?limit=36");
      if (state.rack === rackId) makeChart(history.readings, rack);
    } catch (error) { if (state.rack === rackId) $("sparkline").replaceChildren(node("span","muted",error.message)); }
  }
  function renderIncidents() {
    const mount = $("incident-list");mount.replaceChildren();
    set("incident-total",state.incidents.length+" EVENTS");
    set("incident-side-count",state.incidents.filter(x=>x.status==="open").length);
    if (!state.incidents.length) {mount.append(node("div","muted","No incidents in this demonstration."));return;}
    const sorted = state.incidents.slice().sort((a,b) => (a.status==="open"?0:1)-(b.status==="open"?0:1) || (a.severity==="critical"?-1:1)-(b.severity==="critical"?-1:1));
    for (const incident of sorted.slice(0,7)) {
      const row = node("div","incident");
      const sym = node("div","severity "+incident.severity,incident.severity==="critical"?"!":"△");
      const middle = node("div","incident-main");
      middle.append(node("strong","",incident.rack_id+" · "+incident.code.replaceAll("_"," ")),
                    node("p","",incident.title),node("div","incident-meta",incident.severity.toUpperCase()+"  /  ENGINE-GENERATED"));
      row.append(sym,middle,node("span","incident-status "+incident.status,incident.status.toUpperCase()));
      mount.append(row);
    }
  }
  function renderRedundancy() {
    const mount = $("redundancy-list");mount.replaceChildren();
    for (const zone of state.overview.zones) {
      const unit = node("div","zone-row");
      const top = node("div","zone-row-top");top.append(node("b","",zone.zone+" / COOLING"),
          node("span",zone.cooling_n1_pass?"pass":"fail",zone.cooling_n1_pass?"✓ N+1 PASS":"⚠ N+1 DEFICIT"));
      const track = node("div","capacity-line");
      const fill = node("div","capacity-fill"+(zone.cooling_n1_pass?"":" fail"));
      const avail = zone.cooling_capacity_kw/2;
      fill.style.width = Math.min(100,100*zone.it_kw/Math.max(avail,1)).toFixed(1)+"%";
      track.append(fill);
      const bottom = node("div","zone-row-meta");
      bottom.append(node("span","",fmt(zone.it_kw,0)+" kW IT load"),
                    node("span","",(zone.cooling_n1_headroom_kw<0?"−":"+")+fmt(Math.abs(zone.cooling_n1_headroom_kw),1)+" kW after failover"));
      unit.append(top,track,bottom);mount.append(unit);
    }
  }
  function renderOverview() {
    const overview=state.overview;
    set("k-racks", overview.kpis.rack_count);
    set("k-gpu",overview.kpis.gpu_racks);
    set("k-power",fmt(overview.kpis.it_load_kw,0));
    set("k-alerts",overview.kpis.affected_racks);
    set("k-critical",overview.kpis.critical_racks);
    set("k-pue",fmt(overview.kpis.estimated_pue,2));
    set("clock",new Date(overview.updated_at).toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit",timeZone:"UTC"})+" UTC");
    createZoneButtons();renderHeatmap();renderRedundancy();selectRack();
  }
  async function refresh(showToast=false) {
    if (state.inflight) return;
    state.inflight=true;
    $("refresh").disabled=true;
    try {
      const [overview,incidents] = await Promise.all([getJSON("/api/v1/overview"),getJSON("/api/v1/incidents")]);
      state.overview=overview;state.incidents=incidents.incidents;
      renderOverview();renderIncidents();
      if(showToast) toast("Synthetic fleet telemetry refreshed successfully");
    } catch(error) {toast("Telemetry unavailable: "+error.message);}
    finally {state.inflight=false;$("refresh").disabled=false;}
  }
  function bindScenario() {
    const cooling=$("cooling-loss"),load=$("gpu-load"),setpoint=$("setpoint");
    function labels() {
      set("cooling-out",cooling.value+"%");
      set("gpu-out",(Number(load.value)>=0?"+":"")+load.value+"%");
      set("setpoint-out",(Number(setpoint.value)>=0?"+":"")+setpoint.value+" °C");
    }
    for (const control of [cooling,load,setpoint]) control.addEventListener("input",labels);
    $("simulate-btn").addEventListener("click",async () => {
      const button=$("simulate-btn");button.disabled=true;
      try {
        const q=new URLSearchParams({zone:$("scenario-zone").value,cooling_drop_pct:cooling.value,
          gpu_load_delta_pct:load.value,setpoint_delta_c:setpoint.value});
        const result=await getJSON("/api/v1/scenario?"+q.toString());
        set("scenario-temp",fmt(result.estimated_peak_inlet_c,1));
        set("scenario-cooling",fmt(result.cooling_remaining_kw,1)+" kW");
        set("scenario-load",fmt(result.scenario_it_kw,1)+" kW");
        set("scenario-shortfall",fmt(result.capacity_gap_kw,1)+" kW");
        const tag=$("scenario-tag");
        tag.textContent=result.would_exceed_demo_limit?"LIMIT EXCEEDED":"WITHIN DEMO LIMIT";
        tag.className="scenario-result-tag"+(result.would_exceed_demo_limit?" danger":"");
        set("scenario-explanation",result.zone+" projected peak inlet "+fmt(result.estimated_peak_inlet_c)+" °C. " +
          (result.capacity_gap_kw>0?"Modeled capacity shortfall requires an engineering review.":"Cooling capacity exceeds modeled projected heat load."));
        toast("Scenario evaluated — no facility control actions performed");
      } catch(error){toast("Scenario unavailable: "+error.message);}
      finally{button.disabled=false;}
    });
  }
  $("refresh").addEventListener("click",()=>refresh(true));
  bindScenario();refresh();
  $("simulate-btn").click();
  setInterval(()=>refresh(false),45000);
})();