"""Minimal WSGI application for managing shift changes and rotations.

This script implements a small web application using only Python's
standard library. It serves a simple HTML form that allows users to
record shift changes or rotations, store the data in an SQLite
database, compute total hours, and search existing records. No
external dependencies are required.

How to run
----------
Run this script using Python 3. It will start a local HTTP server on
port 8000. Open your browser to `http://localhost:8000/` to access
the form and search page.

```bash
python app.py
```

Files
-----
This script expects two HTML template files in a `templates`
subdirectory:

* `index.html`: form for entering shift changes.
* `search.html`: page for searching the database and displaying
  results.

The templates use Jinja-like placeholders (delimited by `{{` and
`}}`) for dynamic content. Since this script doesn't rely on an
external templating engine, it performs very simple substitutions.
"""

import os
import sqlite3
import sys
from datetime import datetime
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server


TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
DATABASE = os.path.join(os.path.dirname(__file__), "shift.db")


def init_db() -> None:
    """Create the SQLite database and table if they don't exist."""
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS shift_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_name TEXT NOT NULL,
            date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            rotation TEXT NOT NULL,
            total_hours REAL NOT NULL,
            comment TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def compute_total_hours(start_time: str, end_time: str) -> float:
    """Compute the total number of hours between two HH:MM strings."""
    fmt = "%H:%M"
    start = datetime.strptime(start_time, fmt)
    end = datetime.strptime(end_time, fmt)
    if end <= start:
        # Crosses midnight
        end = end.replace(day=end.day + 1)
    delta = end - start
    return round(delta.total_seconds() / 3600.0, 2)


def render_template(template_name: str, context: dict | None = None) -> bytes:
    """Load an HTML template and substitute placeholders.

    Placeholders in the form `{{ key }}` are replaced by the value of
    the corresponding key in the context dictionary. This function does
    not escape HTML; values should therefore be pre-sanitised if they
    originate from user input. Values that are lists of dictionaries
    are handled specially for the search results table.
    """
    path = os.path.join(TEMPLATES_DIR, template_name)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if context is None:
        context = {}
    # Replace simple placeholders
    for key, value in context.items():
        placeholder = f"{{{{ {key} }}}}"
        if not isinstance(value, list):
            content = content.replace(placeholder, str(value))
    # Handle results table separately
    if "results" in context:
        rows_html = ""
        results = context["results"]
        if results:
            for row in results:
                rows_html += (
                    "<tr>"
                    f"<td>{row['employee_name']}</td>"
                    f"<td>{row['date']}</td>"
                    f"<td>{row['start_time']}</td>"
                    f"<td>{row['end_time']}</td>"
                    f"<td>{row['rotation']}</td>"
                    f"<td>{row['total_hours']}</td>"
                    f"<td>{row['comment']}</td>"
                    "</tr>"
                )
            content = content.replace("{{ results_table }}", rows_html)
        else:
            content = content.replace("{{ results_table }}", "<tr><td colspan='7'>Aucun enregistrement trouvé.</td></tr>")
    return content.encode("utf-8")


def parse_post_data(environ) -> dict:
    """Parse POST data from the request body into a dictionary."""
    try:
        request_body_size = int(environ.get("CONTENT_LENGTH", 0))
    except (ValueError, TypeError):
        request_body_size = 0
    request_body = environ["wsgi.input"].read(request_body_size).decode("utf-8")
    return {k: v[0] for k, v in parse_qs(request_body).items()}


def application(environ, start_response):
    """WSGI entry point for handling HTTP requests."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    init_db()

    if path == "/" and method in {"GET", "POST"}:
        if method == "POST":
            form = parse_post_data(environ)
            employee_name = form.get("employee_name", "").strip()
            date = form.get("date", "")
            start_time = form.get("start_time", "")
            end_time = form.get("end_time", "")
            rotation = form.get("rotation", "")
            comment = form.get("comment", "").strip()
            total_hours = compute_total_hours(start_time, end_time)
            # Insert into database
            conn = sqlite3.connect(DATABASE)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO shift_changes (employee_name, date, start_time, end_time, rotation, total_hours, comment)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (employee_name, date, start_time, end_time, rotation, total_hours, comment),
            )
            conn.commit()
            conn.close()
            # Redirect to homepage using 303 See Other
            start_response("303 See Other", [("Location", "/")])
            return [b""]
        # GET request: serve the form
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [render_template("index.html")]

    elif path == "/search" and method in {"GET", "POST"}:
        results: list[dict] | None = None
        if method == "POST":
            form = parse_post_data(environ)
            employee_name = form.get("employee_name", "").strip()
            date = form.get("date", "").strip()
            conn = sqlite3.connect(DATABASE)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            query = "SELECT * FROM shift_changes WHERE 1=1"
            params = []
            if employee_name:
                query += " AND employee_name LIKE ?"
                params.append(f"%{employee_name}%")
            if date:
                query += " AND date = ?"
                params.append(date)
            query += " ORDER BY date DESC, start_time ASC"
            cur.execute(query, params)
            results = [dict(row) for row in cur.fetchall()]
            conn.close()
        elif method == "GET":
            # On GET request, don't perform a query; results is None
            results = None
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [render_template("search.html", {"results": results or []})]

    else:
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"404 Not Found"]


if __name__ == "__main__":
    # Only run the server when executed directly
    port = 8000
    with make_server("", port, application) as httpd:
        print(f"Serving on port {port}. Visit http://localhost:{port}/ to access the application.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer shutting down.")