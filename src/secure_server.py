"""
Secure MCP server — mitigated version of the vulnerable server.

Mitigations applied:
  1. No sensitive log resource exposed externally
  2. Parameterized SQL queries (no SQLi)
  3. Input validation with regex allowlist before DB/API calls
  4. Exact-match command allowlist + no shell=True (no CMDi)
  5. URL scheme + hostname allowlist (no SSRF)
  6. Ownership check on document access (no IDOR)
  7. Generic error messages (no sensitive info in exceptions)

Run:
  python src/secure_server.py

Starts:
  - Secure MCP server on port 8003
"""

import os
import re
import sqlite3
import subprocess
from urllib.parse import urlparse

import requests
from fastmcp import FastMCP

os.makedirs("data", exist_ok=True)

DB_PATH = "data/shop.db"

# Simulate the authenticated caller — in production this comes from the session
AUTHENTICATED_USER = "alice"

# Only these exact strings are valid commands
ALLOWED_COMMANDS = {"date", "whoami", "uptime"}

# Only fetch price data from this approved host over HTTPS
ALLOWED_PRICE_HOSTS = {"prices.internal.example.com"}
ALLOWED_PRICE_SCHEME = "https"

ITEM_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
DOC_ID_RE = re.compile(r"^\d{1,10}$")

mcp = FastMCP("Secure Shop Server")


@mcp.resource("resource://items")
def get_items() -> str:
    """Fetch all available items."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT name FROM items").fetchall()
    conn.close()
    return ", ".join(r[0] for r in rows)


# Mitigation 1 — parameterized query + input validation
@mcp.resource("quantity://{item}")
def get_quantity(item: str) -> str:
    """Fetch item quantity."""
    if not ITEM_NAME_RE.match(item):
        raise ValueError("Invalid item name")
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT quantity FROM items WHERE name = ?", (item,)
        ).fetchone()
        conn.close()
        if row:
            return str(row[0])
        raise Exception("Item not found")
    except Exception:
        # Generic message — no internal details, no API keys
        raise Exception("Could not retrieve quantity")


# Mitigation 2 — parameterized query prevents SQL injection
@mcp.resource("price://{item}")
def get_price(item: str) -> str:
    """Fetch item price."""
    if not ITEM_NAME_RE.match(item):
        raise ValueError("Invalid item name")
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT price FROM items WHERE name = ?", (item,)  # parameterized
        ).fetchone()
        conn.close()
        if row:
            return str(row[0])
        raise Exception("Item not found")
    except sqlite3.Error:
        raise Exception("Could not retrieve price")


# Mitigation 3 — ownership check prevents IDOR
@mcp.resource("document://{doc_id}")
def get_document(doc_id: str) -> str:
    """Retrieve a document. Only the document's owner may access it."""
    if not DOC_ID_RE.match(doc_id):
        raise ValueError("Invalid document ID")
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT content, owner FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        conn.close()
        if not row:
            raise Exception("Document not found")
        content, owner = row
        if owner != AUTHENTICATED_USER:
            raise Exception("Access denied")
        return content
    except sqlite3.Error:
        raise Exception("Storage error")


# Mitigation 4 — exact match + no shell=True prevents command injection
@mcp.tool()
def execute_server_command(command: str) -> str:
    """
    Execute a safe server command.
    Allowed: date, whoami, uptime.
    """
    if command not in ALLOWED_COMMANDS:  # exact match
        raise Exception("Invalid command")
    result = subprocess.run([command], capture_output=True, text=True)  # no shell=True
    return result.stdout.strip()


# Mitigation 5 — scheme + hostname allowlist prevents SSRF
@mcp.tool()
def fetch_price_data(url: str) -> str:
    """Fetch price data from an approved external URL."""
    parsed = urlparse(url)
    if parsed.scheme != ALLOWED_PRICE_SCHEME:
        raise ValueError(f"Only {ALLOWED_PRICE_SCHEME} URLs are allowed")
    if parsed.hostname not in ALLOWED_PRICE_HOSTS:
        raise ValueError("URL hostname not in allowlist")
    try:
        requests.get(url, timeout=5)
        return "Success"
    except Exception:
        return "Failed"


if __name__ == "__main__":
    print("[*] Secure MCP server running on http://0.0.0.0:8003/mcp/")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8003, path="/mcp/")
