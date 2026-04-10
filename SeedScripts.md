# Postgres DBA Gym — Seed Scripts

PostgreSQL **16** training data and scenarios. All seeds are **pure SQL** (`generate_series`, `random()`, etc.), **self-contained** (`DROP TABLE IF EXISTS ... CASCADE`, `CREATE`, `INSERT`, `ANALYZE`), and intended to finish in **under ~30 seconds** on modest hardware when run against a local instance.

## Contents

| File | Purpose |
|------|---------|
| [sql/seed_index_optimization.sql](sql/seed_index_optimization.sql) | Large `orders` table **with no secondary indexes** (only PK) — index tuning baseline |
| [sql/seed_schema_migration.sql](sql/seed_schema_migration.sql) | Denormalized `user_orders` — normalization / migration exercise |
| [sql/seed_performance_diagnosis.sql](sql/seed_performance_diagnosis.sql) | Four simultaneous **diagnosis** problems (indexes, bloat, config, locks) |

---

## Prerequisites

- **Docker** with the engine running (Docker Desktop on Windows), *or* any PostgreSQL 16 server where you can run `psql` as a superuser.
- Scripts assume default database **`postgres`** unless you pass `-d yourdb`.

**Important:** `seed_performance_diagnosis.sql` runs **`ALTER SYSTEM`** and **`pg_reload_conf()`**. That **rewrites** `postgresql.auto.conf` in the data directory and persists until you change or remove those settings. For a throwaway lab, use a **dedicated container** you can delete after the exercise.

---

## Quick start (Docker + PostgreSQL 16)

From the repo root (`PostgresDBA_Gym`):

```powershell
docker rm -f pg-test 2>$null
docker run -d --name pg-test -e POSTGRES_PASSWORD=test -p 5432:5432 postgres:16
```

Wait until PostgreSQL accepts connections:

```powershell
docker exec pg-test pg_isready -U postgres
```

Run a seed (see **Running with psql** below for PowerShell vs bash).

---

## Running with `psql`

### PowerShell (Windows)

PowerShell **does not** support bash-style stdin redirection `psql < file.sql`. Pipe the file instead:

```powershell
cd D:\PostgresDBA_Gym

Get-Content -Raw .\sql\seed_index_optimization.sql |
  docker exec -i pg-test psql -U postgres -v ON_ERROR_STOP=1

Get-Content -Raw .\sql\seed_schema_migration.sql |
  docker exec -i pg-test psql -U postgres -v ON_ERROR_STOP=1

Get-Content -Raw .\sql\seed_performance_diagnosis.sql |
  docker exec -i pg-test psql -U postgres -v ON_ERROR_STOP=1
```

`-v ON_ERROR_STOP=1` stops on the first SQL error and returns a non-zero exit code.

**Optional — time a run:**

```powershell
Measure-Command {
  Get-Content -Raw .\sql\seed_index_optimization.sql |
    docker exec -i pg-test psql -U postgres -v ON_ERROR_STOP=1
}
```

**Alternative — `cmd` so `<` works:**

```powershell
cmd /c "docker exec -i pg-test psql -U postgres -v ON_ERROR_STOP=1 < sql\seed_index_optimization.sql"
```

**Alternative — copy file into container and use `-f`:**

```powershell
docker cp .\sql\seed_index_optimization.sql pg-test:/tmp/seed.sql
docker exec -i pg-test psql -U postgres -v ON_ERROR_STOP=1 -f /tmp/seed.sql
```

### Bash / WSL / Linux

```bash
docker exec -i pg-test psql -U postgres -v ON_ERROR_STOP=1 < sql/seed_index_optimization.sql
docker exec -i pg-test psql -U postgres -v ON_ERROR_STOP=1 < sql/seed_schema_migration.sql
docker exec -i pg-test psql -U postgres -v ON_ERROR_STOP=1 < sql/seed_performance_diagnosis.sql
```

### Local `psql` (no Docker)

If PostgreSQL 16 is installed locally and `psql` is on your `PATH`:

```bash
psql -U postgres -v ON_ERROR_STOP=1 -f sql/seed_index_optimization.sql
```

---

## Expected `psql` output and notices

On the **first** run of any script, you may see:

```text
NOTICE:  table "..." does not exist, skipping
```

That comes from `DROP TABLE IF EXISTS ...` when the table is not there yet. It is **not** a failure.

Successful loads typically show lines like:

- `DROP TABLE`
- `CREATE TABLE`
- `INSERT 0 <n>`
- `ANALYZE`

For `seed_performance_diagnosis.sql` you will also see output from the intentional `SELECT count(*)` probes and `pg_reload_conf()`.

---

## File 1: `sql/seed_index_optimization.sql`

### Goal

Practice choosing and creating indexes when the planner has **only the primary key** and otherwise **sequential scans** wide filters.

### Table: `orders`

| Column | Type | Notes |
|--------|------|--------|
| `id` | `SERIAL` | Primary key |
| `customer_id` | `INTEGER NOT NULL` | Values **1..5000** |
| `order_date` | `TIMESTAMP NOT NULL` | ~last **2 years**, skewed **more recent** (`power(random(), 2.2)`) |
| `status` | `VARCHAR(20) NOT NULL` | Weighted: **60%** completed, **15%** pending, **10%** shipped, **8%** cancelled, **7%** returned |
| `amount` | `DECIMAL(10,2) NOT NULL` | **$5.99–$2499.99**, log-uniform (bulk in mid range) |
| `region` | `VARCHAR(50) NOT NULL` | 8 regions (see script) |
| `product_category` | `VARCHAR(50) NOT NULL` | 8 categories (see script) |
| `shipping_method` | `VARCHAR(30) NOT NULL` | Standard, Express, Overnight, Economy |

