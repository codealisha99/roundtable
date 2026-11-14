export interface JoinTicket {
  token: string;
  url: string;
  room: string;
  identity: string;
  agent: string;
}

export async function requestTicket(name: string, room: string): Promise<JoinTicket> {
  const response = await fetch("/api/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, room }),
  });
  const body: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof body === "object" && body !== null && "error" in body ? String(body.error) : "Could not join";
    throw new Error(message);
  }
  return body as JoinTicket;
}
