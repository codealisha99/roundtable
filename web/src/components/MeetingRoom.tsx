import { type JoinTicket } from "../lib/api";
import { isAgent, useRoom } from "../lib/useRoom";
import { AgentPanel } from "./AgentPanel";
import { Captions } from "./Captions";
import { Table } from "./Table";

interface Props {
  ticket: JoinTicket;
  onLeave: () => void;
}

export function MeetingRoom({ ticket, onLeave }: Props) {
  const room = useRoom(ticket.url, ticket.token);

  if (room.status === "failed") {
    return (
      <main className="room room--centered">
        <p role="alert">Could not join the room: {room.error}</p>
        <button onClick={onLeave}>Back</button>
      </main>
    );
  }
  const agentPresent = room.participants.some(isAgent);
  return (
    <main className="room">
      <header className="room__bar">
        <div>
          <h1>Roundtable</h1>
          <p>Room <code>{ticket.room}</code> · {room.status === "connected" ? "live" : room.status}</p>
        </div>
        <div className="room__controls">
          <button className={room.micOn ? "" : "is-off"} onClick={room.toggleMic} aria-pressed={room.micOn}>
            {room.micOn ? "Mute" : "Unmute"}
          </button>
          <button className="ghost" onClick={() => { room.leave(); onLeave(); }}>Leave</button>
        </div>
      </header>
      <div className="room__body">
        <Table participants={room.participants} speakers={room.speakers} agent={room.agent} agentPresent={agentPresent} self={ticket.identity} />
        <aside className="room__side">
          <AgentPanel agent={room.agent} agentPresent={agentPresent} />
          <Captions captions={room.captions} />
        </aside>
      </div>
    </main>
  );
}
