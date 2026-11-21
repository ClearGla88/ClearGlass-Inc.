import { ExportReport, SimulationRunner } from "@/components/sim-runner";
import { Chip, Empty, PageHeader, Panel, when } from "@/components/ui";
import { getSnapshot } from "@/lib/snapshot";
import type { Simulation } from "@/lib/types";

function fmt(n: number): string {
  return Math.abs(n) >= 1000 ? Math.round(n).toLocaleString("en-CA") : String(Math.round(n * 100) / 100);
}

function markdown(sim: Simulation): string {
  const obj = sim.recommendation.objective;
  const rows = Object.entries(sim.results).map(([name, m]) => `| ${name} | ${fmt(m[obj]!.p10)} | ${fmt(m[obj]!.p50)} | ${fmt(m[obj]!.p90)} |`);
  return [`# ${sim.title}`, "", `Scenario: ${sim.scenario_type} · seed ${sim.seed} · ${sim.runs} runs per option`, "",
    `| Option | ${obj} p10 | p50 | p90 |`, "|---|---|---|---|", ...rows, "",
    `**Recommendation:** ${sim.recommendation.option}. ${sim.recommendation.rationale}`, "",
    `Conditions: ${sim.recommendation.conditions}`, "", `> ${sim.disclaimer}`, "", "## Assumptions", "",
    "```json", JSON.stringify(sim.assumptions, null, 2), "```", ""].join("\n");
}

function Bars({ sim }: { sim: Simulation }) {
  const obj = sim.recommendation.objective;
  const entries = Object.entries(sim.results);
  const max = Math.max(...entries.map(([, m]) => m[obj]?.p90 ?? 0), 1);
  return (
    <ul className="space-y-3" aria-label={`${obj} by option, p10 to p90 with median marked`}>
      {entries.map(([name, m]) => {
        const q = m[obj]!;
        const best = name === sim.recommendation.option;
        return (
          <li key={name}>
            <div className="flex items-center justify-between text-sm">
              <span className={best ? "text-accent" : ""}>{name}{best && " · recommended"}</span>
              <span className="mono text-xs text-dim">p10 {fmt(q.p10)} · p50 {fmt(q.p50)} · p90 {fmt(q.p90)}</span>
            </div>
            <div className="relative mt-1 h-3 rounded-full bg-white/5">
              <div className="absolute h-full rounded-full" style={{ left: `${(Math.max(q.p10, 0) / max) * 100}%`, width: `${(Math.max(q.p90 - Math.max(q.p10, 0), 0) / max) * 100}%`, background: best ? "color-mix(in srgb, var(--cg-accent) 45%, transparent)" : "rgba(165,180,252,0.3)" }} />
              <div className="absolute top-[-3px] h-[18px] w-0.5 rounded bg-ink" style={{ left: `${(Math.max(q.p50, 0) / max) * 100}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export default async function SimulationsPage() {
  const { snap } = await getSnapshot();
  const agents = Object.fromEntries(snap.agents.map((a) => [a.id, a.name]));
  return (
    <>
      <PageHeader kicker="Sandbox only · seeded · reproducible" title="Simulation Chamber">
        <Chip>{snap.simulations.length} runs on file</Chip>
      </PageHeader>
      <div className="grid gap-5 xl:grid-cols-[26rem_minmax(0,1fr)]">
        <Panel kicker="What-if" title="Launch a scenario" className="h-fit">
          <SimulationRunner scenarios={snap.scenarios} />
          <p className="mt-4 text-xs text-faint">
            Runs through the policy gate as <span className="mono">simulation.run</span> with sandbox=true. The
            simulation package imports nothing that can reach a connector or production system.
          </p>
        </Panel>
        <div className="space-y-5">
          {snap.simulations.length === 0 && <Empty>No simulations yet.</Empty>}
          {snap.simulations.map((sim) => (
            <Panel key={sim.id} kicker={`${sim.scenario_type} · ${agents[sim.created_by] ?? sim.created_by} · ${when(sim.created_at)}`}
              title={sim.title} actions={<ExportReport title={sim.title} body={markdown(sim)} />}>
              <Bars sim={sim} />
              <p className="mt-4 text-sm"><span className="text-accent">Recommend {sim.recommendation.option}.</span> <span className="text-dim">{sim.recommendation.rationale}</span></p>
              <p className="mt-1 text-xs text-dim">{sim.recommendation.conditions}</p>
              <p className="mt-3 rounded-lg border border-warn/30 bg-warn/5 px-3 py-2 text-xs text-warn">{sim.disclaimer}</p>
              <details className="mt-3 text-xs">
                <summary className="cursor-pointer text-faint">Assumptions (seed {sim.seed}, {sim.runs} runs per option)</summary>
                <pre className="mono mt-2 overflow-auto rounded-lg border border-line bg-black/30 p-3 text-dim">{JSON.stringify(sim.assumptions, null, 2)}</pre>
              </details>
            </Panel>
          ))}
        </div>
      </div>
    </>
  );
}
