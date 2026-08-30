"""The one HR database both servers read.

Nothing in here is an anti-pattern. The bad and good servers are given the
*same* data and the *same* queries; every difference the demo measures comes
from how the tools are shaped, described, and guarded -- never from the data.

The seed is deterministic (fixed PRNG seed, fixed offsets from "now"), so a
question has the same right answer on every machine, at every hour.

The domain is deliberately mundane: employees, the departments they sit in, and
the semi-monthly paycheck each of them is issued. Payroll is a good teacher
because it fails in ways everyone recognises -- a budget ceiling, a rate table
nobody published, a lock held during month-end close -- and because payroll
records are exactly the kind of data you must never let a model delete.
"""

from __future__ import annotations

import random
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hr import traces

DB = Path(__file__).parent.parent / "hr.db"
SEED = 20260826

# Paychecks are issued semi-monthly, and the seed lays down 14 cycles per
# employee -- about seven months of history. Every "success rate" in the demo
# is computed over this window, and every tool that reports one says so.
CYCLE_DAYS = 15
CYCLES_SEEDED = 14
STATS_DAYS = 365
STATS_LABEL = "12mo"

# Payroll traces are purged after a year. Exhibit 3 hinges on this: the live
# trace index CANNOT answer "has this happened before", because the precedent
# is 14 months old. Only the case files go back that far.
TRACE_RETENTION_DAYS = 365

SCHEMA = """
CREATE TABLE departments (
    id INTEGER PRIMARY KEY, name TEXT UNIQUE, cost_center TEXT,
    location TEXT, head TEXT
);
CREATE TABLE employees (
    id INTEGER PRIMARY KEY, name TEXT UNIQUE, email TEXT, title TEXT,
    department_id INTEGER, manager_id INTEGER, hired_at TEXT,
    status TEXT, salary INTEGER, payroll_hold INTEGER
);
CREATE TABLE paychecks (
    id INTEGER PRIMARY KEY, employee_id INTEGER, period TEXT,
    issued_at TEXT, settled_at TEXT, status TEXT, net_pay INTEGER,
    error_code INTEGER, trace TEXT
);
CREATE TABLE org_changes (
    id INTEGER PRIMARY KEY, area TEXT, kind TEXT,
    effective_at TEXT, changed_by TEXT, notes TEXT
);
CREATE TABLE hr_cases (
    id INTEGER PRIMARY KEY, title TEXT, opened_at TEXT, closed_at TEXT,
    severity TEXT, resolution TEXT
);
"""

DEPARTMENTS = [
    (1, "Engineering", "CC-4100", "Pune", "Sam Alvarez"),
    (2, "Finance", "CC-2200", "London", "Rosa Delgado"),
    (3, "Sales", "CC-3300", "New York", "Amara Osei"),
    (4, "People Ops", "CC-5500", "London", "Hannah Weiss"),
]

# name, title, department_id, manager_id, salary, and the payroll success rate
# used to synthesise paycheck history.
EMPLOYEES = [
    ("Priya Raman", "Staff Engineer", 1, 3, 187_000, 0.85),
    ("Deniz Okonkwo", "Payroll Analyst", 2, 8, 96_000, 0.99),
    ("Sam Alvarez", "Engineering Manager", 1, None, 211_000, 1.00),
    ("Wei Zhang", "Data Scientist", 1, 3, 164_000, 0.62),
    ("Amara Osei", "Sales Director", 3, None, 198_000, 0.98),
    ("Tomas Novak", "Recruiter", 4, 10, 88_000, 1.00),
    ("Yuki Tanaka", "Product Designer", 1, 3, 152_000, 1.00),
    ("Rosa Delgado", "Controller", 2, None, 205_000, 1.00),
    ("Marcus Bell", "Field Sales Rep", 3, 5, 104_000, 0.12),
    ("Hannah Weiss", "People Ops Partner", 4, None, 143_000, 0.97),
]

TABLES = ("employees", "paychecks", "org_changes", "hr_cases", "departments")


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def email_for(name: str) -> str:
    first, _, last = name.partition(" ")
    return f"{first}.{last}@acme.com".lower()


def last_pay_close() -> datetime:
    """02:00 UTC on the most recent payroll close (the 1st or the 16th), in the past."""
    n = now()
    first_this = n.replace(day=1, hour=2, minute=0, second=0, microsecond=0)
    prev_month_end = first_this - timedelta(days=1)
    first_prev = prev_month_end.replace(day=1, hour=2, minute=0, second=0, microsecond=0)
    candidates = [first_prev, first_prev.replace(day=16), first_this, first_this.replace(day=16)]
    return max(c for c in candidates if c < n)


