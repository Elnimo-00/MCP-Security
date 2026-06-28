"""
Vulnerable MCP server — intentionally insecure for educational purposes.

Vulnerabilities demonstrated:
  1. Sensitive information disclosure (logs leak API key in errors)
  2. Broken authorization / IDOR   (document resource)
  3. SQL injection                 (price resource template)
  4. Command injection             (execute_server_command tool)
  5. Server-Side Request Forgery   (fetch_price_data tool)

Run:
  python src/vulnerable_server.py

Starts:
  - Internal "Quantity API"  on port 8001
  - MCP server               on port 8000
"""

import os
import sqlite3
import subprocess
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from fastmcp import FastMCP

os.makedirs("data", exist_ok=True)
os.makedirs("results", exist_ok=True)

DB_PATH = "data/shop.db"
LOG_PATH = "results/server.log"

QUANTITY_API_KEY = "7f1db571858da4cf0af43645812e1997"
QUANTITY_API_PORT = 8001

# ── Database ───────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id       INTEGER PRIMARY KEY,
            name     TEXT UNIQUE,
            price    REAL,
            quantity INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id      INTEGER PRIMARY KEY,
            owner   TEXT,
            content TEXT
        )
    """)
    c.executemany(
        "INSERT OR IGNORE INTO items (id, name, price, quantity) VALUES (?, ?, ?, ?)",
        [
            (1, "banana", 0.99, 50),
            (2, "apple",  1.49, 30),
            (3, "orange", 0.79, 75),
        ],
    )
    c.executemany(
        "INSERT OR IGNORE INTO documents (id, owner, content) VALUES (?, ?, ?)",
        [
            (1, "alice", "Alice's secret project proposal"),
            (2, "bob",   "Bob's confidential budget plan"),
            (3, "carol", "Carol's private research notes"),
        ],
    )
    conn.commit()
    conn.close()


# ── Logging ────────────────────────────────────────────────────────────────────

log_entries: list[str] = [
    "2025-05-12 14:56:59.941202: MCP server starting...",
    "2025-05-12 14:57:00.183027: Startup complete.",
    "2025-05-12 14:58:38.832220: Getting price for item 'banana'",
    "2025-05-12 14:58:57.657254: Executing server command 'date'",
    "2025-05-12 14:59:15.741989: Getting price for item 'apple'",
    "2025-05-12 15:02:48.047280: Error fetching item quantity for item 'watremelon': 'NoneType' object is not subscriptable",
    "2025-05-13 08:48:54.519100: Getting all items",
]


def server_log(msg: str):
    entry = f"{datetime.now()}: {msg}"
    log_entries.append(entry)
    with open(LOG_PATH, "a") as f:
        f.write(entry + "\n")


# ── Internal Quantity API (HTTP on port 8001) ──────────────────────────────────

class QuantityAPIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        key = self.headers.get("X-Api-Key", "")
        if key != QUANTITY_API_KEY:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return

        item = self.path.rstrip("/").split("/")[-1]
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT quantity FROM items WHERE name = ?", (item,)
        ).fetchone()
        conn.close()

        if row:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(f'{{"quantity": {row[0]}}}'.encode())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "item not found"}')

    def log_message(self, *_):
        pass


def _run_quantity_api():
    HTTPServer(("0.0.0.0", QUANTITY_API_PORT), QuantityAPIHandler).serve_forever()


# ── MCP Server ─────────────────────────────────────────────────────────────────

mcp = FastMCP("Vulnerable Shop Server")


# 1. SENSITIVE INFORMATION DISCLOSURE — logs expose internal errors and API keys
@mcp.resource("resource://logs")
def get_logs() -> str:
    """Provide the MCP server logs."""
    return "\n".join(log_entries)


@mcp.resource("resource://items")
def get_items() -> str:
    """Fetch all available items."""
    server_log("Getting all items")
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT name FROM items").fetchall()
    conn.close()
    return ", ".join(r[0] for r in rows)


# Verbose error leaks the API key in the exception message
@mcp.resource("quantity://{item}")
def get_quantity(item: str) -> str:
    """Fetch item quantity from quantity API."""
    server_log(f"Getting quantity for item '{item}'")
    api_url = f"http://127.0.0.1:{QUANTITY_API_PORT}/api/item/{item}"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "MCP Server 1.0.0",
        "X-Api-Key": QUANTITY_API_KEY,
    }
    try:
        resp = requests.get(api_url, headers=headers, timeout=5)
        if resp.status_code == 200:
            return str(resp.json()["quantity"])
        # Intentionally verbose: leaks API key
        raise Exception(
            f"Quantity API Error: Requests details: '{api_url}' {headers}"
        )
    except requests.RequestException as e:
        server_log(f"Error fetching item quantity for item '{item}': {e}")
        raise Exception(
            f"Quantity API Error: Requests details: '{api_url}' {headers}"
        )


# 3. SQL INJECTION — item parameter concatenated directly into query
@mcp.resource("price://{item}")
def get_price(item: str) -> str:
    """Fetch item price from price database."""
    server_log(f"Getting price for item '{item}'")
    try:
        conn = sqlite3.connect(DB_PATH)
        query = f"SELECT price FROM items WHERE name = '{item}'"  # vulnerable
        row = conn.execute(query).fetchone()
        conn.close()
        if row:
            return str(row[0])
        raise Exception("Price API Error")
    except sqlite3.Error:
        raise Exception("Price API Error")


# 2. BROKEN AUTHORIZATION / IDOR — no ownership check
@mcp.resource("document://{doc_id}")
def get_document(doc_id: str) -> str:
    """Retrieve a document from cloud storage by its ID."""
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT content FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        conn.close()
        if row:
            return row[0]
        raise Exception("Document not found")
    except sqlite3.Error as e:
        raise Exception(f"Storage error: {e}")


# 4. COMMAND INJECTION — substring allowlist check + shell=True
@mcp.tool()
def execute_server_command(command: str) -> str:
    """
    Execute a safe command on the server.
    The command is limited to 'date', 'whoami', and 'uptime'.
    """
    server_log(f"Executing server command '{command}'")
    allowed = ["date", "whoami", "uptime"]
    # Vulnerable: substring match instead of exact match
    if not any(cmd in command for cmd in allowed):
        raise Exception("Invalid Command")
    # Vulnerable: shell=True allows ; | && injection
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout.strip()


# 5. SSRF — fetches any caller-supplied URL without validation
@mcp.tool()
def fetch_price_data(url: str) -> str:
    """Fetch price data from an external URL."""
    try:
        requests.get(url, timeout=5)
        return "Success"
    except Exception as e:
        return f"Failed: {e}"


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    server_log("MCP server starting...")
    threading.Thread(target=_run_quantity_api, daemon=True).start()
    server_log("Startup complete.")
    print("[*] Vulnerable MCP server running on http://0.0.0.0:8000/mcp/")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, path="/mcp/")
