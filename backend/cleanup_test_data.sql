-- Purge schools created by test_full_integration.py and test_client_school.py.
--
-- The API cannot delete a school once a timetable exists (there is no endpoint to
-- delete timetable rows, so the foreign-key guard returns 409 forever). Run this
-- to remove leftover test schools. It only touches 'IntegrationSchool-%' / 'ClientSchool-%'
-- and never touches real schools.
--
-- Usage:
--   psql -U eduflow -h localhost -d eduflow_ai -v ON_ERROR_STOP=1 -f cleanup_test_data.sql

BEGIN;

CREATE TEMP TABLE junk AS
    SELECT id FROM schools
    WHERE name LIKE 'IntegrationSchool-%' OR name LIKE 'ClientSchool-%';

CREATE TEMP TABLE junk_sec AS
    SELECT s.id FROM sections s
    JOIN classes c ON s.class_id = c.id
    WHERE c.school_id IN (SELECT id FROM junk);

CREATE TEMP TABLE junk_t AS
    SELECT id, user_id FROM teachers WHERE school_id IN (SELECT id FROM junk);

CREATE TEMP TABLE junk_u AS
    SELECT user_id AS id FROM junk_t
    UNION
    SELECT id FROM users WHERE school_id IN (SELECT id FROM junk);

DELETE FROM substitutions WHERE timetable_id IN (SELECT id FROM timetables WHERE school_id IN (SELECT id FROM junk));
DELETE FROM swaps        WHERE timetable_id_a IN (SELECT id FROM timetables WHERE school_id IN (SELECT id FROM junk));
DELETE FROM timetable_version_slots WHERE version_id IN (SELECT id FROM timetable_versions WHERE school_id IN (SELECT id FROM junk));
DELETE FROM timetable_versions WHERE school_id IN (SELECT id FROM junk);
DELETE FROM timetables   WHERE school_id IN (SELECT id FROM junk);
DELETE FROM exams        WHERE section_id IN (SELECT id FROM junk_sec);
DELETE FROM leaves       WHERE teacher_id IN (SELECT id FROM junk_t);
DELETE FROM teacher_availability WHERE teacher_id IN (SELECT id FROM junk_t);
DELETE FROM teacher_preferences  WHERE teacher_id IN (SELECT id FROM junk_t);
DELETE FROM teacher_subjects     WHERE teacher_id IN (SELECT id FROM junk_t);
DELETE FROM subject_assignments  WHERE school_id IN (SELECT id FROM junk);
-- sections.class_teacher_id references teachers; detach before removing them.
UPDATE sections SET class_teacher_id = NULL WHERE class_teacher_id IN (SELECT id FROM junk_t);
DELETE FROM teachers     WHERE school_id IN (SELECT id FROM junk);
DELETE FROM notifications WHERE user_id IN (SELECT id FROM junk_u);
DELETE FROM audit_logs    WHERE user_id IN (SELECT id FROM junk_u);
DELETE FROM users         WHERE id IN (SELECT id FROM junk_u);
DELETE FROM sections      WHERE id IN (SELECT id FROM junk_sec);
DELETE FROM classes       WHERE school_id IN (SELECT id FROM junk);
DELETE FROM subjects      WHERE school_id IN (SELECT id FROM junk);
DELETE FROM activities    WHERE school_id IN (SELECT id FROM junk);
DELETE FROM resources     WHERE school_id IN (SELECT id FROM junk);
DELETE FROM calendar_events WHERE school_id IN (SELECT id FROM junk);
DELETE FROM school_configs  WHERE school_id IN (SELECT id FROM junk);
DELETE FROM schools       WHERE id IN (SELECT id FROM junk);

COMMIT;

SELECT id, name FROM schools ORDER BY id;
