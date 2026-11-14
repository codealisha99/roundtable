import { useEffect, useRef } from "react";
import { type Caption } from "../types";
import { clock, speakerColor } from "../lib/present";

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
      {captions.length === 0 ? (
        <p className="panel__empty">
          Nothing said yet. A sentence appears here once someone finishes it. Try “Roundtable, what is the status?”
        </p>
      ) : null}
      <ol className="captions">
        {captions.map((c) => (
          <li key={c.id} className={c.agent ? "caption caption--agent" : "caption"}>
            <span className="caption__meta">
              <span className="caption__speaker" style={c.agent ? undefined : { color: speakerColor(c.speaker) }}>
                {c.speaker}
              </span>
              <time className="caption__at">{clock(c.at)}</time>
            </span>
            <span className="caption__text">{c.text}</span>
          </li>
        ))}
        <li ref={end} aria-hidden="true" />
      </ol>
    </section>
  );
}
