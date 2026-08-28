-- A read-only role for the extractor, on Coal Washery's Postgres.
--
--   psql "$CW_ADMIN_DSN" -v pw="'a-strong-password'" -f grants.sql
--
-- Two properties matter more than the grants themselves, and both are
-- fail-closed by default in Postgres. Do not undo them:
--
--   1. NO `ALTER DEFAULT PRIVILEGES`. Tables created by a future CW migration
--      are then not granted at all — invisible to the extractor until somebody
--      grants them deliberately. The alternative silently exposes whatever the
--      next migration adds.
--
--   2. `users` is granted COLUMN BY COLUMN. A column-level grant does not
--      extend to columns added later, so a future `users.recovery_token` is
--      unreadable without a further decision here. A table-level grant would
--      have picked it up automatically.
--
-- The role can read and nothing else: no INSERT, no UPDATE, no DELETE, no DDL.
-- Reading is the whole security posture. When the trading system needs to write
-- back, that is a different credential and a different document.

\set ON_ERROR_STOP on

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cw_reader') THEN
    CREATE ROLE cw_reader LOGIN;
  END IF;
END
$$;

ALTER ROLE cw_reader WITH PASSWORD :pw;
ALTER ROLE cw_reader SET default_transaction_read_only = on;

GRANT CONNECT ON DATABASE coal_washery_erp TO cw_reader;
GRANT USAGE   ON SCHEMA public TO cw_reader;

-- Everything the contract reads, except users.
GRANT SELECT ON
  site_groups, sites, roles,
  debtors, creditors, vehicles, coal_sources, stock_items, stock_sizes,
  material_rates, transport_rates, company_assets, gates,
  gate_entries, weighments, rom_inward, wash_batches, wash_batch_outputs,
  quality_samples, quality_results, outward_dispatch, stock_movements,
  sales_invoices, sales_invoice_lines, eway_bills, transit_passes,
  audit_logs
TO cw_reader;

-- users, by column. password_hash and session_token are absent by omission,
-- and so is anything a later migration adds.
GRANT SELECT (
  id, site_id, name, email, role_id, active, is_superadmin,
  company_id, is_company_admin, is_owner, created_at,
  failed_login_attempts, locked_until
) ON users TO cw_reader;

-- Prove it: this must return zero rows.
SELECT c.relname AS unexpectedly_writable
  FROM information_schema.role_table_grants g
  JOIN pg_class c ON c.relname = g.table_name
 WHERE g.grantee = 'cw_reader'
   AND g.privilege_type <> 'SELECT';
