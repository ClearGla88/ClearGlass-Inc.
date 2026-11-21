import { cookies } from "next/headers";
import { getRuntime } from "@/lib/runtime";
import { cookieNameFor, unsealSessionId } from "@/lib/session";
import { PERSONAS } from "@/lib/demo";
import { SignIn } from "@/components/SignIn";
import { Workspace } from "@/components/Workspace";

export const dynamic = "force-dynamic";

export default async function Home() {
  const rt = await getRuntime();
  const jar = await cookies();
  const sessionId = unsealSessionId(rt.config.keys.session, jar.get(cookieNameFor(rt.config.appOrigin))?.value);
  const catalogue = sessionId ? await rt.service.listCatalogue(sessionId) : null;

  return (
    <main className="shell">
      <header className="masthead">
        <p className="eyebrow">ClearGlass · Aegis Glass</p>
        <h1>Protected viewing</h1>
        <p className="lede">
          Every view is authorised, single-use, watermarked to the viewer, and recorded. A screen can always be photographed;
          what this layer guarantees is that a leaked copy carries a trace back to the view it came from.
        </p>
      </header>
      {catalogue && catalogue.ok ? (
        <Workspace
          user={{ displayName: catalogue.user.displayName, roles: catalogue.user.roles, authLevel: catalogue.session.authLevel }}
          assets={catalogue.assets}
          devTools={rt.config.devLogin && rt.config.env !== "production"}
        />
      ) : (
        <SignIn
          devLogin={rt.config.devLogin && rt.config.env !== "production"}
          paused={catalogue !== null && !catalogue.ok && catalogue.reasons.includes("session_paused")}
          personas={PERSONAS.map((p) => ({ key: p.key, displayName: p.displayName, description: p.description }))}
        />
      )}
    </main>
  );
}
