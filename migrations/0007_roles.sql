-- 0007: least privilege. Applications should not connect as the owner of the tables.
--
--   labtrack_reader  can SELECT everything in lab and bi (dashboards, analysts).
--   labtrack_writer  can also INSERT, UPDATE and DELETE in lab (the app), but cannot change the schema.
--
-- Roles belong to the whole cluster, not to one database, and creating them needs the CREATEROLE
-- privilege. If the migration user lacks it, the block below says so and moves on instead of failing.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'labtrack_reader') THEN
        CREATE ROLE labtrack_reader NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'labtrack_writer') THEN
        CREATE ROLE labtrack_writer NOLOGIN IN ROLE labtrack_reader;
    END IF;
EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'skipping roles: this user may not create roles';
END
$$;

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'labtrack_reader') THEN
        GRANT USAGE ON SCHEMA lab, bi TO labtrack_reader;
        GRANT SELECT ON ALL TABLES IN SCHEMA lab, bi TO labtrack_reader;
        GRANT USAGE ON SCHEMA lab TO labtrack_writer;
        GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA lab TO labtrack_writer;
        GRANT USAGE ON ALL SEQUENCES IN SCHEMA lab TO labtrack_writer;
        -- Tables created by later migrations get the same grants automatically.
        ALTER DEFAULT PRIVILEGES IN SCHEMA lab, bi GRANT SELECT ON TABLES TO labtrack_reader;
        ALTER DEFAULT PRIVILEGES IN SCHEMA lab GRANT INSERT, UPDATE, DELETE ON TABLES TO labtrack_writer;
        ALTER DEFAULT PRIVILEGES IN SCHEMA lab GRANT USAGE ON SEQUENCES TO labtrack_writer;
    END IF;
END
$$;
