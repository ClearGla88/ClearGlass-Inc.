"use client";

import { Button, ErrorLine, post, useAction } from "./actions";

export function MemoryDecision({ id }: { id: string }) {
  const { pending, error, run } = useAction();
  const decide = (approve: boolean) => {
    const reason = window.prompt(approve ? "Why is this safe to rely on? (12+ characters)" : "Why reject it? (12+ characters)");
    if (reason) run(() => post(`memory/${id}/decision`, { approve, reason }));
  };
  return (
    <div className="flex flex-wrap gap-2">
      <Button variant="ok" disabled={pending} onClick={() => decide(true)}>Approve</Button>
      <Button variant="danger" disabled={pending} onClick={() => decide(false)}>Reject</Button>
      <ErrorLine error={error} />
    </div>
  );
}
