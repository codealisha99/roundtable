import { type Participant } from "livekit-client";
import { type AgentStatus } from "../types";
import { isAgent } from "../lib/useRoom";

interface Props {
  participants: Participant[];
  speakers: ReadonlySet<string>;
  agent: AgentStatus;
  agentPresent: boolean;
  self: string;
}

const RING_RADIUS = 38; // percent of the table box

function seatPosition(index: number, count: number): { left: string; top: string } {
  const angle = (index / Math.max(count, 1)) * Math.PI * 2 - Math.PI / 2;
  const left = 50 + RING_RADIUS * Math.cos(angle);
  const top = 50 + RING_RADIUS * Math.sin(angle);
  return { left: `${left.toFixed(2)}%`, top: `${top.toFixed(2)}%` };
}

function initials(name: string): string {
  return name.split(/\s+/).map((part) => part[0] ?? "").join("").slice(0, 2).toUpperCase() || "?";
}

export function Table({ participants, speakers, agent, agentPresent, self }: Props) {
  const humans = participants.filter((p) => !isAgent(p));
  return (
    <section className="table" aria-label="Participants around the table">
      <div className={`orb orb--${agent.label}`} aria-live="polite">
        <span className="orb__core">{agentPresent ? "Roundtable" : "Waiting"}</span>
        <span className="orb__state">{labelText(agent.label)}</span>
      </div>
      {humans.map((p, index) => {
        const speaking = speakers.has(p.identity) || p.isSpeaking;
        const name = p.name || p.identity;
        return (
          <div
            key={p.identity}
            className={`seat ${speaking ? "seat--speaking" : ""}`}
            style={seatPosition(index, humans.length)}
          >
            <div className="seat__avatar" aria-hidden="true">{initials(name)}</div>
            <div className="seat__name">
              {name}
              {p.identity === self ? <span className="seat__you"> (you)</span> : null}
            </div>
          </div>
        );
      })}
    </section>
  );
}

export function labelText(label: AgentStatus["label"]): string {
  switch (label) {
    case "listening":
      return "listening";
    case "wants_to_speak":
      return "wants to speak";
    case "thinking":
      return "thinking";
    case "speaking":
      return "speaking";
  }
}
