"use client";

// One small form for every Revenue Floor action. Each submits through the server-side proxy, which checks the
// path against its allow-list, the origin, and the operator session before anything reaches the API.
import { useState } from "react";
import { Button, ErrorLine, post, useAction } from "./actions";

export interface FieldSpec {
  name: string;
  label: string;
  kind?: "text" | "textarea" | "number" | "select" | "checkbox" | "json" | "list" | "datetime";
  options?: string[];
  placeholder?: string;
  required?: boolean;
  hint?: string;
  initial?: string | number | boolean;
  group?: string; // nest the value under this key in the request body
}

type Values = Record<string, string | boolean>;

function initialValues(fields: FieldSpec[]): Values {
  return Object.fromEntries(
    fields.map((f) => [f.name, f.kind === "checkbox" ? Boolean(f.initial) : f.initial === undefined ? "" : String(f.initial)]),
  );
}

function buildBody(fields: FieldSpec[], values: Values, fixed: Record<string, unknown>): Record<string, unknown> {
  const body: Record<string, unknown> = { ...fixed };
  for (const f of fields) {
    const raw = values[f.name];
    let value: unknown;
    if (f.kind === "checkbox") value = Boolean(raw);
    else {
      const text = String(raw ?? "").trim();
      if (!text) {
        if (f.required) throw new Error(`${f.label} is required`);
        continue;
      }
      if (f.kind === "number") {
        const n = Number(text);
        if (!Number.isInteger(n)) throw new Error(`${f.label} must be a whole number`);
        value = n;
      } else if (f.kind === "json") {
        try { value = JSON.parse(text); } catch { throw new Error(`${f.label} is not valid JSON`); }
      } else if (f.kind === "list") {
        value = text.split("\n").map((s) => s.trim()).filter(Boolean);
      } else value = text;
    }
    if (f.group) {
      const group = (body[f.group] as Record<string, unknown> | undefined) ?? {};
      group[f.name] = value;
      body[f.group] = group;
    } else body[f.name] = value;
  }
  return body;
}

export function RevenueForm({ path, title, fields, fixed = {}, submit = "Submit", variant = "primary", note }: {
  path: string; title: string; fields: FieldSpec[]; fixed?: Record<string, unknown>; submit?: string;
  variant?: "primary" | "ok" | "danger" | "ghost"; note?: string;
}) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Values>(() => initialValues(fields));
  const { pending, error, run, setError } = useAction();
  if (!open) return <Button variant={variant} onClick={() => setOpen(true)}>{title}</Button>;
  const set = (name: string, value: string | boolean) => setValues((v) => ({ ...v, [name]: value }));
  return (
    <form
      className="glass w-full space-y-3 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        let body: Record<string, unknown>;
        try { body = buildBody(fields, values, fixed); } catch (err) { setError(err instanceof Error ? err.message : String(err)); return; }
        run(() => post(path, body), () => { setOpen(false); setValues(initialValues(fields)); });
      }}
    >
      <p className="text-sm font-semibold">{title}</p>
      {note && <p className="text-xs text-dim">{note}</p>}
      {fields.map((f) => {
        const id = `${path}-${f.name}`.replace(/[^A-Za-z0-9_-]/g, "-");
        const common = "mt-1 w-full p-2 text-sm";
        return (
          <div key={f.name}>
            {f.kind === "checkbox" ? (
              <label htmlFor={id} className="flex items-center gap-2 text-sm">
                <input id={id} type="checkbox" checked={Boolean(values[f.name])} onChange={(e) => set(f.name, e.target.checked)} />
                {f.label}
              </label>
            ) : (
              <>
                <label htmlFor={id} className="label">{f.label}{f.required ? " (required)" : ""}</label>
                {f.kind === "select" ? (
                  <select id={id} value={String(values[f.name])} onChange={(e) => set(f.name, e.target.value)} className={common}>
                    <option value="">Choose…</option>
                    {(f.options ?? []).map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
                  </select>
                ) : f.kind === "textarea" || f.kind === "json" || f.kind === "list" ? (
                  <textarea id={id} rows={f.kind === "json" ? 7 : 3} value={String(values[f.name])} placeholder={f.placeholder}
                    onChange={(e) => set(f.name, e.target.value)} className={`${common} ${f.kind === "json" ? "mono text-xs" : ""}`} />
                ) : (
                  <div className="flex gap-2">
                    <input id={id} type={f.kind === "number" ? "number" : "text"} value={String(values[f.name])}
                      placeholder={f.placeholder} onChange={(e) => set(f.name, e.target.value)} className={common} />
                    {f.kind === "datetime" && (
                      <Button gated={false} onClick={() => set(f.name, new Date().toISOString().slice(0, 19) + "Z")}>Now</Button>
                    )}
                  </div>
                )}
              </>
            )}
            {f.hint && <p className="mt-0.5 text-[0.7rem] text-faint">{f.hint}</p>}
          </div>
        );
      })}
      <div className="flex gap-2">
        <Button type="submit" variant={variant} disabled={pending}>{pending ? "Working…" : submit}</Button>
        <Button gated={false} onClick={() => setOpen(false)}>Cancel</Button>
      </div>
      <ErrorLine error={error} />
    </form>
  );
}
