// Replay player for the recorded e2e runs. Everything shown is derived from the agent's event log
// (replay/<scenario>.json) and the room mix (replay/<scenario>.mp3). Nothing here is live.
(() => {
  const PALETTE = ["#7fc8b5", "#e58f78", "#9fb0e8", "#d7c27a"];
  const VERB = {
    speak: ["spoke", "speak"],
    wait: ["stayed quiet", "wait"],
    consult: ["asked the gate", "consult"],
    stop: ["stopped", "stop"],
  };

  const root = document.querySelector("[data-player]");
  if (!root) return;
  const audio = root.querySelector("[data-audio]");
  const el = {
    tiles: root.querySelector("[data-tiles]"),
    feed: root.querySelector("[data-feed]"),
    captions: root.querySelector("[data-captions]"),
    play: root.querySelector("[data-play]"),
    seek: root.querySelector("[data-seek]"),
    clock: root.querySelector("[data-clock]"),
    checks: document.querySelector("[data-checks]"),
    checksTitle: document.querySelector("[data-checks-title]"),
    fallback: root.querySelector("[data-fallback]"),
    body: root.querySelector("#player-body"),
  };

  let rec = null;
  let feedKey = "";
  let manual = null; // {base, startedAt} when audio is unavailable and the timeline runs alone
  let dragging = false;

  const fmt = (s) => {
    const total = Math.max(0, Math.floor(s));
    return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
  };
  const clockNow = () => {
    if (manual) return manual.base + (manual.startedAt === null ? 0 : (performance.now() - manual.startedAt) / 1000);
    return audio.currentTime || 0;
  };
  const isPlaying = () => (manual ? manual.startedAt !== null : !audio.paused && !audio.ended);

  function colorFor(name, humans) {
    return PALETTE[Math.max(0, humans.indexOf(name)) % PALETTE.length];
  }

  function buildTiles() {
    el.tiles.replaceChildren();
    const humans = rec.roster.filter((p) => p.role === "human").map((p) => p.name);
    humans.forEach((name, i) => {
      const angle = Math.PI / 2 + (2 * Math.PI * i) / humans.length;
      const tile = document.createElement("div");
      tile.className = "tile human";
      tile.dataset.name = name;
      tile.style.left = `${50 + 40 * Math.cos(angle)}%`;
      tile.style.top = `${50 + 36 * Math.sin(angle)}%`;
      tile.innerHTML = `<div class="face" style="background:${colorFor(name, humans)}">${name[0]}</div>
        <span class="name">${name}</span><span class="state">listening</span>`;
      el.tiles.append(tile);
    });
    const agent = document.createElement("div");
    agent.className = "tile agent";
    agent.dataset.name = rec.agent;
    agent.style.left = "50%";
    agent.style.top = "50%";
    agent.innerHTML = `<div class="face">R</div><span class="name">${rec.agent}</span><span class="state">starting</span>`;
    el.tiles.append(agent);
  }

  // Everything on screen at time t, recomputed from the log. The log is small, so no incremental state.
  function stateAt(t) {
    const events = rec.events.filter((e) => e.at <= t);
    const speaking = new Set();
    let lastUtterance = null;
    let agentLine = null;
    let lastDecision = null;
    for (const e of events) {
      if (e.kind === "vad_start") speaking.add(e.speaker);
      else if (e.kind === "vad_end") speaking.delete(e.speaker);
      else if (e.kind === "utterance") lastUtterance = e;
      else if (e.kind === "agent_speech_start") agentLine = { start: e, end: null };
      else if (e.kind === "agent_speech_end" && agentLine && !agentLine.end) agentLine.end = e;
      else if (["decision", "barge_in", "gate", "turn_dropped"].includes(e.kind)) lastDecision = e;
    }
    const agentSpeaking = Boolean(agentLine && !agentLine.end);
    const recent = agentLine && (agentLine.end || agentSpeaking) ? agentLine : null;
    return { events, speaking, lastUtterance, agentLine: recent, agentSpeaking, lastDecision };
  }

  function renderTiles(state) {
    el.tiles.querySelectorAll(".tile.human").forEach((tile) => {
      const name = tile.dataset.name;
      tile.classList.toggle("speaking", state.speaking.has(name));
      tile.querySelector(".state").textContent = state.speaking.has(name) ? "speaking" : "listening";
    });
    const agent = el.tiles.querySelector(".tile.agent");
    agent.classList.toggle("speaking", state.agentSpeaking);
    const reason = state.lastDecision ? state.lastDecision.reason : "";
    agent.querySelector(".state").textContent = state.agentSpeaking ? "speaking" : reason;
  }

  function renderFeed(state) {
    const rows = state.events.filter((e) => ["decision", "gate", "barge_in", "turn_dropped"].includes(e.kind));
    const key = `${rows.length}:${rows.length ? rows[rows.length - 1].at : ""}`;
    if (key === feedKey) return;
    feedKey = key;
    el.feed.replaceChildren();
    rows.forEach((e, i) => {
      const li = document.createElement("li");
      const [label, cls] = verbFor(e);
      li.className = i === rows.length - 1 ? "now" : "";
      li.innerHTML = `<span class="at">${fmt(e.at)}</span><span class="verb ${cls}">${label}</span>
        <span class="reason">${escapeHtml(e.reason || e.text || "")}</span>`;
      el.feed.append(li);
    });
    el.feed.scrollTop = el.feed.scrollHeight;
  }

  function verbFor(e) {
    if (e.kind === "barge_in") return ["stopped", "stop"];
    if (e.kind === "turn_dropped") return ["dropped", "wait"];
    if (e.kind === "gate") return e.speak ? ["gate: spoke", "speak"] : ["gate: silent", "wait"];
    return VERB[e.action] || [e.action, "wait"];
  }

  function renderCaptions(state) {
    const parts = [];
    if (state.lastUtterance) {
      const u = state.lastUtterance;
      parts.push(`<p class="cap"><span class="who">${escapeHtml(u.speaker)}</span>${escapeHtml(u.text)}</p>`);
    }
    if (state.agentLine) {
      const a = state.agentLine;
      const said = a.end ? a.end.heard : a.start.text;
      const cut = a.end && a.end.interrupted ? '<span class="cut">cut off</span>' : "";
      parts.push(`<p class="cap"><span class="who agent-who">${rec.agent}</span>${escapeHtml(said || "")}${cut}</p>`);
    }
    const html = parts.join("") || '<p class="cap" style="color:var(--muted)">Captions appear as people speak.</p>';
    if (el.captions.dataset.key !== html) {
      el.captions.dataset.key = html;
      el.captions.innerHTML = html;
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  function render() {
    const t = clockNow();
    const state = stateAt(t);
    renderTiles(state);
    renderFeed(state);
    renderCaptions(state);
    if (!dragging) el.seek.value = String(Math.round((t / rec.duration_s) * 1000));
    el.clock.textContent = `${fmt(t)} / ${fmt(rec.duration_s)}`;
    el.play.textContent = isPlaying() ? "Pause" : "Play";
    el.play.setAttribute("aria-label", isPlaying() ? "Pause" : "Play");
  }

  function loop() {
    render();
    if (isPlaying()) requestAnimationFrame(loop);
  }

  function useManualClock() {
    if (manual) return;
    el.fallback.hidden = false;
    manual = { base: audio.currentTime || 0, startedAt: null };
  }

  function togglePlay() {
    if (isPlaying()) {
      if (manual) {
        manual.base = clockNow();
        manual.startedAt = null;
      } else audio.pause();
    } else if (manual) {
      manual.startedAt = performance.now();
    } else {
      audio.play().catch(useManualClock);
    }
    requestAnimationFrame(loop);
  }

  function seekTo(seconds) {
    const t = Math.min(Math.max(seconds, 0), rec.duration_s);
    if (manual) {
      manual.base = t;
      if (manual.startedAt !== null) manual.startedAt = performance.now();
    } else {
      audio.currentTime = t;
    }
    feedKey = "";
    render();
  }

  function renderChecks() {
    const passed = rec.checks.filter((c) => c.ok).length;
    el.checksTitle.textContent = `Checks from this run: ${passed} of ${rec.checks.length} passed`;
    el.checks.replaceChildren();
    for (const c of rec.checks) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td class="${c.ok ? "ok" : "bad"}">${c.ok ? "PASS" : "FAIL"}</td>
        <td>${escapeHtml(c.name)}</td><td class="detail">${escapeHtml(c.detail)}</td>`;
      el.checks.append(tr);
    }
  }

  async function load(name) {
    audio.pause();
    manual = null;
    el.fallback.hidden = true;
    const response = await fetch(`replay/${name}.json`);
    if (!response.ok) throw new Error(`replay ${name}: HTTP ${response.status}`);
    rec = await response.json();
    feedKey = "";
    buildTiles();
    renderChecks();
    audio.src = rec.audio ? rec.audio : "";
    audio.load();
    render();
  }

  el.play.addEventListener("click", togglePlay);
  el.seek.addEventListener("pointerdown", () => { dragging = true; });
  el.seek.addEventListener("pointerup", () => { dragging = false; });
  el.seek.addEventListener("input", () => seekTo((el.seek.value / 1000) * rec.duration_s));
  audio.addEventListener("error", useManualClock);
  audio.addEventListener("ended", () => render());
  audio.addEventListener("timeupdate", () => { if (!isPlaying()) render(); });

  const tabs = [...root.querySelectorAll('[role="tab"]')];
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((other) => {
        const on = other === tab;
        other.setAttribute("aria-selected", String(on));
        other.tabIndex = on ? 0 : -1;
      });
      el.body.setAttribute("aria-labelledby", tab.id);
      load(tab.dataset.scenario).catch(showError);
    });
  });

  function showError(err) {
    el.fallback.hidden = false;
    el.fallback.textContent = `The recording could not be loaded (${err.message}). Run make replay after make demo.`;
  }

  load("assistant").catch(showError);
})();
