"use client";

import { CSSProperties } from "react";

function Bar({ w, h = 12, style }: { w: number | string; h?: number; style?: CSSProperties }) {
  return <span className="cw-skel" style={{ width: w, height: h, ...style }} />;
}

// Mirrors the data-page layout so the loading state has the same shape as the
// content that replaces it (no jarring reflow): header + figures strip + one
// table surface.
export function DataPageSkeleton() {
  return (
    <div className="dp" aria-hidden>
      <div className="dp-head">
        <Bar w={150} h={22} />
        <div className="dp-spacer" />
        <Bar w={248} h={40} style={{ borderRadius: 9 }} />
        <Bar w={118} h={38} style={{ borderRadius: 8 }} />
      </div>
      <div className="dp-stats">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="dp-figure">
            <Bar w={i === 0 ? 72 : 54} h={11} />
            <Bar w={i === 0 ? 40 : 30} h={19} />
          </div>
        ))}
        <Bar w={214} h={12} style={{ marginInlineStart: "auto", alignSelf: "flex-end" }} />
      </div>
      <div className="dp-panel">
        <div className="dp-toolbar">
          <Bar w={210} h={30} style={{ borderRadius: 8 }} />
          <Bar w={230} h={22} style={{ marginInlineStart: "auto" }} />
        </div>
        <div className="dp-table-scroll">
          {Array.from({ length: 16 }).map((_, i) => (
            <div key={i} className="dp-skel-row">
              <Bar w={22} />
              <Bar w={112 + ((i * 17) % 54)} />
              <Bar w={72} />
              <Bar w={26} />
              <Bar w={46} />
              <Bar w={16} h={16} style={{ borderRadius: 4 }} />
              <Bar w={16} h={16} style={{ borderRadius: 4, marginInlineStart: "auto" }} />
              <Bar w={16} h={16} style={{ borderRadius: 4 }} />
              <Bar w={150} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Wall-shaped loading state for the assignment screen.
export function WallSkeleton() {
  return (
    <div className="cw-wall-scroll" aria-hidden>
      <div className="cw-wall">
        {Array.from({ length: 6 }).map((_, c) => (
          <div key={c} className="cw-col">
            <div className="cw-col-head">
              <div className="cw-col-title">
                <Bar w={54} h={14} />
                <Bar w={22} h={20} />
              </div>
              <Bar w={"100%"} h={10} style={{ marginTop: 12 }} />
            </div>
            <div className="cw-col-body">
              {Array.from({ length: 11 }).map((_, i) => (
                <Bar key={i} w={"100%"} h={30} style={{ borderRadius: 5 }} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
