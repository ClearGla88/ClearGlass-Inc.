"use client";

import { useState } from "react";
import { Button, ErrorLine, post, useAction } from "./actions";

export function ApprovalActions({ id, params }: { id: string; params: Record<string, unknown> }) {
  const [reason, setReason] = useState("");
  const [modifying, setModifying] = useState(false);
  const [edit, setEdit] = useState(JSON.stringify(params, null, 2));
  const { pending, error, run, setError } = useAction();
  const ok = reason.trim().length >= 12;
  const decide = (decision: "approve" | "reject" | "modify") => {
    let modifications: Record<string, unknown> | undefined;
    if (decision === "modify") {
      try {
        const next = JSON.parse(edit) as Record<string, unknown>;
        modifications = Object.fromEntries(Object.entries(next).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(params[k])));
      } catch { setError("edited parameters are not valid JSON"); return; }
      if (!Object.keys(modifications).length) { setError("change at least one parameter, or approve as is"); return; }
    }
    run(() => post(`approvals/${id}/decision`, { decision, reason: reason.trim(), modifications }));
  };
  return (
    <div className="space-y-3">
      <div>
        <label htmlFor={`reason-${id}`} className="label">Your reason (required, 12+ characters, recorded permanently)</label>
        <textarea id={`reason-${id}`} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} className="mt-1 w-full p-2 text-sm" />
      </div>
      {modifying && (
        <div>
          <label htmlFor={`edit-${id}`} className="label">Edit parameters (existing keys only; the edited action is re-checked by policy)</label>
          <textarea id={`edit-${id}`} rows={8} value={edit} onChange={(e) => setEdit(e.target.value)} className="mono mt-1 w-full p-2 text-xs" />
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant="ok" disabled={pending || !ok} onClick={() => decide("approve")}>Approve</Button>
        {modifying
          ? <Button variant="primary" disabled={pending || !ok} onClick={() => decide("modify")}>Approve with edits</Button>
          : <Button disabled={pending} onClick={() => setModifying(true)}>Modify…</Button>}
        <Button variant="danger" disabled={pending || !ok} onClick={() => decide("reject")}>Reject</Button>
      </div>
      <ErrorLine error={error} />
    </div>
  );
}
