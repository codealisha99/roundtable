export type AgentLabel = "listening" | "wants_to_speak" | "speaking" | "thinking";

/** Messages the agent publishes on the "roundtable" data topic. */
export type AgentMessage =
  | { kind: "state"; label: AgentLabel; reason: string }
  | { kind: "caption"; speaker: string; text: string; start_ms: number }
  | { kind: "agent_caption"; text: string };

export interface Caption {
  id: number;
  speaker: string;
  text: string;
  agent: boolean;
  /** Seconds since this browser joined the room. */
  at: number;
}

/** One change of the agent's state, with the reason the floor manager gave for it. */
export interface Decision {
  id: number;
  label: AgentLabel;
  reason: string;
  /** Seconds since this browser joined the room. */
  at: number;
}

export interface AgentStatus {
  label: AgentLabel;
  reason: string;
  decisions: readonly Decision[];
}

export const AGENT_IDENTITY_PREFIX = "roundtable-agent";
