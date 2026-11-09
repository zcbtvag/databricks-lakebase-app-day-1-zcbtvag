"""Week 1 homework: minimal ticketing app.

A tiny Flask app to start from — list tickets and create new ones.
In-memory storage for now; swap in Lakebase later if the homework needs it.
"""

import os
import uuid

from flask import Flask, redirect, render_template_string, request, url_for

app = Flask(__name__)

# Simple in-memory store, seeded with a couple of example tickets.
TICKETS = [
    {"id": str(uuid.uuid4())[:8], "title": "Login page 500 error", "status": "open"},
    {"id": str(uuid.uuid4())[:8], "title": "Add dark mode toggle", "status": "closed"},
]

PAGE = """
<!doctype html>
<html>
<head><title>WK1 Ticketing</title>
<style>
  body { font-family: sans-serif; max-width: 640px; margin: 2rem auto; }
  h1 { font-size: 1.4rem; }
  li { margin: 0.4rem 0; }
  .status { color: #666; font-size: 0.9rem; }
  form { margin-top: 1.5rem; }
  input, select, button { padding: 0.4rem; font-size: 1rem; }
</style>
</head>
<body>
<h1>WK1 Ticketing</h1>
<ul>
  {% for t in tickets %}
    <li><strong>{{ t.title }}</strong> <span class="status">[{{ t.status }}] {{ t.id }}</span></li>
  {% else %}
    <li>No tickets yet.</li>
  {% endfor %}
</ul>
<form method="post" action="{{ url_for('create_ticket') }}">
  <input name="title" placeholder="Ticket title" required>
  <select name="status">
    <option value="open">open</option>
    <option value="closed">closed</option>
  </select>
  <button type="submit">Create ticket</button>
</form>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE, tickets=TICKETS)


@app.route("/tickets", methods=["POST"])
def create_ticket():
    title = request.form.get("title", "").strip()
    status = request.form.get("status", "open")
    if title:
        TICKETS.append({"id": str(uuid.uuid4())[:8], "title": title, "status": status})
    return redirect(url_for("index"))


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    # Databricks Apps routes traffic to the port in DATABRICKS_APP_PORT (default 8000).
    port = int(os.environ.get("DATABRICKS_APP_PORT", 8000))
    app.run(host="0.0.0.0", port=port)
