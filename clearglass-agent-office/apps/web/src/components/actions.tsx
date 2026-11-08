"use client";

import { useRouter } from "next/navigation";
import { createContext, useContext, useState, useTransition, type ReactNode } from "react";

// Whether this console can act: false on the offline snapshot, when locked, or when signed out.
export const CanAct = createContext<{ can: boolean; why: string }>({ can: false, why: "" });

export function CanActProvider({ can, why, children }: { can: boolean; why: string; children: ReactNode }) {
  return <CanAct.Provider value={{ can, why }}>{children}</CanAct.Provider>;
}

export async function post(path: string, body: unknown = {}): Promise<unknown> {
  const res = await fetch(`/api/office/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : `request failed (${res.status})`);
  }
  return data;
}

export function useAction() {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const run = (fn: () => Promise<unknown>, after?: (r: unknown) => void) =>
    start(async () => {
      setError(null);
      try {
        const r = await fn();
        after?.(r);
        router.refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    });
  return { pending, error, run, setError };
}

const VARIANTS = {
  primary: "border-accent/50 bg-accent/15 text-accent hover:bg-accent/25",
  ghost: "border-line bg-white/[0.03] text-dim hover:text-ink hover:bg-white/[0.07]",
  danger: "border-bad/60 bg-bad/15 text-bad hover:bg-bad/25",
  ok: "border-ok/50 bg-ok/15 text-ok hover:bg-ok/25",
} as const;

export function Button({
  children, onClick, variant = "ghost", disabled, type = "button", title, gated = true,
}: {
  children: ReactNode; onClick?: () => void; variant?: keyof typeof VARIANTS; disabled?: boolean;
  type?: "button" | "submit"; title?: string; gated?: boolean;
}) {
  const { can, why } = useContext(CanAct);
  const blocked = gated && !can;
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || blocked}
      title={blocked ? why : title}
      className={`inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border px-3 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${VARIANTS[variant]}`}
    >
      {children}
    </button>
  );
}

export function ErrorLine({ error }: { error: string | null }) {
  if (!error) return null;
  return <p role="alert" className="mt-2 text-sm text-bad">{error}</p>;
}

export function ActionButton({ path, body, children, variant, confirm }: {
  path: string; body?: unknown; children: ReactNode; variant?: keyof typeof VARIANTS; confirm?: string;
}) {
  const { pending, error, run } = useAction();
  return (
    <span className="inline-flex flex-col">
      <Button
        variant={variant}
        disabled={pending}
        onClick={() => {
          if (confirm && !window.confirm(confirm)) return;
          run(() => post(path, body ?? {}));
        }}
      >
        {pending ? "Working…" : children}
      </Button>
      <ErrorLine error={error} />
    </span>
  );
}
