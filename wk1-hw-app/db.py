"""Lakebase connection helpers for the WK1 ticketing app.

How the app authenticates to Lakebase (no static passwords, no secrets):

1. The app has a Lakebase Autoscaling *resource* attached (key "postgres").
   When that resource is attached, the platform creates a Postgres role for the
   app's service principal and grants it CONNECT + CREATE on the database.
2. At deploy time the platform injects connection variables into the runtime:
   PGHOST, PGPORT, PGDATABASE, PGUSER (= the service principal's client ID, and
   the name of its Postgres role), PGSSLMODE.
3. app.yaml maps the resource to LAKEBASE_ENDPOINT via `valueFrom: postgres`.
   That is the resource path (projects/.../branches/.../endpoints/...), which
   the Databricks SDK needs to mint a short-lived OAuth token (~1h expiry).
4. Every connection mints a fresh token, so tokens never need rotating.
"""

import os
from contextlib import contextmanager

import psycopg
from databricks.sdk import WorkspaceClient

# Postgres schema that holds this app's tables.
SCHEMA = "wk1_hw"

LAKEBASE_ENDPOINT = os.environ.get("LAKEBASE_ENDPOINT", "")

_w: WorkspaceClient | None = None


def workspace_client() -> WorkspaceClient:
    """Lazily create one WorkspaceClient per process (uses the app's SP identity)."""
    global _w
    if _w is None:
        _w = WorkspaceClient()
    return _w


@contextmanager
def get_connection():
    """Yield a psycopg3 connection with a freshly minted OAuth token.

    A new connection (and token) per use is intentionally simple; the pool+
    rotation pattern only pays off at high concurrency.
    """
    missing = [
        name
        for name in ("PGHOST", "PGDATABASE", "PGUSER", "LAKEBASE_ENDPOINT")
        if not os.environ.get(name)
    ]
    if missing:
        raise RuntimeError(
            "Lakebase env vars missing: ", ", ".join(missing),
            ". Attach the Lakebase resource (postgres) and redeploy.",
        )

    cred = workspace_client().postgres.generate_database_credential(
        endpoint=LAKEBASE_ENDPOINT
    )
    conn = psycopg.connect(
        host=os.environ["PGHOST"],
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=cred.token,
        sslmode=os.environ.get("PGSSLMODE", "require"),
    )
    try:
        yield conn
    finally:
        conn.close()


def run_query(sql: str, params: tuple | dict | None = None) -> list[dict]:
    """Run a read query and return rows as a list of dicts."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc.name for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def run_write(sql: str, params: tuple | dict | None = None) -> int:
    """Run an INSERT/UPDATE/DELETE, commit, and return the affected row count."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            affected = cur.rowcount
        conn.commit()
        return affected


# ---------------------------------------------------------------------------
# One-time bootstrap: schema, tables, and sample data.
# Safe to run on every startup: IF NOT EXISTS + seed only when empty.
# ---------------------------------------------------------------------------

_DDL = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA};

CREATE TABLE IF NOT EXISTS {SCHEMA}.tickets (
    ticket_id  BIGSERIAL PRIMARY KEY,
    title      TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open'
               CHECK (status IN ('open', 'in_progress', 'resolved')),
    created_by TEXT NOT NULL DEFAULT 'anonymous',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.ticket_messages (
    message_id   BIGSERIAL PRIMARY KEY,
    ticket_id    BIGINT NOT NULL
                 REFERENCES {SCHEMA}.tickets (ticket_id) ON DELETE CASCADE,
    message_text TEXT NOT NULL,
    author       TEXT NOT NULL DEFAULT 'anonymous',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket_id
    ON {SCHEMA}.ticket_messages (ticket_id);
"""

_SAMPLE_TICKETS = [
    ("Cannot log in with single sign-on", "open", "alice@example.com"),
    ("Dashboard shows stale data after refresh", "in_progress", "bob@example.com"),
    ("CSV export fails for large reports", "resolved", "carol@example.com"),
]

_SAMPLE_MESSAGES = [
    [
        ("I get redirected back to the login page every time I use SSO.", "alice@example.com"),
        ("Thanks for the report — we're looking into the SSO certificate rotation.", "support-team"),
    ],
    [
        ("Numbers in the dashboard differ from the source report by about a day.", "bob@example.com"),
        ("Reproduced — the refresh job is running on a stale cache. Fix in progress.", "support-team"),
    ],
    [
        ("Exporting a report with more than 10k rows fails with a timeout.", "carol@example.com"),
        ("Fixed in release 2.4.1 — the export now streams instead of buffering.", "support-team"),
    ],
]


def ensure_schema() -> None:
    """Create the schema/tables if needed and seed sample data when empty."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_DDL)
            cur.execute(f"SELECT count(*) FROM {SCHEMA}.tickets")
            (count,) = cur.fetchone()
            if count == 0:
                for idx, (title, status, author) in enumerate(_SAMPLE_TICKETS):
                    cur.execute(
                        f"INSERT INTO {SCHEMA}.tickets (title, status, created_by) "
                        "VALUES (%s, %s, %s) RETURNING ticket_id",
                        (title, status, author),
                    )
                    (ticket_id,) = cur.fetchone()
                    for text, author_name in _SAMPLE_MESSAGES[idx]:
                        cur.execute(
                            f"INSERT INTO {SCHEMA}.ticket_messages "
                            "(ticket_id, message_text, author) VALUES (%s, %s, %s)",
                            (ticket_id, text, author_name),
                        )
        conn.commit()
