# Roundtable

A voice agent that joins a multi-person group call as one participant and behaves like a good meeting attendee. Several humans talk, sometimes over each other. The agent tracks who said what, decides whether a turn is for it, waits for a real gap, speaks when it is asked or has something useful to add, and stops immediately when someone talks over it.

The hard part is multi-party turn-taking, not the 1:1 voice loop. Most voice agents assume one speaker. Here the floor manager is a pure, well-tested state machine over the transcript and per-speaker voice activity. It knows nothing about LiveKit, so every turn-taking rule is checked against scripted timelines.

**Keyless demo:** `make install && make demo` runs LiveKit in Docker, joins three synthesised speakers, and asserts the agent's behaviour from its own event log.

## Architecture

```mermaid
flowchart LR
  subgraph Humans
    B[Browser client<br/>React + livekit-client]
    S[Simulated speakers<br/>macOS say -> WAV]
  end
  LK[(LiveKit server<br/>Docker, dev mode)]
  T[Token API<br/>:4501]
  B -- POST /api/token --> T
  B <-- WebRTC audio + data topic 'roundtable' --> LK
  S <--> LK
  subgraph Agent [roundtable agent, Python]
    A[Per-speaker track<br/>AudioStream 16 kHz]
    V[Silero VAD]
    W[STT<br/>faster-whisper / Deepgram / OpenAI]
    F[Floor manager<br/>pure: apply + evaluate]
    G[LLM gate<br/>only for ambiguous silences]
    R[Reply + meeting memory<br/>Anthropic / scripted]
    P[TTS<br/>Piper / ElevenLabs / OpenAI]
    O[Paced playback<br/>barge-in truncates text]
  end
  LK --> A --> V --> W -- final utterance --> F
  V -- start/end --> F
  F -- consult --> G --> F
  F -- speak --> R --> P --> O --> LK
  F -- stop --> O
  F -. state + captions .-> LK
  F -. JSONL event log .-> E[(out/events.jsonl)]
```

Each human gets their own audio stream, their own VAD, and their own STT task. The agent sees speech *starts* immediately (for barge-in) and speech *finals* when STT finishes, so a slow transcription never delays interruption.

## What's hard, and how it is solved

1. **Floor manager as a pure module.** `src/roundtable/floor/` has no LiveKit imports. `apply(state, event)` is a reducer over immutable events (`Utterance`, `Activity`, `AgentStarted`, `AgentEnded`). `evaluate(state, now)` returns `wait | speak | stop | consult` with a human-readable reason. Those reasons are what the web panel and the event log show, so "why it stayed silent" is never a mystery.
2. **Addressing without a model in the loop.** Cheap text cues decide most turns: the agent's name or alias, a name at the start of a line (`Dan, can you...`), a question with silence after it, a follow-up in the 20 s after the agent spoke. A name *inside* a sentence does not count ("I think Dan is right" is not addressed to Dan).
3. **Gaps are measured, not guessed.** The agent never starts while anyone has VAD open. It waits 700 ms after someone addressing it, 1.5 s after an unanswered group question, and 1.2 s of quiet after any overlap before starting anything.
4. **Two humans mid-exchange.** Three alternating human turns between two people inside 30 s is a back-and-forth. The agent backs off from unaddressed questions. Addressing it by name still works.
5. **Barge-in with honest truncation.** Human speech over the agent for 250 ms cancels playback. The agent counts only the audio that actually left the speaker (pushed minus still-queued) and truncates its own transcript line to that share of words. The meeting record shows what was heard, not what was planned.
6. **Heuristic first, LLM for ambiguity.** The LLM gate is consulted only for decision-relevant statements that nobody answered (at most once per 20 s). It returns JSON, and malformed output fails closed. Approval is re-checked against the floor before anything plays, so a turn never starts over someone who began talking during the model call.
7. **Standup proxy mode.** `roundtable agent --mode standup --absent Sam --update "..." --notes notes.md` answers to "Sam", delivers the prepared update once, answers follow-ups only from the notes, and says it will take anything else back to Sam.

## Quickstart

Prerequisites: macOS (uses `say` for the simulated speakers), Docker, uv (Python 3.12), pnpm.

```bash
make install          # uv sync + pnpm install
make test             # 37 unit tests: floor timelines, meeting memory, prompts, token API
make demo             # keyless end-to-end run; prints the attributed transcript, decisions, checks
```

