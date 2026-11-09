"""Week 1 homework: Lakebase-backed ticketing app.

Features (all read/write Lakebase, no in-memory data):
  - View all support tickets            GET  /
  - View a ticket and its messages      GET  /tickets/<id>
  - Create a new ticket                 POST /tickets
  - Add a message to a ticket           POST /tickets/<id>/messages
  - Update a ticket's status            POST /tickets/<id>/status
  - Health check (deploy probe)         GET  /health

The identity of the logged-in user comes from the X-Forwarded-Email header,
which the Databricks Apps runtime sets for authenticated visitors.
"""

import os

from flask import Flask, abort, redirect, render_template, request, url_for

import db

app = Flask(__name__)

STATUSES = ("open", "in_progress", "resolved")


def current_user() -> str:
    """Best-effort identity of the visitor (set by the Apps runtime)."""
    return request.headers.get("X-Forwarded-Email") or "anonymous"


@app.route("/")
def index():
    tickets = db.run_query(
        f"""
        SELECT t.ticket_id, t.title, t.status, t.created_by, t.created_at,
               count(m.message_id) AS message_count
        FROM {db.SCHEMA}.tickets t
        LEFT JOIN {db.SCHEMA}.ticket_messages m ON m.ticket_id = t.ticket_id
        GROUP BY t.ticket_id
        ORDER BY t.created_at DESC
        """
    )
    return render_template("index.html", tickets=tickets, statuses=STATUSES)


@app.route("/tickets/<int:ticket_id>")
def ticket_detail(ticket_id: int):
    rows = db.run_query(
        f"SELECT ticket_id, title, status, created_by, created_at "
        f"FROM {db.SCHEMA}.tickets WHERE ticket_id = %s",
        (ticket_id,),
    )
    if not rows:
        abort(404)
    ticket = rows[0]
    messages = db.run_query(
        f"SELECT message_id, message_text, author, created_at "
        f"FROM {db.SCHEMA}.ticket_messages WHERE ticket_id = %s "
        f"ORDER BY created_at",
        (ticket_id,),
    )
    return render_template(
        "ticket.html", ticket=ticket, messages=messages, statuses=STATUSES
    )


@app.route("/tickets", methods=["POST"])
def create_ticket():
    title = request.form.get("title", "").strip()
    if title:
        db.run_write(
            f"INSERT INTO {db.SCHEMA}.tickets (title, created_by) VALUES (%s, %s)",
            (title, current_user()),
        )
    return redirect(url_for("index"))


@app.route("/tickets/<int:ticket_id>/messages", methods=["POST"])
def add_message(ticket_id: int):
    text = request.form.get("message_text", "").strip()
    if text:
        db.run_write(
            f"INSERT INTO {db.SCHEMA}.ticket_messages (ticket_id, message_text, author) "
            "VALUES (%s, %s, %s)",
            (ticket_id, text, current_user()),
        )
    return redirect(url_for("ticket_detail", ticket_id=ticket_id))


@app.route("/tickets/<int:ticket_id>/status", methods=["POST"])
def update_status(ticket_id: int):
    status = request.form.get("status", "")
    if status in STATUSES:
        db.run_write(
            f"UPDATE {db.SCHEMA}.tickets SET status = %s WHERE ticket_id = %s",
            (status, ticket_id),
        )
    return redirect(url_for("ticket_detail", ticket_id=ticket_id))


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    # Create schema/tables and seed sample data before serving traffic.
    # Idempotent: safe on every restart, no-ops when data already exists.
    db.ensure_schema()

    # Databricks Apps routes traffic to the port in DATABRICKS_APP_PORT (default 8000).
    port = int(os.environ.get("DATABRICKS_APP_PORT", 8000))
    app.run(host="0.0.0.0", port=port)