def period_label(dt: datetime) -> str:
    """The pay period a date falls in, e.g. '2026-08-B' for the second half."""
    return f"{dt:%Y-%m}-{'B' if dt.day > 15 else 'A'}"


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


# --------------------------------------------------------------------------
# seeding
# --------------------------------------------------------------------------


def reset_db() -> None:
    rnd = random.Random(SEED)
    DB.unlink(missing_ok=True)
    Path(str(DB) + "-wal").unlink(missing_ok=True)
    Path(str(DB) + "-shm").unlink(missing_ok=True)

    with connect() as db:
        db.executescript(SCHEMA)
        db.executemany("INSERT INTO departments VALUES (?,?,?,?,?)", DEPARTMENTS)

        hired = now() - timedelta(days=2200)
        for eid, (name, title, dept, mgr, salary, _rate) in enumerate(EMPLOYEES, start=1):
            db.execute(
                "INSERT INTO employees VALUES (?,?,?,?,?,?,?,?,?,0)",
                (
                    eid,
                    name,
                    email_for(name),
                    title,
                    dept,
                    mgr,
                    iso(hired + timedelta(days=eid * 137)),
                    "active",
                    salary,
                ),
            )

        _seed_paychecks(db, rnd)
        _seed_org_changes(db)
        _seed_hr_cases(db)


def _seed_paychecks(db: sqlite3.Connection, rnd: random.Random) -> None:
    """14 semi-monthly cycles each, plus the three paychecks the demo depends on."""
    pc_id = 4000
    fail_close = last_pay_close()

    for eid, (name, _title, _dept, _mgr, salary, rate) in enumerate(EMPLOYEES, start=1):
        for k in range(CYCLES_SEEDED, 0, -1):
            pc_id += 1
            issued = now() - timedelta(days=k * CYCLE_DAYS) + timedelta(minutes=eid)
            ok = rnd.random() < rate
            dur = timedelta(seconds=rnd.randint(20, 900))
            body = traces.GENERIC_OK_TRACE.format(
                name=name, n=rnd.randint(4, 90), ms=rnd.randint(50, 40000)
            )
            if name == "Priya Raman":
                body = traces.PAYRUN_OK_TRACE.format(date=issued.date().isoformat())
            elif name == "Wei Zhang" and not ok:
                body = traces.RETRO_FAIL_TRACE
            elif name == "Marcus Bell":
                body = traces.monster_trace(rnd) if not ok else body
            db.execute(
                "INSERT INTO paychecks VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    pc_id,
                    eid,
                    period_label(issued),
                    iso(issued),
                    iso(issued + dur),
                    "paid" if ok else "failed",
                    round(salary / 24) if ok else 0,
                    0 if ok else rnd.choice([1, 2, 137]),
                    body,
                ),
            )

    # --- the three paychecks every exhibit points at, appended last so they are newest
    ids = {name: eid for eid, (name, *_r) in enumerate(EMPLOYEES, start=1)}

    # exhibit 1: last cycle's failure for Priya Raman, error 28, cost-center budget
    db.execute(
        "INSERT INTO paychecks VALUES (?,?,?,?,?,?,?,?,?)",
        (
            9001,
            ids["Priya Raman"],
            period_label(fail_close),
            iso(fail_close),
            iso(fail_close + timedelta(minutes=22, seconds=42)),
            "failed",
            0,
            28,
            traces.BUDGET_FAIL_TRACE,
        ),
    )
    # exhibit 2: the 600k-char commission trace for Marcus Bell
    db.execute(
        "INSERT INTO paychecks VALUES (?,?,?,?,?,?,?,?,?)",
        (
            9002,
            ids["Marcus Bell"],
            period_label(now() - timedelta(days=1)),
            iso(now() - timedelta(days=1)),
            iso(now() - timedelta(days=1) + timedelta(minutes=10)),
            "failed",
            0,
            137,
            traces.monster_trace(random.Random(SEED + 1)),
        ),
    )
    # exhibit 4: keeps Deniz Okonkwo unambiguously healthy for exhibit 7
    db.execute(
        "INSERT INTO paychecks VALUES (?,?,?,?,?,?,?,?,?)",
        (
            9003,
            ids["Deniz Okonkwo"],
            period_label(now() - timedelta(days=2)),
            iso(now() - timedelta(days=2)),
            iso(now() - timedelta(days=2) + timedelta(minutes=1)),
            "paid",
            4000,
            0,
            traces.GENERIC_OK_TRACE.format(name="Deniz Okonkwo", n=12, ms=934),
        ),
    )


