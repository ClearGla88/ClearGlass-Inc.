"use client";

import { useState } from "react";
import type { Scenario } from "@/lib/types";
import { Button, ErrorLine, post, useAction } from "./actions";

const RUNNERS: Record<string, string> = {
  pricing: "revenue.pricing-analyst",
  campaign: "growth.campaign-analyst",
  incident: "sim.red-team",
  rollout: "sim.scenario-designer",
};

export function SimulationRunner({ scenarios }: { scenarios: Record<string, Scenario> }) {
  const names = Object.keys(scenarios);
  const [kind, setKind] = useState(names[0] ?? "pricing");
  const [text, setText] = useState(JSON.stringify(scenarios[names[0] ?? "pricing"]?.example ?? {}, null, 2));
  const [seed, setSeed] = useState(7);
  const { pending, error, run, setError } = useAction();
  const pick = (k: string) => { setKind(k); setText(JSON.stringify(scenarios[k]?.example ?? {}, null, 2)); };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Scenario type">
        {names.map((k) => (
          <button key={k} role="radio" aria-checked={k === kind} onClick={() => pick(k)}
            className={`rounded-full border px-3 py-1 text-xs ${k === kind ? "border-accent/50 text-accent" : "border-line text-dim"}`}>{k}</button>
        ))}
      </div>
      <p className="text-xs text-dim">{scenarios[kind]?.description} Objective: {scenarios[kind]?.direction} {scenarios[kind]?.objective}.</p>
      <label htmlFor="sim-json" className="label">Assumptions and options (ranges as low / mode / high)</label>
      <textarea id="sim-json" rows={12} value={text} onChange={(e) => setText(e.target.value)} className="mono w-full p-3 text-xs" />
      <div className="flex flex-wrap items-center gap-3">
        <label className="label" htmlFor="seed">Seed</label>
        <input id="seed" type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} className="w-24 px-2 py-1 text-sm" />
        <Button variant="primary" disabled={pending} onClick={() => {
          let spec: { assumptions?: unknown; options?: unknown };
          try { spec = JSON.parse(text); } catch { setError("not valid JSON"); return; }
          run(() => post("simulations", { agent_id: RUNNERS[kind] ?? "sim.scenario-designer", scenario_type: kind,
            title: `${kind} what-if`, assumptions: spec.assumptions, options: spec.options, seed, runs: 2000 }));
        }}>{pending ? "Running in sandbox…" : "Run simulation"}</Button>
      </div>
      <ErrorLine error={error} />
    </div>
  );
}

export function ExportReport({ title, body }: { title: string; body: string }) {
  return (
    <Button gated={false} onClick={() => {
      const url = URL.createObjectURL(new Blob([body], { type: "text/markdown" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.md`;
      a.click();
      URL.revokeObjectURL(url);
    }}>Export report</Button>
  );
}
