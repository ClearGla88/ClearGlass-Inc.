import sharp from "sharp";
import type { AuthLevel, Classification } from "./classification";
import type { Role } from "./policy";
import type { AegisService } from "./service";
import { pseudonym } from "./trace";
import type { AegisConfig } from "./config";

// Development seed. Every image is synthetic, generated here from SVG: no real
// customer data, documents, people, or credentials. The honey asset is a
// plausible-looking decoy with fictional figures and a canary reference code.

export const DEMO_TENANT = "6f1d2c3b-0000-4000-8000-00000000a001";
export const OTHER_TENANT = "6f1d2c3b-0000-4000-8000-00000000b001";

export interface Persona {
  key: "analyst" | "admin" | "investigator" | "outsider";
  userId: string;
  tenantId: string;
  displayName: string;
  roles: Role[];
  authLevel: AuthLevel;
  description: string;
}

export const PERSONAS: readonly Persona[] = [
  { key: "analyst", userId: "6f1d2c3b-0000-4000-8000-0000000000a1", tenantId: DEMO_TENANT, displayName: "Avery (analyst)", roles: ["member"], authLevel: "mfa", description: "Member with MFA. Has a design-lab grant and a purpose-bound prototype grant." },
  { key: "admin", userId: "6f1d2c3b-0000-4000-8000-0000000000a2", tenantId: DEMO_TENANT, displayName: "Morgan (tenant admin)", roles: ["member", "tenant_admin"], authLevel: "mfa", description: "Owns the crown-jewel asset; must step up to a passkey to open it." },
  { key: "investigator", userId: "6f1d2c3b-0000-4000-8000-0000000000a3", tenantId: DEMO_TENANT, displayName: "Rowan (investigator)", roles: ["member", "investigator"], authLevel: "phishing_resistant", description: "Runs leak intake and audit verification." },
  { key: "outsider", userId: "6f1d2c3b-0000-4000-8000-0000000000b1", tenantId: OTHER_TENANT, displayName: "Casey (other tenant)", roles: ["member", "tenant_admin"], authLevel: "phishing_resistant", description: "Admin of a different tenant. Sees none of the demo tenant's assets." },
];

export const PROTOTYPE_PURPOSE = "Q4 design review";