**Rows:** **100,000**  
**Indexes:** **None** beyond the primary key on `id`.

### End state

`ANALYZE orders;` has been run.

### Training excerpt (from script)

**Target query:**

```sql
SELECT *
FROM orders
WHERE customer_id = 1234
  AND status = 'completed'
  AND order_date >= now() - interval '90 days'
ORDER BY order_date DESC
LIMIT 100;
```

**Suggested index:**

```sql
CREATE INDEX idx_orders_customer_status_date
    ON orders(customer_id, status, order_date DESC);
```

**Expected outcome:** plan moves from **sequential scan** toward **index** usage; aim for **~10×+** speedup on suitable hardware and shared_buffers.

---

## File 2: `sql/seed_schema_migration.sql`

### Goal

Normalize a **denormalized** table that duplicates customer attributes on every order row (**2NF/3NF** violations).

### Table: `user_orders`

| Column | Type |
|--------|------|
| `id` | `SERIAL` PK |
| `customer_name`, `customer_email`, `customer_address`, `customer_phone`, `customer_tier` | Customer fields **repeated** per order |
| `order_date`, `order_amount`, `order_status` | Order facts |
| `product_name`, `product_category`, `quantity` | Line-item style columns on one row |

**Rows:** **5,000**  
**Customers:** **500** logical customers (~**10** orders each). Customer fields are **identical** for all rows of the same customer (join key is `((order_no - 1) % 500) + 1`).

### Distributions

- **Tiers:** **50%** bronze, **25%** silver, **15%** gold, **10%** platinum (by `customer_id` ranges).
- **order_status:** same weighting pattern as file 1 (60/15/10/8/7).
- **order_amount:** log-uniform between 5.99 and 2499.99.
- Names like `Customer_001` … `Customer_500`; emails `customer_XXX@example.com`.

### Expected normalized design (from script comments)

- **`customers`**: one row per customer (**500** rows after migration).
- **`orders`**: one row per original `user_orders` row (**5000** rows), with `customer_id` → `customers(id)`.
- **`user_orders_view`**: `JOIN` that reproduces original column layout and row count.

### End state

`ANALYZE user_orders;` has been run.

---

## File 3: `sql/seed_performance_diagnosis.sql`

### Goal

Find and fix **four** issues at once: missing indexes, heap bloat, bad GUCs, and an **idle-in-transaction** locker (simulated outside SQL).

### Problem 1 — Missing indexes

**Table:** `transactions` — **200,000** rows.

Columns: `id` (PK), `account_id`, `transaction_date`, `merchant`, `category`, `amount`, `status`, `region`.

The script runs selective counts then **`ANALYZE transactions`**. There are **no** secondary indexes (only PK).

### Problem 2 — Table bloat

**Table:** `logs` — insert **100,000** rows, then **`DELETE`** rows with **`id <= 80000`**, leaving **20,000** live rows and **many dead tuples**. **`ANALYZE logs`** follows.

Typical trainee actions: inspect `pg_stat_user_tables`, run `VACUUM` / `VACUUM FULL` as appropriate for the lesson.

### Problem 3 — Bad `postgresql.conf` settings

The script runs:

- `ALTER SYSTEM SET shared_buffers = '32MB';`
- `ALTER SYSTEM SET work_mem = '1MB';`
- `ALTER SYSTEM SET random_page_cost = '4.0';`
- `ALTER SYSTEM SET effective_cache_size = '128MB';`
- `SELECT pg_reload_conf();`

These are **intentionally** poor for many workloads. They persist in **`postgresql.auto.conf`**. To undo in a lab container, either remove the container or use `ALTER SYSTEM RESET ...` for each parameter and reload again.

### Problem 4 — Idle transaction / locks

**Table:** `lock_test` — small table with a few rows.

SQL cannot keep a transaction open after the script ends. The script’s block comment describes opening **another session** (e.g. **psycopg2**): `BEGIN;` + `UPDATE lock_test ...;` then leave the session **idle in transaction**. Trainees identify the backend in **`pg_stat_activity`** and use **`pg_terminate_backend(pid)`** (or fix the app).

### Verification reference (from script)

| Issue | What to check |
|------|----------------|
| **1 — Missing indexes** | `pg_stat_user_tables` / `EXPLAIN` on filter queries; non-PK index count on `transactions` |
| **2 — Bloat** | `n_dead_tup` for `logs` in `pg_stat_user_tables`; drop after `VACUUM` |
| **3 — Config** | `current_setting('shared_buffers')`, `work_mem`, `random_page_cost`, `effective_cache_size` |
| **4 — Idle txn** | `pg_stat_activity` where `state = 'idle in transaction'` and query references `lock_test` |

### End state

`ANALYZE` on `transactions`, `logs`, and `lock_test`; config is **altered** until reset.

---

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| `The '<' operator is reserved for future use` | PowerShell — use **pipe** or `cmd /c` (see above) |
| `open //./pipe/dockerDesktopLinuxEngine` | Docker engine not running — start **Docker Desktop** |
| Notice: table does not exist, skipping | First run of `DROP IF EXISTS` — **safe** |
| `ALTER SYSTEM` / permission errors | Connect as **superuser** (default `postgres` in the image is fine) |
| Performance seed “ruined” my local Postgres | **ALTER SYSTEM** persisted — use a **dedicated** container or `ALTER SYSTEM RESET` each setting |

---

## Order of execution

Scripts are **independent** for `orders` and `user_orders`. You can load them in any order.

`seed_performance_diagnosis.sql` **changes global server settings**; run it in an isolated instance or **last** in a disposable container.

---

## License / usage

Internal training / lab use. Adjust row counts and GUCs if your environment policy forbids `ALTER SYSTEM` on shared clusters.
