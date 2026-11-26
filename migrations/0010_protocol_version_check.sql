-- 0010: step 3 of 4. Add the rule, without checking the old rows yet.
--
-- NOT VALID means: enforce the CHECK for rows inserted or changed from now on, and do not scan the
-- existing ones. The command is instant. The strong lock it needs is released when this migration
-- commits, a moment later.
--
-- Note "IS NOT NULL" inside the CHECK. A CHECK constraint is satisfied when its expression is TRUE
-- *or NULL*, and "NULL ~ 'regex'" is NULL, so a format test alone lets NULL through. Saying it
-- explicitly makes the constraint prove "never NULL", which step 4 relies on (tests/test_migrate.py
-- checks that PostgreSQL really does skip the scan).

ALTER TABLE lab.session
    ADD CONSTRAINT session_protocol_format
    CHECK (protocol_version IS NOT NULL AND protocol_version ~ '^v[0-9]+$') NOT VALID;
