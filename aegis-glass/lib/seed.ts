// Demo data. Every asset is synthetic: generated images, invented project
// names, no real people, customers or secrets. The decoy asset is labelled as
// a decoy only here, in code; in the product it looks like any other draft.

import sharp from "sharp";
import type { AegisService } from "./service.ts";
import type { Asset, Classification, Grant, Principal, Role, AuthLevel } from "./types.ts";

export const DEMO_TENANT = "t-demo";
export const OTHER_TENANT = "t-other";

export interface Persona {
  key: string;
  label: string;
  description: string;
  userId: string;
  tenantId: string;
  roles: Role[];
  authLevel: AuthLevel;
}

export const PERSONAS: Persona[] = [
  { key: "analyst", label: "Analyst", description: "Viewer with MFA and a grant for Project Atlas", userId: "u-analyst", tenantId: DEMO_TENANT, roles: ["viewer"], authLevel: "mfa" },
  { key: "owner", label: "Owner", description: "Owns the assets; passkey sign-in", userId: "u-owner", tenantId: DEMO_TENANT, roles: ["owner", "editor"], authLevel: "phishing_resistant" },
  { key: "admin", label: "Tenant admin", description: "Administers the tenant; no implicit access to restricted content", userId: "u-admin", tenantId: DEMO_TENANT, roles: ["tenant_admin"], authLevel: "phishing_resistant" },
  { key: "investigator", label: "Investigator", description: "Resolves trace tokens and reviews cases", userId: "u-investigator", tenantId: DEMO_TENANT, roles: ["investigator"], authLevel: "phishing_resistant" },
  { key: "outsider", label: "Other tenant", description: "Viewer in a different tenant", userId: "u-outsider", tenantId: OTHER_TENANT, roles: ["viewer"], authLevel: "mfa" },
];

export function personaPrincipal(persona: Persona, sessionId: string, authTime: number): Principal {
  return {
    userId: persona.userId,
    tenantId: persona.tenantId,
    displayName: persona.label,
    roles: [...persona.roles],
    authLevel: persona.authLevel,
    authTime,
    sessionId,
  };
}

interface SeedAsset {
  id: string;
  tenantId: string;
  title: string;
  classification: Classification;
  compartments: string[];
  isHoney: boolean;
  hue: number;
  caption: string;
}

const SEED_ASSETS: SeedAsset[] = [
  { id: "a-palette", tenantId: DEMO_TENANT, title: "Brand palette study", classification: "INTERNAL", compartments: [], isHoney: false, hue: 190, caption: "Palette study" },
  { id: "a-atlas-concept", tenantId: DEMO_TENANT, title: "Atlas homepage concept", classification: "CONFIDENTIAL", compartments: ["project-atlas"], isHoney: false, hue: 260, caption: "Atlas concept" },
  { id: "a-atlas-proto", tenantId: DEMO_TENANT, title: "Atlas v2 prototype screens", classification: "RESTRICTED", compartments: ["project-atlas"], isHoney: false, hue: 320, caption: "Atlas v2 prototype" },
  { id: "a-partner-draft", tenantId: DEMO_TENANT, title: "Partner shortlist draft", classification: "CONFIDENTIAL", compartments: [], isHoney: true, hue: 30, caption: "Partner shortlist" },
  { id: "a-core-whiteboard", tenantId: DEMO_TENANT, title: "Core method whiteboard", classification: "CROWN_JEWEL", compartments: [], isHoney: false, hue: 140, caption: "Core method" },
  { id: "a-other-plan", tenantId: OTHER_TENANT, title: "Other tenant plan", classification: "CONFIDENTIAL", compartments: [], isHoney: false, hue: 0, caption: "Other tenant" },
];

/** A synthetic 1600x1000 concept image: gradient, shapes and a caption. */
export async function syntheticImage(hue: number, caption: string): Promise<Buffer> {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="hsl(${hue},70%,18%)"/><stop offset="1" stop-color="hsl(${(hue + 60) % 360},70%,42%)"/>
  </linearGradient></defs>
  <rect width="1600" height="1000" fill="url(#g)"/>
  <circle cx="1180" cy="380" r="220" fill="hsl(${(hue + 120) % 360},80%,60%)" fill-opacity="0.55"/>
  <rect x="140" y="560" width="760" height="260" rx="28" fill="#ffffff" fill-opacity="0.12"/>
  <rect x="180" y="610" width="520" height="28" rx="14" fill="#ffffff" fill-opacity="0.6"/>
  <rect x="180" y="670" width="640" height="20" rx="10" fill="#ffffff" fill-opacity="0.35"/>
  <rect x="180" y="710" width="420" height="20" rx="10" fill="#ffffff" fill-opacity="0.35"/>
  <text x="140" y="220" font-family="DejaVu Sans, Arial, sans-serif" font-size="96" font-weight="700" fill="#ffffff">${caption}</text>
  <text x="140" y="300" font-family="DejaVu Sans, Arial, sans-serif" font-size="40" fill="#ffffff" fill-opacity="0.8">Synthetic demo artwork</text>
</svg>`;
  return sharp(Buffer.from(svg)).png().toBuffer();
}

export async function seedDemo(service: AegisService, nowSeconds: number): Promise<void> {
  for (const s of SEED_ASSETS) {
    const asset: Asset = {
      id: s.id,
      tenantId: s.tenantId,
      title: s.title,
      altText: `${s.title}: synthetic concept artwork with a gradient background, a circle and placeholder text blocks.`,
      classification: s.classification,
      ownerId: s.tenantId === DEMO_TENANT ? "u-owner" : "u-other-owner",
      compartments: s.compartments,
      isHoney: s.isHoney,
      storageKey: `objects/${s.tenantId}/${s.id}`,
      mime: "image/png",
    };
    await service.ingest(asset, await syntheticImage(s.hue, s.caption));
  }

  const grants: Grant[] = [
    { id: "g-analyst-atlas", tenantId: DEMO_TENANT, userId: "u-analyst", compartment: "project-atlas", actions: ["view"], purpose: "Atlas design review", expiresAt: nowSeconds + 30 * 24 * 3600 },
  ];
  for (const g of grants) await service.deps.repo.putGrant(g);
}