function syntheticImage(title: string, subtitle: string, hueA: string, hueB: string, extra = ""): Promise<Buffer> {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${hueA}"/><stop offset="1" stop-color="${hueB}"/></linearGradient></defs>
  <rect width="1600" height="1000" fill="url(#g)"/>
  <g stroke="#ffffff" stroke-opacity="0.18" fill="none">${Array.from({ length: 14 }, (_, i) => `<circle cx="${800 + Math.cos(i) * 260}" cy="${500 + Math.sin(i * 1.7) * 160}" r="${60 + i * 22}"/>`).join("")}</g>
  <rect x="90" y="90" width="1420" height="820" rx="36" fill="#ffffff" fill-opacity="0.08" stroke="#ffffff" stroke-opacity="0.35"/>
  <text x="150" y="230" font-family="DejaVu Sans, sans-serif" font-size="68" font-weight="700" fill="#ffffff">${title}</text>
  <text x="150" y="300" font-family="DejaVu Sans, sans-serif" font-size="32" fill="#e6f7ff">${subtitle}</text>
  ${extra}
  <text x="150" y="860" font-family="DejaVu Sans Mono, monospace" font-size="24" fill="#ffffff" fill-opacity="0.7">SYNTHETIC DEMO CONTENT · NOT REAL DATA</text>
</svg>`;
  return sharp(Buffer.from(svg)).png().toBuffer();
}

const bars = (values: number[]) =>
  values
    .map((v, i) => `<rect x="${170 + i * 150}" y="${760 - v * 4}" width="90" height="${v * 4}" fill="#ffffff" fill-opacity="0.55"/><text x="${180 + i * 150}" y="${745 - v * 4}" font-family="DejaVu Sans Mono, monospace" font-size="24" fill="#ffffff">${v}</text>`)
    .join("");

export async function seedDemo(service: AegisService, config: AegisConfig): Promise<{ seeded: boolean }> {
  const store = service.store;
  if (await store.tenantPseudonym(DEMO_TENANT)) return { seeded: false };

  await store.insertTenant({ tenantId: DEMO_TENANT, name: "ClearGlass Demo Studio", pseudonym: pseudonym(config.keys.pseudonym, "T", DEMO_TENANT) });
  await store.insertTenant({ tenantId: OTHER_TENANT, name: "Other Organisation", pseudonym: pseudonym(config.keys.pseudonym, "T", OTHER_TENANT) });
  for (const p of PERSONAS) await store.insertUser({ userId: p.userId, tenantId: p.tenantId, displayName: p.displayName, roles: p.roles });

  const [analyst, admin, investigator, outsider] = PERSONAS as [Persona, Persona, Persona, Persona];
  const reg = async (owner: Persona, title: string, altText: string, classification: Classification, compartment: string | null, honey: boolean, bytes: Buffer) =>
    service.registerAsset({ tenantId: owner.tenantId, ownerId: owner.userId, title, altText, classification, compartment, honey, bytes });

  await reg(admin, "Studio wall: team offsite board", "Gradient board with concentric rings and the words Team offsite.", "INTERNAL", null, false,
    await syntheticImage("Team offsite board", "Internal · open to every member", "#0d3b66", "#3fa7d6"));
  await reg(admin, "Concept draft: glass facade study", "Concept sketch of a glass facade with ring geometry.", "CONFIDENTIAL", "design-lab", false,
    await syntheticImage("Glass facade study", "Concept draft v3 · design-lab", "#14213d", "#5e60ce"));
  await reg(admin, "Prototype schematic: lens array", "Schematic panel titled Lens array prototype.", "RESTRICTED", "prototype", false,
    await syntheticImage("Lens array prototype", "Restricted · purpose-bound access", "#2b2d42", "#ef233c"));
  await reg(admin, "Board roadmap: Project Halo", "Roadmap slide titled Project Halo.", "CROWN_JEWEL", null, false,
    await syntheticImage("Project Halo", "Crown jewel · owner only · passkey", "#1b1b1e", "#ffb703"));
  // Canary: looks like a pricing model; every figure is invented; REF code is the canary id.
  await reg(investigator, "Pricing model FY27 (draft)", "Bar chart titled Pricing model FY27 draft.", "CONFIDENTIAL", "design-lab", true,
    await syntheticImage("Pricing model FY27", "Draft · design-lab", "#003049", "#669bbc", bars([41, 58, 63, 77, 52, 88, 69]) + `<text x="1240" y="860" font-family="DejaVu Sans Mono, monospace" font-size="22" fill="#ffffff" fill-opacity="0.5">REF HX-0417</text>`));
  await reg(outsider, "Other tenant: supplier map", "Map of suppliers belonging to another organisation.", "CONFIDENTIAL", null, false,
    await syntheticImage("Supplier map", "Belongs to another tenant", "#283618", "#606c38"));

  const now = Math.floor(Date.now() / 1000);
  await service.createGrant({ tenantId: DEMO_TENANT, subjectUserId: null, subjectRole: "member", assetId: null, compartment: "design-lab", actions: ["view"], purpose: null, notBefore: now - 60, expiresAt: now + 30 * 86400 }, admin.userId);
  await service.createGrant({ tenantId: DEMO_TENANT, subjectUserId: analyst.userId, subjectRole: null, assetId: null, compartment: "prototype", actions: ["view"], purpose: PROTOTYPE_PURPOSE, notBefore: now - 60, expiresAt: now + 7 * 86400 }, admin.userId);
  return { seeded: true };
}
