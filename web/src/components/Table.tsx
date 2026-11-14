import { type Participant } from "livekit-client";
import { type AgentStatus } from "../types";
import { isAgent } from "../lib/useRoom";
import { labelText, speakerColor } from "../lib/present";

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
        <span className="orb__state">{agentPresent ? labelText(agent.label) : "not in the room yet"}</span>
      </div>
      {humans.map((p, index) => {
        const speaking = speakers.has(p.identity) || p.isSpeaking;
        const muted = !p.isMicrophoneEnabled;
        const name = p.name || p.identity;
        const isSelf = p.identity === self;
        return (
          <div
            key={p.identity}
            className={`seat ${speaking ? "seat--speaking" : ""} ${isSelf ? "seat--self" : ""}`}
            style={seatPosition(index, humans.length)}
          >
            <div className="seat__avatar" style={{ background: speakerColor(name) }} aria-hidden="true">
              {initials(name)}
              {speaking ? <span className="seat__bars"><i /><i /><i /></span> : null}
            </div>
            <div className="seat__name">
              {name}
              {isSelf ? <span className="seat__you"> (you)</span> : null}
            </div>
            <div className="seat__status">
              {speaking ? <span className="seat__speaking">speaking</span> : null}
              {muted ? <span className="seat__muted">mic off</span> : null}
            </div>
          </div>
        );
      })}
    </section>
  );
}
