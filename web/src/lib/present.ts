import { type AgentLabel, type Decision } from "../types";

// Muted tones that stay readable on the dark table. Each person keeps the same colour in captions and seats.
const SPEAKER_TONES = ["#8fc7ad", "#e0a58f", "#a9b8e6", "#d7c27a", "#c9a8d8", "#8fc1cf"] as const;

export function speakerColor(name: string): string {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return SPEAKER_TONES[hash % SPEAKER_TONES.length];
}

export function labelText(label: AgentLabel): string {
  switch (label) {
    case "listening":
      return "listening";
    case "wants_to_speak":
      return "wants to speak";
    case "thinking":
      return "asking the gate";
    case "speaking":
      return "speaking";
  }
}

export type Verb = "spoke" | "stayed quiet" | "waiting for a gap" | "asked the gate" | "stopped";

/** The short verb for a decision row. The reason string carries the detail. */
export function verbFor(decision: Pick<Decision, "label" | "reason">): Verb {
  if (decision.label === "speaking") return "spoke";
  if (decision.label === "thinking") return "asked the gate";
  if (decision.label === "wants_to_speak") return "waiting for a gap";
  return /talked over|stopping/.test(decision.reason) ? "stopped" : "stayed quiet";
}

/** m:ss from seconds since the browser joined. */
export function clock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
