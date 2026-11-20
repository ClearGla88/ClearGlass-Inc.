"use client";

import { useState } from "react";
import { Button, ErrorLine, post, useAction } from "./actions";

const TEMPLATE = {
  title: "Client onboarding checklist v1",
  objective: "Give every new advisory client the same first-week checklist.",
  department: "revenue",
  owner: "revenue.proposal-writer",
  priority: 3,
  deadline_days: 7,
  deliverables: ["Checklist draft", "Review notes"],
  constraints: ["No client contact inside this mission"],
  approval_rules: ["Sending the checklist to a client is a high-risk external action"],
  goal_ids: ["obj-pipeline"],
  tasks: [
    { key: "draft", title: "Draft the checklist", assignee: "revenue.proposal-writer",
      action: { type: "docs.draft", params: { title: "First-week checklist", items: ["Kickoff call", "Access inventory", "Risk summary"] } } },
    { key: "review", title: "Brand review", assignee: "growth.brand-strategist", depends_on: ["draft"],
      action: { type: "docs.draft", params: { title: "Review notes", ref: { $from: "draft", path: "artifact.title" } } } },
  ],
};

export function MissionCreate() {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(JSON.stringify(TEMPLATE, null, 2));
  const { pending, error, run, setError } = useAction();
  if (!open) return <Button variant="primary" onClick={() => setOpen(true)}>New mission</Button>;
  return (
    <div className="glass w-full p-4">
      <p className="text-sm font-semibold">Create a mission</p>
      <p className="mt-1 text-xs text-dim">
        Tasks form a dependency graph: <span className="mono">depends_on</span> sets order, independent tasks share a
        wave. <span className="mono">{"{\"$from\": key, \"path\": …}"}</span> pulls an upstream output in before the policy check.
      </p>
      <textarea aria-label="Mission specification (JSON)" rows={16} value={text} onChange={(e) => setText(e.target.value)}
        className="mono mt-3 w-full p-3 text-xs" />
      <div className="mt-3 flex gap-2">
        <Button variant="primary" disabled={pending} onClick={() => {
          let spec: unknown;
          try { spec = JSON.parse(text); } catch { setError("not valid JSON"); return; }
          run(() => post("missions", spec), () => setOpen(false));
        }}>{pending ? "Creating…" : "Create"}</Button>
        <Button gated={false} onClick={() => setOpen(false)}>Cancel</Button>
      </div>
      <ErrorLine error={error} />
    </div>
  );
}