def _seed_org_changes(db: sqlite3.Connection) -> None:
    fail_close = last_pay_close()
    rows = [
        # THE causal link for exhibit 1: effective 2h before the payroll close.
        (
            1,
            "Engineering",
            "reorg",
            iso(fail_close - timedelta(hours=2)),
            "Sam Alvarez",
            "Reorg 4.2: move the Platform team into cost center CC-4100 for FY27. "
            "Headcount +6. No budget change requested.",
        ),
        (
            2,
            "Company",
            "calendar",
            iso(fail_close - timedelta(days=1, hours=6)),
            "Rosa Delgado",
            "Routine semi-monthly payroll calendar publish.",
        ),
        (
            3,
            "Sales",
            "comp-plan",
            iso(now() - timedelta(days=2)),
            "Amara Osei",
            "Publish the 2026H2 commission rate tables for all territories.",
        ),
        (
            4,
            "Finance",
            "policy",
            iso(now() - timedelta(days=4)),
            "Rosa Delgado",
            "Direct-deposit retry policy: 3 attempts -> 5.",
        ),
        (
            5,
            "People Ops",
            "benefits",
            iso(now() - timedelta(days=6)),
            "Hannah Weiss",
            "Open enrolment window opens for FY27.",
        ),
    ]
    db.executemany("INSERT INTO org_changes VALUES (?,?,?,?,?,?)", rows)


def _seed_hr_cases(db: sqlite3.Connection) -> None:
    """Closed case files. Exhibit 3 hinges on these being the ONLY place prior art
    lives -- payroll traces are purged after 12 months."""
    rows = [
        (
            1,
            "Payroll failed after a cost-center move filled CC-4100",
            iso(now() - timedelta(days=417)),
            iso(now() - timedelta(days=416)),
            "SEV2",
            "Someone moved a team into cost center CC-4100 without raising its 200,000 "
            "monthly payroll budget. Two cycles later the payroll engine hit the ceiling "
            "and exited 28 with 'cost center budget exceeded'. Fix: budget raised to "
            "500,000 and a pre-flight capacity check added to the pay run. Action item "
            "never completed: alert when a cost center exceeds 80% of its committed "
            "budget. Cost-center moves must be reviewed against the budget -- this WILL "
            "recur otherwise.",
        ),
        (
            2,
            "Retro adjustments deadlock during month-end close",
            iso(now() - timedelta(days=190)),
            iso(now() - timedelta(days=189)),
            "SEV3",
            "The retro-adjustment pass and the general-ledger export contend on the same "
            "period locks. The pay run rolls back with 'deadlock detected'. Mitigation: "
            "stagger the two close windows.",
        ),
        (
            3,
            "Commission rate-table rollout broke EMEA payouts",
            iso(now() - timedelta(days=61)),
            iso(now() - timedelta(days=60)),
            "SEV3",
            "Territories were moved onto the 2026H2 rate tables but EMEA-3 was missed. "
            "Reps in that territory could not be priced and their pay runs aborted. Fix: "
            "publish the rate table for every territory before flipping any of them.",
        ),
        (
            4,
            "Benefits deduction silently skipped a dependent tier",
            iso(now() - timedelta(days=300)),
            iso(now() - timedelta(days=299)),
            "SEV2",
            "Open enrolment applied the employee-only tier but not employee+family. The "
            "under-deduction went unnoticed for two cycles and had to be clawed back. "
            "Fix: enumerate every tier explicitly.",
        ),
    ]
    db.executemany("INSERT INTO hr_cases VALUES (?,?,?,?,?,?)", rows)


# --------------------------------------------------------------------------
# plain queries -- shared by both servers, so tool *shape* is the only variable
# --------------------------------------------------------------------------


