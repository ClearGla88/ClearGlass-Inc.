"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { apiPost } from "../lib/client-api.ts";
import { InvestigatorPanel } from "./InvestigatorPanel.tsx";
import { SecureAssetViewer, type CapabilityGrant } from "./SecureAssetViewer.tsx";

export interface VaultAsset {
  id: string;
  title: string;
  classification: string;
  needsStepUp: boolean;
}

export interface VaultUser {
  displayName: string;
  roles: string[];
  authLevel: string;
  tenantId: string;
}

const AUTH_LABEL: Record<string, string> = {
  password: "Password",
  mfa: "MFA",
  phishing_resistant: "Passkey",
};

export function Vault({ user, assets, demo }: { user: VaultUser; assets: VaultAsset[]; demo: boolean }) {
  const router = useRouter();
  const [selected, setSelected] = useState<string | undefined>(assets[0]?.id);
  const [authVersion, setAuthVersion] = useState(0);
  const [risk, setRisk] = useState<CapabilityGrant["riskState"]>("LOW");
  const [busy, setBusy] = useState(false);

  const stepUp = useCallback(async () => {
    setBusy(true);
    const r = await apiPost("/api/dev/step-up");
    setBusy(false);
    if (r.ok) {
      setAuthVersion((v) => v + 1);
      router.refresh();
    }
  }, [router]);

  const signOut = useCallback(async () => {
    setBusy(true);
    await apiPost("/api/sessions/revoke", {});
    router.refresh();
  }, [router]);

  const canInvestigate = user.roles.includes("investigator");
  const isAdmin = user.roles.includes("tenant_admin");

  return (
    <div className="vault" data-risk={risk}>
      <header className="topbar glass">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span>Aegis Glass</span>
        </div>
        <div className="identity">
          <span>{user.displayName}</span>
          <span className="chip">{AUTH_LABEL[user.authLevel] ?? user.authLevel}</span>
          <span className="chip" data-risk={risk}>
            Risk {risk}
          </span>
          {demo && user.authLevel !== "phishing_resistant" && (
            <button type="button" className="btn" onClick={stepUp} disabled={busy}>
              Verify with passkey
            </button>
          )}
          <button type="button" className="btn" onClick={signOut} disabled={busy}>
            Sign out
          </button>
        </div>
      </header>

      <main className="layout">
        <nav className="asset-list glass" aria-label="Protected items">
          <h2 className="panel-title">Items shared with you</h2>
          {assets.length === 0 ? (
            <p className="muted">Nothing is shared with you in this workspace.</p>
          ) : (
            <ul>
              {assets.map((a) => (
                <li key={a.id}>
                  <button
                    type="button"
                    className="asset-button"
                    aria-current={selected === a.id ? "true" : undefined}
                    onClick={() => setSelected(a.id)}
                  >
                    <span className="badge" data-class={a.classification}>
                      {a.classification}
                    </span>
                    <span className="asset-title">{a.title}</span>
                    {a.needsStepUp && <span className="asset-hint">Needs passkey</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>

        <section className="stage glass" aria-label="Preview">
          {selected ? (
            <SecureAssetViewer key={`${selected}:${authVersion}`} assetId={selected} onStepUp={demo ? stepUp : undefined} onRiskChange={setRisk} />
          ) : (
            <p className="muted">Select an item to preview it.</p>
          )}
        </section>

        {(canInvestigate || isAdmin) && <InvestigatorPanel canResolveTraces={canInvestigate && user.authLevel === "phishing_resistant"} canRevoke={isAdmin} />}
      </main>
    </div>
  );
}
