import { type FormEvent, useState } from "react";

interface Props {
  onJoin: (name: string, room: string) => void;
  busy: boolean;
  error: string | null;
}

export function JoinForm({ onJoin, busy, error }: Props) {
  const [name, setName] = useState("");
  const [room, setRoom] = useState("roundtable");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) onJoin(name.trim(), room.trim());
  }

  return (
    <main className="join">
      <section className="join__card" aria-labelledby="join-title">
        <p className="join__kicker">A seat at the table</p>
        <h1 id="join-title">Roundtable</h1>
        <p className="join__lede">
          An attendee that listens to everyone, speaks when it is addressed or when the room goes quiet
          without an answer, and stops the moment you talk over it.
        </p>
        <form onSubmit={submit} className="join__form">
          <label>
            Your name
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} autoFocus required placeholder="Priya" />
          </label>
          <label>
            Room
            <input value={room} onChange={(e) => setRoom(e.target.value)} pattern="[a-z0-9][a-z0-9\-]{0,39}" required />
          </label>
          <button type="submit" disabled={busy || !name.trim()}>
            {busy ? "Pulling up a chair" : "Take a seat"}
          </button>
          {error ? <p role="alert" className="join__error">{error}</p> : null}
        </form>
        <p className="join__fine">Your microphone is used only in this call. The agent hears each person on a separate track.</p>
      </section>
    </main>
  );
}