def q(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute(sql, args).fetchall()


def row_counts() -> dict[str, int]:
    """Powers the exhibit-5 'database state' panel."""
    return {t: q(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in TABLES}


def table_rows(limit: int | None = None, max_text: int = 180) -> list[dict]:
    """Every row of every demo table, read-only, for the Database tab.

    `max_text` truncates long text *per cell* -- and it has to. One paycheck
    trace is 700k characters, so a genuinely untruncated dump would ship
    megabytes to the browser to render a column nobody can read anyway. The
    row COUNT is complete; the cell contents are elided with a trailing "…".
    """
    out = []
    counts = row_counts()
    for table in TABLES:
        direction = "DESC" if table == "paychecks" else "ASC"
        sql = f"SELECT * FROM {table} ORDER BY id {direction}"
        rows = q(f"{sql} LIMIT ?", (limit,)) if limit else q(sql)
        columns = list(rows[0].keys()) if rows else []
        compact_rows = []
        for row in rows:
            values = []
            for value in row:
                if isinstance(value, str) and len(value) > max_text:
                    value = value[:max_text].rstrip() + "…"
                values.append(value)
            compact_rows.append(values)
        out.append(
            {"name": table, "columns": columns, "rows": compact_rows, "total": counts[table]}
        )
    return out


def all_employees() -> list[sqlite3.Row]:
    return q("SELECT * FROM employees ORDER BY id")


def employee_by_name(name: str) -> sqlite3.Row | None:
    rows = q("SELECT * FROM employees WHERE name = ?", (name,))
    return rows[0] if rows else None


def paychecks_for_employee(employee_id: int, limit: int = 20) -> list[sqlite3.Row]:
    return q(
        "SELECT id, employee_id, period, issued_at, settled_at, status, net_pay, error_code "
        "FROM paychecks WHERE employee_id = ? ORDER BY issued_at DESC LIMIT ?",
        (employee_id, limit),
    )


def paycheck_by_id(paycheck_id: int) -> sqlite3.Row | None:
    rows = q("SELECT * FROM paychecks WHERE id = ?", (paycheck_id,))
    return rows[0] if rows else None


def recent_failures(days: int = 30) -> list[sqlite3.Row]:
    cutoff = iso(now() - timedelta(days=days))
    return q(
        "SELECT p.*, e.name AS employee_name FROM paychecks p "
        "JOIN employees e ON e.id = p.employee_id "
        "WHERE p.status = 'failed' AND p.issued_at >= ? ORDER BY p.issued_at DESC",
        (cutoff,),
    )


def org_changes_before(when_iso: str, hours: int = 72) -> list[sqlite3.Row]:
    start = iso(datetime.fromisoformat(when_iso.replace("Z", "+00:00")) - timedelta(hours=hours))
    return q(
        "SELECT * FROM org_changes WHERE effective_at BETWEEN ? AND ? ORDER BY effective_at DESC",
        (start, when_iso),
    )


STOPWORDS = {"the", "and", "for", "was", "has", "have", "this", "that", "with", "what", "did"}


def _terms(query: str) -> list[str]:
    """Words worth matching on. A single LIKE over the raw query matches nothing
    for a natural phrase like 'has the budget problem happened before', which
    turns every search into an empty result and the model into a flailing mess."""
    words = [w for w in re.split(r"[^a-z0-9]+", query.lower()) if len(w) > 2]
    return [w for w in words if w not in STOPWORDS] or words


def _scored(rows: list[sqlite3.Row], fields: tuple[str, ...], query: str) -> list[sqlite3.Row]:
    """Rows containing at least one query term, best match first."""
    terms = _terms(query)
    if not terms:
        return []
    scored = []
    for row in rows:
        hay = " ".join(str(row[f]).lower() for f in fields)
        hits = sum(1 for t in terms if t in hay)
        if hits:
            scored.append((hits, row))
    scored.sort(key=lambda pair: -pair[0])
    return [row for _hits, row in scored]


def search_hr_cases(term: str) -> list[sqlite3.Row]:
    rows = q("SELECT * FROM hr_cases ORDER BY opened_at DESC")
    return _scored(rows, ("title", "resolution"), term)


def search_traces(term: str) -> list[dict]:
    """Paychecks whose trace matches `term`. METADATA ONLY -- never trace bodies.

    The trace column is read to score the match and then dropped. Returning it
    would make this tool unbounded: one monster trace is 600k chars, and a
    caller that serialises whole rows would emit millions of tokens for one
    search.
    """
    cutoff = iso(now() - timedelta(days=TRACE_RETENTION_DAYS))
    rows = q(
        "SELECT p.id, e.name AS employee_name, p.period, p.issued_at, p.status, p.trace "
        "FROM paychecks p JOIN employees e ON e.id = p.employee_id "
        "WHERE p.issued_at >= ? ORDER BY p.issued_at DESC",
        (cutoff,),
    )
    hits = _scored(rows, ("trace", "employee_name"), term)[:20]
    return [
        {
            "id": r["id"],
            "employee_name": r["employee_name"],
            "period": r["period"],
            "issued_at": r["issued_at"],
            "status": r["status"],
            "trace_lines": len(r["trace"].splitlines()),
        }
        for r in hits
    ]


def payroll_stats(employee_id: int) -> dict:
    cutoff = iso(now() - timedelta(days=STATS_DAYS))
    rows = q(
        "SELECT status, COUNT(*) AS n FROM paychecks WHERE employee_id = ? AND issued_at >= ? "
        "GROUP BY status",
        (employee_id, cutoff),
    )
    counts = {r["status"]: r["n"] for r in rows}
    ok, bad = counts.get("paid", 0), counts.get("failed", 0)
    total = ok + bad
    return {"paid": ok, "failed": bad, "total": total, "rate": (ok / total) if total else 0.0}


if __name__ == "__main__":
    reset_db()
    print("seeded", row_counts())
