import { cookies } from "next/headers";
import { DevLogin } from "../components/DevLogin.tsx";
import { Vault } from "../components/Vault.tsx";
import { ProductionNotReadyError } from "../lib/config.ts";
import { getRuntime, type AegisRuntime } from "../lib/runtime.ts";
import { PERSONAS } from "../lib/seed.ts";
import { readSessionCookie, SESSION_COOKIE } from "../lib/session.ts";

export default async function Home() {
  let rt: AegisRuntime;
  try {
    rt = await getRuntime();
  } catch (err) {
    if (!(err instanceof ProductionNotReadyError)) throw err;
    return (
      <main className="signin glass">
        <h1>Not configured</h1>
        <p className="muted">
          Production mode needs Postgres, Redis, a KMS and an identity provider. This release ships the demo only. Set AEGIS_MODE=demo to
          evaluate it.
        </p>
      </main>
    );
  }

  const jar = await cookies();
  const principal = readSessionCookie(rt.config.sessionKey, jar.get(SESSION_COOKIE)?.value, Math.floor(Date.now() / 1000));
  const active = principal && !(await rt.service.isSessionRevoked(principal.sessionId)) ? principal : undefined;

  if (!active) {
    return <DevLogin personas={rt.config.mode === "demo" ? PERSONAS.map(({ key, label, description }) => ({ key, label, description })) : []} />;
  }

  const assets = await rt.service.listVisibleAssets(active);
  return (
    <Vault
      demo={rt.config.mode === "demo"}
      user={{ displayName: active.displayName, roles: active.roles, authLevel: active.authLevel, tenantId: active.tenantId }}
      assets={assets}
    />
  );
}
