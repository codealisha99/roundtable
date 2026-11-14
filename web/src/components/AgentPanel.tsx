import { type AgentStatus } from "../types";
import { labelText } from "./Table";

interface Props {
  agent: AgentStatus;
  agentPresent: boolean;
}

export function AgentPanel({ agent, agentPresent }: Props) {
  return (
    <section className="panel" aria-labelledby="agent-title">
      <h2 id="agent-title">Agent</h2>
      <p className={`chip chip--${agent.label}`}>{agentPresent ? labelText(agent.label) : "not in the room yet"}</p>
      <p className="panel__reason">{agent.reason}</p>
      {agent.history.length > 1 ? (
        <details>
          <summary>Recent decisions</summary>
          <ol className="panel__history">
            {agent.history.slice(1).map((entry, i) => (
              <li key={`${i}-${entry}`}>{entry}</li>
            ))}
          </ol>
        </details>
      ) : null}
    </section>
  );
}
