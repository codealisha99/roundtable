import { useCallback, useEffect, useRef, useState } from "react";
import {
  type Participant,
  type RemoteParticipant,
  type RemoteTrack,
  type RemoteTrackPublication,
  Room,
  RoomEvent,
  Track,
} from "livekit-client";
import { AGENT_IDENTITY_PREFIX, type AgentMessage, type AgentStatus, type Caption } from "../types";

const TOPIC = "roundtable";
const MAX_CAPTIONS = 40;
const MAX_HISTORY = 10;

export interface RoomState {
  status: "connecting" | "connected" | "failed" | "closed";
  error: string | null;
  participants: Participant[];
  speakers: ReadonlySet<string>;
  captions: readonly Caption[];
  agent: AgentStatus;
  micOn: boolean;
  leave: () => void;
  toggleMic: () => void;
}

const INITIAL_AGENT: AgentStatus = { label: "listening", reason: "Waiting for the call to start", history: [] };

export function isAgent(participant: Participant): boolean {
  return participant.identity.startsWith(AGENT_IDENTITY_PREFIX);
}

function parseMessage(payload: Uint8Array): AgentMessage | null {
  try {
    return JSON.parse(new TextDecoder().decode(payload)) as AgentMessage;
  } catch {
    return null;
  }
}

/** Owns the LiveKit connection: participants, active speakers, captions, agent state and remote audio. */
export function useRoom(url: string, token: string): RoomState {
  const roomRef = useRef<Room | null>(null);
  const audioEls = useRef<Map<string, HTMLMediaElement>>(new Map());
  const captionId = useRef(0);
  const [status, setStatus] = useState<RoomState["status"]>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [speakers, setSpeakers] = useState<ReadonlySet<string>>(new Set());
  const [captions, setCaptions] = useState<readonly Caption[]>([]);
  const [agent, setAgent] = useState<AgentStatus>(INITIAL_AGENT);
  const [micOn, setMicOn] = useState(false);

  useEffect(() => {
    const room = new Room({ adaptiveStream: true, dynacast: true });
    roomRef.current = room;
    const refresh = () => {
      setParticipants([room.localParticipant, ...room.remoteParticipants.values()]);
    };
    const onTrack = (track: RemoteTrack, _pub: RemoteTrackPublication, _p: RemoteParticipant) => {
      if (track.kind !== Track.Kind.Audio) return;
      const el = track.attach();
      el.dataset.track = track.sid ?? "";
      document.body.appendChild(el);
      audioEls.current.set(track.sid ?? "", el);
    };
    const onUntrack = (track: RemoteTrack) => {
      track.detach().forEach((el) => el.remove());
      audioEls.current.delete(track.sid ?? "");
    };
    const onData = (payload: Uint8Array, _p?: RemoteParticipant, _k?: unknown, topic?: string) => {
      if (topic !== TOPIC) return;
      const message = parseMessage(payload);
      if (!message) return;
      if (message.kind === "state") {
        setAgent((prev) => ({
          label: message.label,
          reason: message.reason,
          history: [message.reason, ...prev.history].slice(0, MAX_HISTORY),
        }));
      } else if (message.kind === "caption") {
        captionId.current += 1;
        setCaptions((prev) => [...prev, { id: captionId.current, speaker: message.speaker, text: message.text, agent: false }].slice(-MAX_CAPTIONS));
      } else {
        captionId.current += 1;
        setCaptions((prev) => [...prev, { id: captionId.current, speaker: "Roundtable", text: message.text, agent: true }].slice(-MAX_CAPTIONS));
      }
    };
    const onSpeakers = (list: Participant[]) => setSpeakers(new Set(list.map((p) => p.identity)));
    const onDisconnected = () => setStatus("closed");

    room
      .on(RoomEvent.ParticipantConnected, refresh)
      .on(RoomEvent.ParticipantDisconnected, refresh)
      .on(RoomEvent.TrackSubscribed, onTrack)
      .on(RoomEvent.TrackUnsubscribed, onUntrack)
      .on(RoomEvent.DataReceived, onData)
      .on(RoomEvent.ActiveSpeakersChanged, onSpeakers)
      .on(RoomEvent.LocalTrackPublished, refresh)
      .on(RoomEvent.Disconnected, onDisconnected);

    let cancelled = false;
    room
      .connect(url, token)
      .then(async () => {
        if (cancelled) return;
        setStatus("connected");
        await room.localParticipant.setMicrophoneEnabled(true);
        setMicOn(room.localParticipant.isMicrophoneEnabled);
        refresh();
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Could not connect");
        setStatus("failed");
      });

    const audio = audioEls.current;
    return () => {
      cancelled = true;
      room.removeAllListeners();
      void room.disconnect();
      roomRef.current = null;
      audio.forEach((el) => el.remove());
      audio.clear();
    };
  }, [url, token]);

  const toggleMic = useCallback(() => {
    const room = roomRef.current;
    if (!room) return;
    const next = !room.localParticipant.isMicrophoneEnabled;
    void room.localParticipant.setMicrophoneEnabled(next).then(() => setMicOn(next));
  }, []);

  const leave = useCallback(() => {
    void roomRef.current?.disconnect();
    setStatus("closed");
  }, []);

  return { status, error, participants, speakers, captions, agent, micOn, leave, toggleMic };
}
