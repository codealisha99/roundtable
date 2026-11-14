import { useEffect, useRef } from "react";
import { type Caption } from "../types";

interface Props {
  captions: readonly Caption[];
}

export function Captions({ captions }: Props) {
  const end = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [captions.length]);
  return (
    <section className="panel panel--captions" aria-labelledby="captions-title">
      <h2 id="captions-title">Live captions</h2>
      {captions.length === 0 ? <p className="panel__empty">Captions appear here as people speak.</p> : null}
      <ol className="captions">
        {captions.map((c) => (
          <li key={c.id} className={c.agent ? "caption caption--agent" : "caption"}>
            <span className="caption__speaker">{c.speaker}</span>
            <span className="caption__text">{c.text}</span>
          </li>
        ))}
        <li ref={end} aria-hidden="true" />
      </ol>
    </section>
  );
}
