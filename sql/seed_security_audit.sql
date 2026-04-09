-- Task 5: Security Audit & Access Control
--
-- Seeds realistic HR/project tables and three misconfigured roles plus an
-- overly permissive public-schema grant. The agent must lock everything
-- down via ALTER ROLE / GRANT / REVOKE.
--
-- Roles are cluster-global and survive the task_schema DROP done by reset(),
-- so the seed starts with an idempotent pre-clean that drops any stale roles
-- from previous episodes. The task's ``teardown()`` also drops them on the
-- next reset (belt and suspenders).

SET search_path TO task_schema, public;

-- ---------------------------------------------------------------------------
-- Idempotent pre-clean: stale roles + stale public-schema grant
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_user') THEN
        EXECUTE 'REASSIGN OWNED BY analytics_user TO dba';
        EXECUTE 'DROP OWNED BY analytics_user';
        DROP ROLE analytics_user;
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'readonly_user') THEN
        EXECUTE 'REASSIGN OWNED BY readonly_user TO dba';
        EXECUTE 'DROP OWNED BY readonly_user';
        DROP ROLE readonly_user;
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'intern_user') THEN
        EXECUTE 'REASSIGN OWNED BY intern_user TO dba';
        EXECUTE 'DROP OWNED BY intern_user';
        DROP ROLE intern_user;
    END IF;
END $$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS employees (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(100) NOT NULL,
    department VARCHAR(50)  NOT NULL,
    hire_date  DATE         NOT NULL
);

INSERT INTO employees (name, department, hire_date)
SELECT
    'Employee ' || i                                               AS name,
    (ARRAY['Engineering','Sales','HR','Marketing','Finance'])[1 + (i % 5)] AS department,
    (DATE '2020-01-01') + ((i * 7) % 1500)                         AS hire_date
FROM generate_series(1, 100) AS gs(i);

CREATE TABLE IF NOT EXISTS salaries (
    id             SERIAL PRIMARY KEY,
    employee_id    INT REFERENCES employees(id),
    amount         DECIMAL(10,2) NOT NULL,
    effective_date DATE          NOT NULL
);

INSERT INTO salaries (employee_id, amount, effective_date)
SELECT
    ((i - 1) % 100) + 1                            AS employee_id,
    (50000 + ((i * 137) % 50000))::DECIMAL(10,2)   AS amount,
    (DATE '2023-01-01') + ((i * 3) % 365)          AS effective_date
FROM generate_series(1, 100) AS gs(i);

CREATE TABLE IF NOT EXISTS projects (
    id     SERIAL PRIMARY KEY,
    name   VARCHAR(100)  NOT NULL,
    budget DECIMAL(12,2) NOT NULL,
    status VARCHAR(20)   NOT NULL
);

INSERT INTO projects (name, budget, status)
SELECT
    'Project ' || i                                                    AS name,
    (100000 + (i * 13000))::DECIMAL(12,2)                              AS budget,
    (ARRAY['planning','active','completed','on_hold'])[1 + (i % 4)]    AS status
FROM generate_series(1, 20) AS gs(i);

CREATE TABLE IF NOT EXISTS project_assignments (
    employee_id INT,
    project_id  INT,
    role        VARCHAR(50) NOT NULL,
    PRIMARY KEY (employee_id, project_id)
);

INSERT INTO project_assignments (employee_id, project_id, role)
SELECT
    ((i * 7) % 100) + 1                                            AS employee_id,
    ((i * 3) % 20) + 1                                             AS project_id,
    (ARRAY['lead','engineer','reviewer','qa'])[1 + (i % 4)]        AS role
FROM generate_series(1, 50) AS gs(i)
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- Seed the four security issues
-- ---------------------------------------------------------------------------

-- Issue 1: analytics_user has SUPERUSER (should be NOSUPERUSER).
CREATE ROLE analytics_user WITH LOGIN PASSWORD 'analytics123' SUPERUSER;

-- Issue 2: PUBLIC can CREATE objects in the public schema.
GRANT CREATE ON SCHEMA public TO PUBLIC;

-- Issue 3: readonly_user can SELECT task_schema.salaries (sensitive data leak).
CREATE ROLE readonly_user WITH LOGIN PASSWORD 'readonly123';
GRANT USAGE ON SCHEMA task_schema TO readonly_user;
GRANT SELECT ON ALL TABLES IN SCHEMA task_schema TO readonly_user;

-- Issue 4: intern_user has no password (passwordless LOGIN role).
CREATE ROLE intern_user WITH LOGIN;
GRANT USAGE ON SCHEMA task_schema TO intern_user;
GRANT SELECT ON employees, projects, project_assignments TO intern_user;

ANALYZE employees;
ANALYZE salaries;
ANALYZE projects;
ANALYZE project_assignments;
