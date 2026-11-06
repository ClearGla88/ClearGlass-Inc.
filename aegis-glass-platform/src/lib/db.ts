import { PGlite } from "@electric-sql/pglite";
import pg from "pg";

// One SQL dialect (PostgreSQL), two engines:
//   - PGlite: real Postgres compiled to WASM, in-process. Development and CI.
//   - pg.Pool: a PostgreSQL server. Production.
// Both satisfy Database, so every query in AegisStore runs unchanged on either.

export interface QueryRunner {
  query<T = Record<string, unknown>>(sql: string, params?: unknown[]): Promise<{ rows: T[] }>;
}

export interface Database extends QueryRunner {
  readonly engine: "pglite" | "postgres";
  exec(sql: string): Promise<void>;
  transaction<T>(fn: (tx: QueryRunner) => Promise<T>): Promise<T>;
  close(): Promise<void>;
}

export async function openPglite(dataDir?: string): Promise<Database> {
  const db = dataDir ? new PGlite(dataDir) : new PGlite();
  await db.waitReady;
  return {
    engine: "pglite",
    query: async <T>(sql: string, params?: unknown[]) => ({ rows: (await db.query<T>(sql, params)).rows }),
    exec: async (sql) => {
      await db.exec(sql);
    },
    transaction: (fn) => db.transaction((tx) => fn({ query: async <T>(sql: string, params?: unknown[]) => ({ rows: (await tx.query<T>(sql, params)).rows }) })),
    close: () => db.close(),
  };
}

export function openPostgres(connectionString: string): Database {
  const pool = new pg.Pool({ connectionString, max: 10, statement_timeout: 10_000 });
  const run = (client: pg.Pool | pg.PoolClient): QueryRunner => ({
    query: async <T>(sql: string, params?: unknown[]) => ({ rows: (await client.query(sql, params as unknown[])).rows as T[] }),
  });
  return {
    engine: "postgres",
    ...run(pool),
    exec: async (sql) => {
      await pool.query(sql);
    },
    transaction: async (fn) => {
      const client = await pool.connect();
      try {
        await client.query("BEGIN");
        const result = await fn(run(client));
        await client.query("COMMIT");
        return result;
      } catch (err) {
        await client.query("ROLLBACK").catch(() => undefined);
        throw err;
      } finally {
        client.release();
      }
    },
    close: () => pool.end(),
  };
}
