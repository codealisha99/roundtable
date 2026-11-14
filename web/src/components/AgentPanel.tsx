import { type AgentStatus } from "../types";
import { clock, labelText, verbFor } from "../lib/present";

interface Props {
  agent: AgentStatus;
  agentPresent: boolean;
}

export function AgentPanel({ agent, agentPresent }: Props) {
  return (
    <section className="panel panel--agent" aria-labelledby="agent-title">
      <h2 id="agent-title">Agent</h2>
      <p className={`chip chip--${agent.label}`}>{agentPresent ? labelText(agent.label) : "not in the room yet"}</p>
      <p className="panel__reason">{agent.reason}</p>
      <h3 className="panel__log-title">Why it spoke, and why it stayed quiet</h3>
      {agent.decisions.length === 0 ? (
        <p className="panel__empty">Each decision appears here with its reason as the agent listens.</p>
      ) : (
        <ol className="log">
          {agent.decisions.map((d, i) => {
            const verb = verbFor(d);
            return (
              <li key={d.id} className={`log__row ${i === 0 ? "log__row--now" : ""}`}>
                <time className="log__at">{clock(d.at)}</time>
                <span className={`log__verb log__verb--${verb.replace(/\s+/g, "-")}`}>{verb}</span>
                <span className="log__reason">{d.reason}</span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
