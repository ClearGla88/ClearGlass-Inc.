"use client";

import { useState } from "react";
import { Button, ErrorLine, post, useAction } from "./actions";

export function EmergencyControl({ halted, reason }: { halted: boolean; reason?: string }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const { pending, error, run } = useAction();
  const path = halted ? "emergency-stop/release" : "emergency-stop";
  return (
    <div className="relative">
      <Button variant={halted ? "ok" : "danger"} onClick={() => setOpen((v) => !v)}>
        <span aria-hidden="true">{halted ? "▶" : "■"}</span>
        {halted ? "Release stop" : "Emergency stop"}
      </Button>
      {open && (
        <div role="dialog" aria-label={halted ? "Release the emergency stop" : "Engage the emergency stop"}
          className="glass absolute right-0 z-40 mt-2 w-[min(22rem,calc(100vw-2rem))] p-4">
          <p className="text-sm font-semibold">{halted ? "Release the emergency stop" : "Stop the whole office"}</p>
          <p className="mt-1 text-xs text-dim">
            {halted
              ? `Engaged: ${reason ?? ""}. Agents return to idle. Cancelled approvals stay cancelled.`
              : "Pauses every agent, cancels every open approval, keeps all state, opens an incident record, and notifies you."}
          </p>
          <label className="label mt-3 block" htmlFor="stop-reason">Reason (required, 12+ characters)</label>
          <textarea id="stop-reason" rows={2} value={text} onChange={(e) => setText(e.target.value)}
            className="mt-1 w-full p-2 text-sm" />
          <div className="mt-3 flex justify-end gap-2">
            <Button gated={false} onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant={halted ? "ok" : "danger"} disabled={pending || text.trim().length < 12}
              onClick={() => run(() => post(path, { reason: text.trim() }), () => { setOpen(false); setText(""); })}>
              {pending ? "Working…" : halted ? "Release" : "Engage stop"}
            </Button>
          </div>
          <ErrorLine error={error} />
        </div>
      )}
    </div>
  );
}
