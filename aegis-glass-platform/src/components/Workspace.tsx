"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Classification } from "@/lib/classification";
import { postJson } from "./api";
import { SecureAssetViewer } from "./SecureAssetViewer";
import { InvestigatorPanel } from "./InvestigatorPanel";

interface Props {
  user: { displayName: string; roles: string[]; authLevel: string };
  assets: Array<{ assetId: string; title: string; classification: Classification }>;
  devTools: boolean;
}

const LABEL: Record<Classification, string> = {
  PUBLIC: "Public",
  INTERNAL: "Internal",
  CONFIDENTIAL: "Confidential",
  RESTRICTED: "Restricted",
  CROWN_JEWEL: "Crown jewel",
};

const needsPurpose = (c: Classification) => c === "RESTRICTED" || c === "CROWN_JEWEL";

export function Workspace({ user, assets, devTools }: Props) {
  const router = useRouter();
  const [selected, setSelected] = useState<string | null>(null);
  const [purpose, setPurpose] = useState("");
  const [attempt, setAttempt] = useState(0);
  const asset = assets.find((a) => a.assetId === selected) ?? null;

  async function signOut() {
    await postJson("/api/auth/logout");
    router.refresh();
  }

  async function stepUp() {
    const r = await postJson("/api/dev/step-up");
    if (r.status === 200) {
      router.refresh();
      setAttempt((n) => n + 1);
    }
  }

  return (
    <div className="workspace">
      <section className="panel identity" aria-label="Signed-in account">
        <div>
          <p className="identity-name">{user.displayName}</p>
          <p className="muted">
            Roles: {user.roles.join(", ")} · Sign-in strength: {user.authLevel.replace("_", "-")}
          </p>
        </div>
        <button type="button" className="btn btn-quiet" onClick={signOut}>
          Sign out
        </button>
      </section>

      <div className="grid">
        <section className="panel" aria-labelledby="catalogue-title">
          <h2 id="catalogue-title">Workspace assets</h2>
          <ul className="asset-list">
            {assets.map((a) => (
              <li key={a.assetId}>
                <button
                  type="button"
                  className="asset"
                  aria-pressed={selected === a.assetId}
                  onClick={() => {
                    setSelected(a.assetId);
                    setPurpose("");
                    setAttempt((n) => n + 1);
                  }}
                >
                  <span className="asset-title">{a.title}</span>
                  <span className={`badge badge-${a.classification.toLowerCase()}`}>{LABEL[a.classification]}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel viewer-panel" aria-labelledby="viewer-title">
          <h2 id="viewer-title">{asset ? asset.title : "Select an asset"}</h2>
          {asset && needsPurpose(asset.classification) && (
            <form
              className="purpose"
              onSubmit={(e) => {
                e.preventDefault();
                setAttempt((n) => n + 1);
              }}
            >
              <label htmlFor="purpose">Purpose of access (must match your grant)</label>
              <div className="purpose-row">
                <input id="purpose" value={purpose} onChange={(e) => setPurpose(e.target.value)} maxLength={200} autoComplete="off" />
                <button type="submit" className="btn">
                  Request view
                </button>
              </div>
            </form>
          )}
          {asset ? (
            <SecureAssetViewer key={`${asset.assetId}:${attempt}`} assetId={asset.assetId} purpose={purpose || null} onStepUp={devTools ? stepUp : null} />
          ) : (
            <p className="muted">Protected previews open here. Each one is fetched once, for you only, and expires in minutes.</p>
          )}
        </section>
      </div>

      {(user.roles.includes("investigator") || user.roles.includes("tenant_admin")) && <InvestigatorPanel canIntake={user.roles.includes("investigator")} />}
    </div>
  );
}
