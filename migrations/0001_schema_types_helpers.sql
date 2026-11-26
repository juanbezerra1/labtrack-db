-- 0001: the schema, the extension, the enumerated types and two small helper functions.
--
-- Everything the application owns lives in the schema "lab" (and, for reporting, "bi"), never in
-- "public": a dedicated schema keeps the objects easy to list, grant and drop.

CREATE SCHEMA lab;
COMMENT ON SCHEMA lab IS
    'LabTrack: who was recorded, when, with which equipment, and what came out of it.';

-- btree_gist lets a GiST index compare plain equality (a room) together with range overlap (a time
-- slot). That is what makes "one session per room at a time" a constraint instead of a hope.
-- It ships with PostgreSQL (the contrib package) and is a "trusted" extension: the owner of the
-- database can create it without being a superuser.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Enumerated types: small closed sets of values, stored in 4 bytes and sorted in declaration order.
-- (A lookup table is the alternative when the list changes often; docs/design-notes.md compares them.)
CREATE TYPE lab.researcher_role AS ENUM ('pi', 'postdoc', 'phd', 'msc', 'technician');
CREATE TYPE lab.hand            AS ENUM ('right', 'left', 'ambidextrous');
CREATE TYPE lab.device_kind     AS ENUM ('emg_amplifier', 'eeg_amplifier', 'dynamometer', 'stimulator');
CREATE TYPE lab.session_status  AS ENUM ('scheduled', 'completed', 'cancelled', 'no_show');
CREATE TYPE lab.modality        AS ENUM ('emg', 'eeg', 'force');
CREATE TYPE lab.qc_status       AS ENUM ('pending', 'passed', 'flagged', 'rejected');

-- "Today", but overridable: SET labtrack.as_of = '2026-10-31' makes every view that talks about
-- "overdue" or "upcoming" answer as if it were that day. Tests and the committed CSV exports use it,
-- so their numbers never depend on the day they were produced.
CREATE FUNCTION lab.reference_date() RETURNS date
    LANGUAGE sql STABLE
    AS $$
        SELECT coalesce(nullif(current_setting('labtrack.as_of', true), ''), current_date::text)::date
    $$;
COMMENT ON FUNCTION lab.reference_date() IS
    'The date that "today" means: the setting labtrack.as_of when it is set, else current_date.';

-- Keeps updated_at honest without trusting every writer to remember it.
CREATE FUNCTION lab.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END
$$;
