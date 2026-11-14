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
}

export interface AgentStatus {
  label: AgentLabel;
  reason: string;
  history: readonly string[];
}

export const AGENT_IDENTITY_PREFIX = "roundtable-agent";
