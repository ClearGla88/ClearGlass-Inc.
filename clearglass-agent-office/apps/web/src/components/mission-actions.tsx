"use client";

import { Button, ErrorLine, post, useAction } from "./actions";

export function MissionLifecycle({ id, status }: { id: string; status: string }) {
  const { pending, error, run } = useAction();
  const act = (action: "pause" | "resume" | "cancel") => {
    const reason = window.prompt(`Reason to ${action} this mission (12+ characters, recorded permanently)`);
    if (reason) run(() => post(`missions/${id}/${action}`, { reason }));
  };
  if (status !== "active" && status !== "paused") return null;
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {status === "active" && <Button disabled={pending} onClick={() => act("pause")}>Pause</Button>}
      {status === "paused" && <Button disabled={pending} onClick={() => act("resume")}>Resume</Button>}
      <Button variant="danger" disabled={pending} onClick={() => act("cancel")}>Cancel</Button>
      <ErrorLine error={error} />
    </span>
  );
}
