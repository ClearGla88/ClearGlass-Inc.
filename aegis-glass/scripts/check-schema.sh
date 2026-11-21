#!/usr/bin/env bash
# Applies db/schema.sql to a throwaway PostgreSQL cluster and proves the
# guarantees it claims: append-only evidence tables and tenant isolation.
# Needs PostgreSQL server binaries (initdb, pg_ctl) on PATH or under
# /usr/lib/postgresql/<version>/bin.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
bin="$(dirname "$(command -v initdb 2>/dev/null || ls -d /usr/lib/postgresql/*/bin/initdb | tail -1)")"
work="$(mktemp -d)"
port=55432
run_as=()
if [ "$(id -u)" = "0" ]; then
  chown -R postgres "$work" 2>/dev/null || true
  run_as=(runuser -u postgres --)
fi

cleanup() {
  "${run_as[@]}" "$bin/pg_ctl" -D "$work/data" -m immediate stop >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

"${run_as[@]}" "$bin/initdb" -D "$work/data" -A trust -U postgres >/dev/null
"${run_as[@]}" "$bin/pg_ctl" -D "$work/data" -o "-p $port -k $work -c listen_addresses=''" -l "$work/log" -w start >/dev/null

psql_() { psql -h "$work" -p "$port" -U postgres -v ON_ERROR_STOP=1 -X -q "$@"; }

psql_ -d postgres -c "CREATE DATABASE aegis"
psql_ -d aegis -f "$here/db/schema.sql"
echo "schema applied"

# Seed two tenants as a superuser-free app role so RLS applies.
psql_ -d aegis <<'SQL'
CREATE ROLE aegis_app LOGIN;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO aegis_app;
INSERT INTO tenants (id, name) VALUES ('11111111-1111-1111-1111-111111111111', 'A'), ('22222222-2222-2222-2222-222222222222', 'B');
SET aegis.tenant_id = '11111111-1111-1111-1111-111111111111';
INSERT INTO principals (id, tenant_id, oidc_sub, roles) VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '11111111-1111-1111-1111-111111111111', 'sub-a', '{owner}');
SET aegis.tenant_id = '22222222-2222-2222-2222-222222222222';
INSERT INTO principals (id, tenant_id, oidc_sub, roles) VALUES ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '22222222-2222-2222-2222-222222222222', 'sub-b', '{owner}');
INSERT INTO audit_events VALUES (1, now(), 'media.served', 't', 'u', 'a', '{}', repeat('0',64), repeat('a',64), repeat('b',64));
SQL

fail=0
expect_error() {
  local label="$1" sql="$2"
  if psql_ -d aegis -U aegis_app -c "$sql" >/dev/null 2>&1; then
    echo "FAIL: $label succeeded"; fail=1
  else
    echo "ok:   $label refused"
  fi
}

expect_error "UPDATE audit_events" "UPDATE audit_events SET actor = 'x'"
expect_error "DELETE audit_events" "DELETE FROM audit_events"
expect_error "grant with both asset and compartment" \
  "SET aegis.tenant_id = '11111111-1111-1111-1111-111111111111'; INSERT INTO policy_grants (tenant_id, user_id, asset_id, compartment, actions, purpose, granted_by, expires_at) VALUES ('11111111-1111-1111-1111-111111111111','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', gen_random_uuid(), 'x', '{view}', 'test', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', now() + interval '1 day')"
expect_error "insert into another tenant" \
  "SET aegis.tenant_id = '11111111-1111-1111-1111-111111111111'; INSERT INTO principals (tenant_id, oidc_sub) VALUES ('22222222-2222-2222-2222-222222222222', 'sneak')"

seen="$(psql_ -d aegis -U aegis_app -At -c "SET aegis.tenant_id = '11111111-1111-1111-1111-111111111111'; SELECT count(*) FROM principals")"
if [ "$seen" = "1" ]; then echo "ok:   tenant A sees only its own principals"; else echo "FAIL: tenant A saw $seen principals"; fail=1; fi
none="$(psql_ -d aegis -U aegis_app -At -c "SELECT count(*) FROM principals")"
if [ "$none" = "0" ]; then echo "ok:   no tenant set means no rows"; else echo "FAIL: unscoped query saw $none rows"; fail=1; fi

exit "$fail"
