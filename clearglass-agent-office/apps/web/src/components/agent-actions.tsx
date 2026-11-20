"use client";

import { useState } from "react";
import { Button, ErrorLine, post, useAction } from "./actions";

export function AgentActions({ id, status, objective, department }: {
  id: string; status: string; objective: string; department: string;
}) {
  const { pending, error, run } = useAction();
  const act = (action: string, body: unknown) => run(() => post(`agents/${id}/${action}`, body));
  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {status === "paused" ? (
          <Button disabled={pending} onClick={() => act("resume", { reason: "resumed from the directory" })}>Resume</Button>
        ) : status !== "retired" ? (
          <Button disabled={pending} onClick={() => act("pause", { reason: "paused from the directory" })}>Pause</Button>
        ) : null}
        {status !== "retired" && (
          <Button disabled={pending} onClick={() => {
            const next = window.prompt("New objective", objective);
            if (next && next !== objective) run(() => fetch(`/api/office/agents/${id}`, {
              method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ objective: next }),
            }).then(async (r) => { if (!r.ok) throw new Error(((await r.json()) as { detail?: string }).detail ?? "edit failed"); }));
          }}>Edit</Button>
        )}
        <Button disabled={pending} onClick={() => {
          const newId = window.prompt("Clone as agent id (e.g. eng.backend-2)", `${id}-2`);
          const callsign = newId && window.prompt("Callsign (e.g. CG-EN-07)", "");
          if (newId && callsign) act("clone", { new_id: newId, callsign });
        }}>Clone</Button>
        {status !== "retired" && (
          <Button variant="danger" disabled={pending} onClick={() => {
            const reason = window.prompt(`Retire ${id}? Its history is kept. Reason:`);
            if (reason) act("retire", { reason });
          }}>Retire</Button>
        )}
      </div>
      <ErrorLine error={error} />
      <span className="sr-only">{department}</span>
    </div>
  );
}

const TEMPLATE = {
  id: "growth.newsletter",
  callsign: "CG-GM-07",
  name: "Newsletter Agent",
  department: "growth",
  reports_to: "growth.brand-strategist",
  objective: "Draft the monthly client newsletter from approved posts.",
  success_criteria: ["Every issue reuses only approved content"],
  permissions: { content: "propose" },
  tools: ["content.studio"],
};

export function HireAgent() {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(JSON.stringify(TEMPLATE, null, 2));
  const { pending, error, run, setError } = useAction();
  if (!open) return <Button variant="primary" onClick={() => setOpen(true)}>Hire agent</Button>;
  return (
    <div className="glass w-full p-4">
      <p className="text-sm font-semibold">Hire an agent</p>
      <p className="mt-1 text-xs text-dim">
        Base grants (memory, messaging) are added automatically. The org validator rejects unknown tools, unknown
        domains, broken reporting lines, and the human-only <span className="mono">approve</span> level.
      </p>
      <textarea aria-label="Agent specification (JSON)" rows={12} value={text} onChange={(e) => setText(e.target.value)}
        className="mono mt-3 w-full p-3 text-xs" />
      <div className="mt-3 flex gap-2">
        <Button variant="primary" disabled={pending} onClick={() => {
          let spec: unknown;
          try { spec = JSON.parse(text); } catch { setError("not valid JSON"); return; }
          run(() => post("agents", spec), () => setOpen(false));
        }}>{pending ? "Hiring…" : "Hire"}</Button>
        <Button gated={false} onClick={() => setOpen(false)}>Cancel</Button>
      </div>
      <ErrorLine error={error} />
    </div>
  );
}