`make demo` writes `out/e2e/events.jsonl` (the agent's full event log), `out/e2e/meeting.md` (notes), and `out/e2e/agent.log`. It stops the LiveKit container when it finishes.

To use the web client with a live agent:

```bash
docker run -d --name roundtable-livekit -p 7880:7880 -p 7881:7881 -p 7882:7882/udp \
  livekit/livekit-server --dev --bind 0.0.0.0 --node-ip 127.0.0.1
make agent            # in one terminal: the agent joins room "roundtable"
make serve            # in another: token API on 4501
make web              # builds web/dist; then: cd web && pnpm preview  (http://127.0.0.1:4500)
```

Open the web app, enter a name, and take a seat. The agent is named "Roundtable" and responds to "Roundtable" or "round table". Meeting notes are written to `out/meeting.md` when the agent exits (Ctrl-C).

### Real providers

Set keys in `.env` (see `.env.example`). The provider is selected by env:

- LLM: `ANTHROPIC_API_KEY` selects Anthropic (`ROUNDTABLE_MODEL`, default `claude-sonnet-5-5`). `ROUNDTABLE_LLM=openai` uses any OpenAI-compatible URL (Ollama, OpenRouter, Groq).
- STT: `DEEPGRAM_API_KEY` selects Deepgram. `ROUNDTABLE_STT=openai` uses OpenAI transcription. Default is local faster-whisper.
- TTS: `ELEVENLABS_API_KEY` selects ElevenLabs. `ROUNDTABLE_TTS=openai` uses OpenAI speech. Default is local Piper.

The keyless demo pins `ROUNDTABLE_LLM=scripted`, `ROUNDTABLE_STT=local`, and `ROUNDTABLE_TTS=piper`, so it never reaches a cloud provider even when keys are exported.

## Design decisions and trade-offs

- **Pure floor, thin runtime.** The runtime (`agent.py`) only translates LiveKit events into floor events and floor verdicts into speech. That made the most important logic testable in milliseconds with scripted timelines.
- **Per-speaker pipelines, not a mixed stream.** Mixing would lose attribution and make barge-in detection depend on the mixture. Separate tracks cost a few more VAD instances, which Silero handles cheaply on CPU.
- **Deterministic memory extraction.** Decisions, action items and notes come from cue phrases plus addressing, so they work offline and are testable. A rolling LLM summary sits on top. Owners come from "I'll ..." (the speaker) or a name in the sentence.
- **Keyless first, cloud by env.** The keyless path is what the demo proves. Cloud adapters are small and selected by key presence, so the same code path runs in both modes.
- **Event log as the contract.** The end-to-end test asserts on the agent's own JSONL log rather than scraping console output. The same log drives the debugging workflow.
- **Dev keys.** `LIVEKIT_API_KEY=devkey` and `LIVEKIT_API_SECRET=secret` are the `livekit-server --dev` defaults. Production needs real keys and a real secret.

## Verification status

| What | Status |
| --- | --- |
| Floor manager, meeting memory, prompt builders, token API (`make test`, 37 tests) | Passing |
| Keyless end-to-end demo (`make demo`): LiveKit in Docker, agent subprocess, 3 simulated speakers, 17 checks | Passing |
| Web client: loads, joins the LiveKit room with a fake microphone, shows the agent panel and the self tile (headless Chromium via Playwright) | Passing (`cd web && pnpm verify`, needs the live stack) |
| Local providers: faster-whisper, Piper, Silero VAD | Exercised by the demo |
| Anthropic and OpenAI-compatible LLM paths | **Not exercised**: no API keys on this machine. Code follows the SDK and REST shapes; verify before relying on it |
| Deepgram, ElevenLabs, OpenAI speech adapters | **Not exercised**: no keys. Plain REST, written against the documented endpoints |
| Standup proxy mode | Unit-tested (delivery once, notes-only follow-ups, unknown answers). Not in the live demo |

## Limitations and next steps

- **Partial transcripts.** STT runs per utterance when VAD closes the segment. Captions appear after the speaker pauses, not word by word. Streaming STT (for example Deepgram live or a rolling whisper window) would tighten captions and let the floor react earlier.
- **Echo.** If a human's microphone picks up the agent's speech through speakers, the agent can hear itself as a barge-in. Browser echo cancellation helps. Headphones are the reliable answer. Speaker-level echo suppression is not implemented.
- **Speaker identity** is the display name from the token. Two people with the same name would collapse into one speaker.
- **Heuristics are tuned on one scripted meeting.** Thresholds (700 ms gap, 250 ms barge-in, 1.5 s group-question silence) are reasonable defaults, not measured against real meetings. A labelled meeting corpus would be the next step.
- **Gate cost bound.** The LLM gate runs at most once per 20 s, and only for decision-relevant statements. A smarter gate (embedding-based relevance) would need evaluation data.
- **Piper voices download on first run** from Hugging Face. Offline machines need the voice pre-fetched into `ROUNDTABLE_VOICE_DIR`.
- **Mac-only demo.** The simulated speakers use `say`. The agent itself is cross-platform; the demo could use Piper for speech synthesis elsewhere.

## Layout

```
src/roundtable/floor/     pure floor manager: events, addressing cues, reducer + gate
src/roundtable/meeting/   transcript retrieval and meeting memory
src/roundtable/speech/    per-speaker pipeline, paced playback, STT/TTS adapters
src/roundtable/agent.py   LiveKit runtime: wiring, turns, barge-in, state broadcast
src/roundtable/respond.py prompt builders, replies, rolling summary, LLM gate prompt
src/roundtable/e2e/       keyless end-to-end harness and assertions
web/                      React client: the table, agent panel, captions
tests/                    pytest suites (floor timelines, meeting, units)
```
