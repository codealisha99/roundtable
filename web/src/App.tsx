import { useState } from "react";
import { JoinForm } from "./components/JoinForm";
import { MeetingRoom } from "./components/MeetingRoom";
import { type JoinTicket, requestTicket } from "./lib/api";

export function App() {
  const [ticket, setTicket] = useState<JoinTicket | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function join(name: string, room: string) {
    setBusy(true);
    setError(null);
    try {
      setTicket(await requestTicket(name, room));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not join");
    } finally {
      setBusy(false);
    }
  }

  if (!ticket) return <JoinForm onJoin={join} busy={busy} error={error} />;
  return <MeetingRoom ticket={ticket} onLeave={() => setTicket(null)} />;
}
