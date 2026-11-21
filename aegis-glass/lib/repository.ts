// Data access. Every lookup is tenant-scoped: there is no "get asset by ID"
// without a tenant, which closes the insecure-direct-object-reference path by
// construction. Production implements this interface over Postgres with
// row-level security (db/schema.sql); the in-memory version backs dev and tests.

import type { Asset, Grant } from "./types.ts";
import type { SealedObject } from "./envelope.ts";
import type { ViewReceipt } from "./receipts.ts";

export interface IncidentCase {
  id: string;
  tenantId: string;
  kind: "honey_access" | "leak_report" | "risk_critical";
  status: "needs_review" | "investigating" | "closed_no_action" | "closed_action_taken";
  subjectUserId: string;
  subjectSessionId: string;
  assetId?: string;
  openedAt: string;
  /** Plain-language summary of the evidence. A case is an allegation, not a finding. */
  summary: string;
}

export interface Repository {
  getAsset(tenantId: string, assetId: string): Promise<Asset | undefined>;
  listAssets(tenantId: string): Promise<Asset[]>;
  putAsset(asset: Asset): Promise<void>;
  grantsFor(tenantId: string, userId: string): Promise<Grant[]>;
  putGrant(grant: Grant): Promise<void>;
  revokeGrant(tenantId: string, grantId: string, at: number): Promise<boolean>;
  putReceipt(receipt: ViewReceipt): Promise<void>;
  receiptByTrace(tenantId: string, traceToken: string): Promise<ViewReceipt | undefined>;
  openCase(c: IncidentCase): Promise<void>;
  listCases(tenantId: string): Promise<IncidentCase[]>;
}

export interface ObjectStore {
  put(key: string, sealed: SealedObject): Promise<void>;
  get(key: string): Promise<SealedObject | undefined>;
}

export class MemoryRepository implements Repository {
  private readonly assets = new Map<string, Asset>();
  private readonly grants = new Map<string, Grant>();
  private readonly receipts = new Map<string, ViewReceipt>();
  private readonly cases: IncidentCase[] = [];

  private static key(tenantId: string, id: string): string {
    return `${tenantId}\u0000${id}`;
  }

  async getAsset(tenantId: string, assetId: string): Promise<Asset | undefined> {
    return this.assets.get(MemoryRepository.key(tenantId, assetId));
  }

  async listAssets(tenantId: string): Promise<Asset[]> {
    return [...this.assets.values()].filter((a) => a.tenantId === tenantId);
  }

  async putAsset(asset: Asset): Promise<void> {
    this.assets.set(MemoryRepository.key(asset.tenantId, asset.id), { ...asset });
  }

  async grantsFor(tenantId: string, userId: string): Promise<Grant[]> {
    return [...this.grants.values()].filter((g) => g.tenantId === tenantId && g.userId === userId).map((g) => ({ ...g }));
  }

  async putGrant(grant: Grant): Promise<void> {
    this.grants.set(MemoryRepository.key(grant.tenantId, grant.id), { ...grant });
  }

  async revokeGrant(tenantId: string, grantId: string, at: number): Promise<boolean> {
    const g = this.grants.get(MemoryRepository.key(tenantId, grantId));
    if (!g || g.revokedAt !== undefined) return false;
    g.revokedAt = at;
    return true;
  }

  async putReceipt(receipt: ViewReceipt): Promise<void> {
    this.receipts.set(MemoryRepository.key(receipt.body.tenantId, receipt.body.traceToken), receipt);
  }

  async receiptByTrace(tenantId: string, traceToken: string): Promise<ViewReceipt | undefined> {
    return this.receipts.get(MemoryRepository.key(tenantId, traceToken));
  }

  async openCase(c: IncidentCase): Promise<void> {
    this.cases.push({ ...c });
  }

  async listCases(tenantId: string): Promise<IncidentCase[]> {
    return this.cases.filter((c) => c.tenantId === tenantId).map((c) => ({ ...c }));
  }
}

/** Only ciphertext is ever stored. Production: a private bucket with public access blocked. */
export class MemoryObjectStore implements ObjectStore {
  private readonly objects = new Map<string, SealedObject>();

  async put(key: string, sealed: SealedObject): Promise<void> {
    this.objects.set(key, sealed);
  }

  async get(key: string): Promise<SealedObject | undefined> {
    return this.objects.get(key);
  }
}
