// Replay for the recorded e2e runs. Everything shown is derived from the agent's event log
// (replay/<scenario>.json) and the room mix (replay/<scenario>.mp3). Nothing here is live.
(() => {
  const SPEAKER_COLORS = ["#7fc8b5", "#e58f78", "#9fb0e8", "#d7c27a"];
  const AGENT_COLOR = "#f2b441";
  const VERBS = { speak: ["spoke", "speak"], wait: ["stayed quiet", "wait"], consult: ["asked the gate", "consult"], stop: ["stopped", "stop"] };
  const CHECK_GROUPS = ["Transcription", "Restraint", "Response", "Barge-in", "Notes"];
  // Checks name a moment in the run. Each rule maps a check name to the agent's own event that proves it.
  const MOMENTS = [
    [/^responded when addressed/, (a) => a.agentSpeech[0]?.start],
    [/^second addressed turn answered/, (a) => a.agentSpeech[1]?.start],
    [/^update delivered on/, (a) => a.agentSpeech[0]?.start],
    [/^update delivered exactly once/, (a) => a.agentSpeech[0]?.start],
    [/^follow-up answered/, (a) => a.agentSpeech[1]?.start],
    [/^unknown question deferred/, (a) => a.agentSpeech[2]?.start],
    [/^agent audio reached/, (a) => a.agentSpeech[0]?.start],
    [/^silent before being addressed/, (a) => a.agentSpeech[0]?.start],
    [/^silent until/, (a) => a.agentSpeech[0]?.start],
    [/^stayed silent on an unaddressed/, (a) => a.gates[0]?.at],
    [/barge-in|truncated/, (a) => a.barges[0]?.at],
  ];

  const root = document.querySelector("[data-player]");
  const heroStage = document.querySelector("[data-hero-stage]");
  if (!root || !heroStage) return;

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const audio = root.querySelector("[data-audio]");
  const el = {
    stage: root.querySelector("[data-stage]"),
    feed: root.querySelector("[data-feed]"),
    timeline: root.querySelector("[data-timeline]"),
    transcript: document.querySelector("[data-captions]"),
    checks: document.querySelector("[data-checks]"),
    checksTitle: document.querySelector("[data-checks-title]"),
    title: root.querySelector("[data-title]"),
    play: root.querySelector("[data-play]"),
    seek: root.querySelector("[data-seek]"),
    clock: root.querySelector("[data-clock]"),
    sound: root.querySelector("[data-sound]"),
    rate: root.querySelector("[data-rate]"),
    fallback: root.querySelector("[data-fallback]"),
    body: root.querySelector("#player-body"),
    heroClock: document.querySelector("[data-hero-clock]"),
    heroNow: document.querySelector("[data-hero-now]"),
  };

  const cache = new Map();
  let current = null; // { rec, a, ring, timeline, feed, transcript, checks }
  let manual = null; // { base, startedAt } when audio is unavailable and the timeline runs alone
  let rate = 1;
  let soundOn = true;
  let dragging = false;
  let frame = 0;

  // ---- small helpers -------------------------------------------------------

  const fmt = (s) => {
    const total = Math.max(0, Math.floor(s));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const el2 = (tag, cls, html) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (html !== undefined) node.innerHTML = html;
    return node;
  };

  function loadRecording(name) {
    if (!cache.has(name)) {
      cache.set(
        name,
        fetch(`replay/${name}.json`).then((r) => {
          if (!r.ok) throw new Error(`replay ${name}: HTTP ${r.status}`);
          return r.json();
        }),
      );
    }
    return cache.get(name);
  }

  // Derived once per recording: lanes, agent speech spans, gates, barge-ins, transcript lines.
  function analyse(rec) {
    const humans = rec.roster.filter((p) => p.role === "human").map((p) => p.name);
    const color = (name) => {
      const i = humans.indexOf(name);
      return i < 0 ? AGENT_COLOR : SPEAKER_COLORS[i % SPEAKER_COLORS.length];
    };
    const speech = [];
    const agentSpeech = [];
    const open = new Map();
    let agentOpen = null;
    for (const e of rec.events) {
      if (e.kind === "vad_start") open.set(e.speaker, e.at);
      else if (e.kind === "vad_end" && open.has(e.speaker)) {
        speech.push({ lane: e.speaker, start: open.get(e.speaker), end: e.at });
        open.delete(e.speaker);
      } else if (e.kind === "agent_speech_start") agentOpen = { start: e.at, text: e.text || "" };
      else if (e.kind === "agent_speech_end" && agentOpen) {
        agentSpeech.push({ ...agentOpen, end: e.at, heard: e.heard ?? agentOpen.text, interrupted: Boolean(e.interrupted) });
        agentOpen = null;
      }
    }
    if (agentOpen) agentSpeech.push({ ...agentOpen, end: rec.duration_s, heard: agentOpen.text, interrupted: false });
    return {
      humans,
      color,
      speech,
      agentSpeech,
      gates: rec.events.filter((e) => e.kind === "gate"),
      barges: rec.events.filter((e) => e.kind === "barge_in"),
      utterances: rec.events.filter((e) => e.kind === "utterance"),
      decisions: rec.events.filter((e) => ["decision", "gate", "barge_in", "turn_dropped"].includes(e.kind)),
    };
  }

  // Everything on screen at time t, recomputed from the log. The log is small, so no incremental state.
  function stateAt(rec, t) {
    const speaking = new Set();
    let agentSpeaking = false;
    let lastDecision = null;
    let lastGate = null;
    for (const e of rec.events) {
      if (e.at > t) continue;
      if (e.kind === "vad_start") speaking.add(e.speaker);
      else if (e.kind === "vad_end") speaking.delete(e.speaker);
      else if (e.kind === "agent_speech_start") agentSpeaking = true;
      else if (e.kind === "agent_speech_end") agentSpeaking = false;
      else if (e.kind === "gate") lastGate = e;
      else if (["decision", "barge_in", "turn_dropped"].includes(e.kind)) lastDecision = e;
    }
    const gateActive = Boolean(lastGate && t - lastGate.at < 2.5);
    return { speaking, agentSpeaking, lastDecision, gateActive };
  }

  function verbFor(e) {
    if (e.kind === "barge_in") return ["stopped", "stop"];
    if (e.kind === "turn_dropped") return ["dropped", "wait"];
    if (e.kind === "gate") return e.speak ? ["gate: spoke", "speak"] : ["gate: silent", "wait"];
    return VERBS[e.action] || [e.action, "wait"];
  }

  const reasonOf = (e) => e.reason || e.text || (e.kind === "gate" ? (e.speak ? "LLM gate said yes" : "LLM gate: no contribution") : "");

  // Consecutive repeats of the same verb and reason are one decision as far as a reader is concerned.
  function feedRows(decisions) {
    return decisions.filter((e, i, all) => {
      if (i === 0) return true;
      const prev = all[i - 1];
      return verbFor(prev)[0] !== verbFor(e)[0] || reasonOf(prev) !== reasonOf(e);
    });
  }

  function checkGroup(name) {
    if (/^transcribed/.test(name)) return "Transcription";
    if (/silent/.test(name)) return "Restraint";
    if (/barge-in|truncated/.test(name)) return "Barge-in";
    if (/^notes:/.test(name)) return "Notes";
    return "Response";
  }

  function checkMoment(check, a) {
    const heard = check.name.match(/^transcribed and attributed: (\S+) '(.*)'$/);
    if (heard) {
      // Check names quote the agent's transcript, but a few differ by a word or a space, so compare letters only.
      const key = (text) => text.toLowerCase().replace(/[^a-z0-9]/g, "");
      const fragment = key(heard[2]).slice(0, 16);
      const line = a.utterances.find((u) => u.speaker === heard[1] && key(u.text).startsWith(fragment));
      return line ? line.at : null;
    }
    const rule = MOMENTS.find(([pattern]) => pattern.test(check.name));
    const at = rule ? rule[1](a) : null;
    return typeof at === "number" ? at : null;
  }

  // ---- ring: the participant table, shared by the hero and the player --------

  function mountRing(container, rec, a, { compact = false } = {}) {
    container.replaceChildren();
    const humans = rec.roster.filter((p) => p.role === "human").map((p) => p.name);
    const tiles = new Map();
    humans.forEach((name, i) => {
      const angle = Math.PI / 2 + (2 * Math.PI * i) / humans.length;
      const tile = el2("div", "tile human");
      tile.style.left = `${50 + 40 * Math.cos(angle)}%`;
      tile.style.top = `${50 + 36 * Math.sin(angle)}%`;
      tile.innerHTML = `<div class="face" style="background:${a.color(name)}">${esc(name[0])}</div>
        <span class="name">${esc(name)}</span><span class="state">listening</span>`;
      container.append(tile);
      tiles.set(name, tile);
    });
    const agent = el2("div", "tile agent");
    agent.style.left = "50%";
    agent.style.top = "50%";
    agent.innerHTML = `<div class="face">R</div><span class="name">${esc(rec.agent)}</span><span class="state">starting</span>`;
    container.append(agent);
    if (compact) container.dataset.compact = "true";

    return {
      update(state) {
        for (const [name, tile] of tiles) {
          const on = state.speaking.has(name);
          tile.classList.toggle("speaking", on);
          tile.querySelector(".state").textContent = on ? "speaking" : "listening";
        }
        const reason = state.lastDecision ? reasonOf(state.lastDecision) : "";
        agent.classList.toggle("speaking", state.agentSpeaking);
        agent.classList.toggle("gate", state.gateActive);
        agent.querySelector(".state").textContent = state.agentSpeaking ? "speaking" : state.gateActive ? "asking the gate" : reason;
      },
    };
  }

  // ---- timeline: who spoke when, the agent's turns, gate calls and barge-ins --

  function mountTimeline(container, rec, a, seek) {
    const D = rec.duration_s;
    const pct = (t) => `${(Math.min(Math.max(t, 0), D) / D) * 100}%`;
    const span = (s, e) => `${((Math.min(e, D) - s) / D) * 100}%`;
    const playheads = [];
    const bodies = [];
    container.replaceChildren();

    const row = (name, cls) => {
      const r = el2("div", "tl__row");
      r.append(el2("span", `tl__name${cls ? ` tl__name--${cls}` : ""}`, esc(name)));
      const body = el2("div", `tl__body${cls ? ` tl__body--${cls}` : ""}`);
      body.setAttribute("role", "presentation");
      body.addEventListener("click", (ev) => {
        const rect = body.getBoundingClientRect();
        seek(((ev.clientX - rect.left) / rect.width) * D);
      });
      const head = el2("div", "tl__playhead");
      head.style.left = "0%";
      body.append(head);
      playheads.push(head);
      bodies.push(body);
      r.append(body);
      container.append(r);
      return body;
    };

    for (const name of a.humans) {
      const body = row(name);
      for (const s of a.speech.filter((x) => x.lane === name)) {
        const seg = el2("i", "tl__seg");
        seg.style.left = pct(s.start);
        seg.style.width = span(s.start, s.end);
        seg.style.background = a.color(name);
        seg.title = `${name} speaking, ${fmt(s.start)} to ${fmt(s.end)}`;
        body.append(seg);
      }
    }

    const agentBody = row(rec.agent, "agent");
    for (const s of a.agentSpeech) {
      const seg = el2("i", `tl__seg tl__seg--agent${s.interrupted ? " tl__seg--interrupted" : ""}`);
      seg.style.left = pct(s.start);
      seg.style.width = span(s.start, s.end);
      seg.title = `${rec.agent} speaking, ${fmt(s.start)} to ${fmt(s.end)}`;
      agentBody.append(seg);
    }
    for (const g of a.gates) {
      const mark = el2("i", "tl__gate");
      mark.style.left = pct(g.at);
      mark.title = `Asked the LLM gate at ${fmt(g.at)}`;
      agentBody.append(mark);
    }
    for (const body of bodies) {
      for (const b of a.barges) {
        const line = el2("i", "tl__barge");
        line.style.left = pct(b.at);
        if (body === bodies[0]) line.append(el2("span", "", "barge-in"));
        body.append(line);
      }
    }

    const axis = el2("div", "tl__axis");
    axis.append(el2("span", "", ""));
    const ticks = el2("div", "tl__ticks");
    for (let s = 0; s <= D; s += 10) {
      const label = el2("span", "", fmt(s));
      label.style.left = pct(s);
      ticks.append(label);
    }
    axis.append(ticks);
    container.append(axis);
    container.append(
      el2(
        "div",
        "tl__legend",
        `<span><i style="background:${SPEAKER_COLORS[0]}"></i>speaking</span>
         <span><i style="background:${AGENT_COLOR}"></i>${esc(rec.agent)} speaking</span>
         <span><i style="background:repeating-linear-gradient(45deg,${AGENT_COLOR} 0 3px,#8a6a25 3px 5px)"></i>cut off by a person</span>
         <span><i style="background:#c7b0e6;transform:rotate(45deg);width:7px;height:7px"></i>asked the LLM gate</span>
         <span><i style="background:transparent;border-left:2px dashed #ff9a7a;height:12px"></i>barge-in</span>
         <span>click a lane to jump</span>`,
      ),
    );

    return {
      update(t) {
        for (const head of playheads) head.style.left = pct(t);
      },
    };
  }

  // ---- decision log -----------------------------------------------------------

  function mountFeed(list, a, seek) {
    const rows = feedRows(a.decisions);
    list.replaceChildren();
    const items = rows.map((e) => {
      const [label, cls] = verbFor(e);
      const li = el2("li");
      li.innerHTML = `<button type="button" class="feed-row" data-at="${e.at}" aria-label="${esc(fmt(e.at))}: ${esc(label)}. ${esc(reasonOf(e))}">
        <span class="at">${fmt(e.at)}</span><span class="verb ${cls}">${esc(label)}</span>
        <span class="reason">${esc(reasonOf(e))}</span></button>`;
      li.querySelector("button").addEventListener("click", (ev) => seek(Number(ev.currentTarget.dataset.at)));
      list.append(li);
      return { at: e.at, li };
    });
    let last = -1;
    return {
      update(t) {
        let now = -1;
        items.forEach((item, i) => {
          if (item.at <= t) now = i;
          item.li.classList.toggle("later", item.at > t);
        });
        if (now === last) return;
        last = now;
        items.forEach((item, i) => item.li.classList.toggle("now", i === now));
        if (now >= 0) list.scrollTop = Math.max(0, items[now].li.offsetTop - list.clientHeight / 3);
      },
    };
  }

  // ---- transcript: every line in order; lines not yet reached are dimmed ----

  function mountTranscript(list, rec, a, seek) {
    const lines = [
      ...a.utterances.map((u) => ({ at: u.at, who: u.speaker, text: u.text, agent: false, color: a.color(u.speaker) })),
      ...a.agentSpeech.map((s) => ({ at: s.start, who: rec.agent, text: s.heard, agent: true, cut: s.interrupted })),
    ].sort((x, y) => x.at - y.at);
    list.replaceChildren();
    const items = lines.map((line) => {
      const li = el2("li", `tx${line.agent ? " tx--agent" : ""}`);
      li.innerHTML = `<span class="tx__meta"><span class="tx__who${line.agent ? " tx__who--agent" : ""}" ${
        line.agent ? "" : `style="color:${line.color}"`
      }>${esc(line.who)}</span>${fmt(line.at)}</span>
        <span class="tx__text">${esc(line.text)}${line.cut ? '<span class="tx__cut">cut off</span>' : ""}</span>`;
      li.tabIndex = 0;
      li.setAttribute("role", "button");
      li.setAttribute("aria-label", `${fmt(line.at)} ${line.who}: ${line.text}`);
      li.addEventListener("click", () => seek(line.at));
      li.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          seek(line.at);
        }
      });
      list.append(li);
      return { at: line.at, li };
    });
    let last = -1;
    return {
      update(t) {
        let now = -1;
        items.forEach((item, i) => {
          if (item.at <= t) now = i;
          item.li.classList.toggle("tx--later", item.at > t);
        });
        if (now === last) return;
        last = now;
        items.forEach((item, i) => item.li.classList.toggle("tx--now", i === now));
        if (now >= 0) list.scrollTop = Math.max(0, items[now].li.offsetTop - list.clientHeight / 3);
      },
    };
  }

  // ---- checks, grouped, each tied to a moment in the run ----------------------

  function mountChecks(rec, a, seek) {
    const passed = rec.checks.filter((c) => c.ok).length;
    el.checksTitle.textContent = `Checks from this run: ${passed} of ${rec.checks.length} passed`;
    const groups = CHECK_GROUPS.map((title) => ({ title, checks: rec.checks.filter((c) => checkGroup(c.name) === title) }))
      .filter((g) => g.checks.length > 0);
    el.checks.replaceChildren();
    const buttons = [];
    for (const g of groups) {
      const ok = g.checks.filter((c) => c.ok).length;
      const section = el2("section", `check-group${g.title === "Transcription" ? " check-group--wide" : ""}`);
      section.setAttribute("aria-label", g.title);
      section.innerHTML = `<h4>${g.title} <span class="${ok === g.checks.length ? "" : "bad"}">${ok} of ${g.checks.length}</span></h4>`;
      for (const c of g.checks) {
        const row = el2("div", "check");
        const at = checkMoment(c, a);
        const jump = at === null ? '<span class="check__none">no moment</span>' : `<button type="button" class="check__at" data-at="${at}" aria-label="Jump to ${fmt(at)} in the run">${fmt(at)}</button>`;
        row.innerHTML = `<span class="${c.ok ? "check__ok" : "check__bad"}">${c.ok ? "PASS" : "FAIL"}</span>
          <span class="check__name">${esc(c.name)}</span>${jump}
          <span class="check__detail">${esc(c.detail)}</span>`;
        const button = row.querySelector(".check__at");
        if (button) {
          button.addEventListener("click", () => seek(at - 0.6, { play: true }));
          buttons.push({ at, button });
        }
        section.append(row);
      }
      el.checks.append(section);
    }
    let lastNear = null;
    return {
      update(t) {
        const near = buttons.filter((b) => Math.abs(b.at - t) < 1.2);
        if (near.length === lastNear?.length && near.every((b, i) => b.button === lastNear[i]?.button)) return;
        buttons.forEach((b) => b.button.removeAttribute("aria-current"));
        near.forEach((b) => b.button.setAttribute("aria-current", "true"));
        lastNear = near;
      },
    };
  }

  // ---- hero: the same ring, a silent loop of the run -------------------------

  function startHero(rec, a) {
    const ring = mountRing(heroStage, rec, a, { compact: true });
    const end = rec.duration_s;
    const paint = (t) => {
      const state = stateAt(rec, t);
      ring.update(state);
      el.heroClock.textContent = fmt(t);
      el.heroNow.textContent = state.lastDecision ? `${verbFor(state.lastDecision)[0]}: ${reasonOf(state.lastDecision)}` : "Waiting for the call to start";
    };
    const firstSpeech = a.agentSpeech[0]?.start ?? 0;
    if (reduced.matches) {
      paint(firstSpeech + 1);
      return;
    }
    const loop = end + 4;
    let origin = null;
    let raf = 0;
    const tick = (now) => {
      if (origin === null) origin = now;
      paint(Math.min(((now - origin) / 1000) % loop, end));
      raf = requestAnimationFrame(tick);
    };
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.some((entry) => entry.isIntersecting);
      if (visible && !raf) raf = requestAnimationFrame(tick);
      if (!visible && raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    });
    observer.observe(heroStage);
  }

  // ---- player clock: the audio element, or the timeline alone if audio fails ----

  const playing = () => (manual ? manual.startedAt !== null : !audio.paused && !audio.ended);

  function now() {
    if (manual) return manual.base + (manual.startedAt === null ? 0 : ((performance.now() - manual.startedAt) / 1000) * rate);
    return audio.currentTime || 0;
  }

  function rebase() {
    if (!manual) return;
    manual.base = now();
    if (manual.startedAt !== null) manual.startedAt = performance.now();
  }

  function draw() {
    if (!current) return;
    const t = now();
    const state = stateAt(current.rec, t);
    current.ring.update(state);
    current.timeline.update(t);
    current.feed.update(t);
    current.transcript.update(t);
    current.checks.update(t);
    if (!dragging) el.seek.value = String(Math.round((t / current.rec.duration_s) * 1000));
    el.clock.textContent = `${fmt(t)} / ${fmt(current.rec.duration_s)}`;
    const isPlaying = playing();
    el.play.textContent = isPlaying ? "Pause" : "Play";
    el.play.setAttribute("aria-label", isPlaying ? "Pause" : "Play");
  }

  function loop() {
    cancelAnimationFrame(frame);
    const step = () => {
      draw();
      if (playing()) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
  }

  function useManualClock() {
    if (manual) return;
    el.fallback.hidden = false;
    manual = { base: audio.currentTime || 0, startedAt: null };
  }

  function pause() {
    if (manual) {
      rebase();
      manual.startedAt = null;
    } else audio.pause();
    draw();
  }

  function setSound(on) {
    soundOn = on;
    audio.muted = !on;
    el.sound.textContent = on ? "Sound on" : "Sound off";
    el.sound.setAttribute("aria-pressed", String(on));
  }

  // fromGesture: a press of Play is a user gesture, so sound is allowed. Scroll autoplay is muted, which browsers allow.
  function play({ fromGesture }) {
    if (fromGesture) setSound(true);
    if (manual) {
      manual.startedAt = performance.now();
      loop();
      return;
    }
    audio.play().then(loop).catch((err) => {
      if (err.name !== "NotAllowedError") useManualClock();
      if (manual) {
        manual.startedAt = performance.now();
        loop();
      }
    });
  }

  function togglePlay() {
    if (playing()) pause();
    else play({ fromGesture: true });
  }

  function seekTo(seconds, { play: shouldPlay = false } = {}) {
    if (!current) return;
    const t = Math.min(Math.max(seconds, 0), current.rec.duration_s);
    if (manual) {
      manual.base = t;
      if (manual.startedAt !== null) manual.startedAt = performance.now();
    } else {
      audio.currentTime = t;
    }
    draw();
    if (shouldPlay && !playing()) play({ fromGesture: true });
  }

  // ---- scenario selection -------------------------------------------------------

  async function select(name) {
    pause();
    manual = null;
    el.fallback.hidden = true;
    const rec = await loadRecording(name);
    const a = analyse(rec);
    const seek = (t, opts) => seekTo(t, opts);
    current = {
      rec,
      a,
      ring: mountRing(el.stage, rec, a),
      timeline: mountTimeline(el.timeline, rec, a, seek),
      feed: mountFeed(el.feed, a, seek),
      transcript: mountTranscript(el.transcript, rec, a, seek),
      checks: mountChecks(rec, a, seek),
    };
    el.title.textContent = rec.title;
    el.feed.scrollTop = 0;
    audio.src = rec.audio || "";
    audio.load();
    audio.playbackRate = rate;
    audio.muted = !soundOn;
    draw();
  }

  // ---- wiring ---------------------------------------------------------------------

  el.play.addEventListener("click", togglePlay);
  el.sound.addEventListener("click", () => setSound(!soundOn));
  el.rate.addEventListener("change", () => {
    rebase();
    rate = Number(el.rate.value);
    audio.playbackRate = rate;
    draw();
  });
  el.seek.addEventListener("pointerdown", () => { dragging = true; });
  el.seek.addEventListener("pointerup", () => { dragging = false; });
  el.seek.addEventListener("input", () => seekTo((el.seek.value / 1000) * (current?.rec.duration_s ?? 0)));
  audio.addEventListener("error", useManualClock);
  audio.addEventListener("ended", () => draw());
  audio.addEventListener("timeupdate", () => { if (!playing()) draw(); });

  const tabs = [...root.querySelectorAll('[role="tab"]')];
  function selectTab(tab) {
    tabs.forEach((other) => {
      const on = other === tab;
      other.setAttribute("aria-selected", String(on));
      other.tabIndex = on ? 0 : -1;
    });
    el.body.setAttribute("aria-labelledby", tab.id);
    tab.focus();
    select(tab.dataset.scenario).catch(showError);
  }
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", (ev) => {
      if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
      ev.preventDefault();
      const next = tabs[(i + (ev.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      selectTab(next);
    });
  });

  function showError(err) {
    el.fallback.hidden = false;
    el.fallback.textContent = `The recording could not be loaded (${err.message}). Run make replay after make demo.`;
  }

  // Autoplay the replay the first time it is at least a third visible. Muted, so browsers allow it.
  if (!reduced.matches) {
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting) || playing() || !current) return;
      observer.disconnect();
      setSound(false);
      play({ fromGesture: false });
    }, { threshold: 0.35 });
    observer.observe(root);
  }

  for (const button of document.querySelectorAll("[data-copy-target]")) {
    button.addEventListener("click", async () => {
      const source = document.getElementById(button.dataset.copyTarget);
      try {
        await navigator.clipboard.writeText(source.innerText);
        button.dataset.state = "copied";
        button.textContent = "Copied";
      } catch {
        button.textContent = "Select to copy";
      }
      setTimeout(() => {
        button.dataset.state = "";
        button.textContent = "Copy";
      }, 1800);
    });
  }

  loadRecording("assistant")
    .then((rec) => {
      startHero(rec, analyse(rec));
      return select("assistant");
    })
    .catch(showError);
})();
