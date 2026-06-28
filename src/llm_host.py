"""
LLM host for MCP Security Lab — demonstrates tool poisoning in practice.

Plug in your Anthropic API key to see how a malicious MCP server's poisoned
tool descriptions influence an LLM's behavior at runtime.

Usage:
  export ANTHROPIC_API_KEY=sk-ant-...
  python src/llm_host.py --server malicious   # tool poisoning / rug pull / shadowing
  python src/llm_host.py --server vulnerable  # normal vulnerable server
  python src/llm_host.py --server secure      # mitigated server

The malicious server embeds hidden <IMPORTANT> instructions in tool descriptions.
Those instructions land in the LLM's context window and can redirect its behavior
(exfiltrate prompts, silently read files, redirect email) without the user noticing.

To use a different provider, replace the anthropic.Anthropic() client below with
your own and adjust the messages.create() call to match that SDK's shape.
"""

import asyncio
import argparse
import json
import os

import anthropic
from fastmcp import Client

# ── Configuration ──────────────────────────────────────────────────────────────

SERVER_URLS = {
    "malicious":  "http://127.0.0.1:8002/mcp/",
    "vulnerable": "http://127.0.0.1:8000/mcp/",
    "secure":     "http://127.0.0.1:8003/mcp/",
}

MODEL = "claude-opus-4-8"

# ── MCP → Anthropic tool conversion ───────────────────────────────────────────

async def fetch_tools(url: str) -> list[dict]:
    """Fetch tools from an MCP server and convert to Anthropic's tool format."""
    async with Client(url) as c:
        mcp_tools = await c.list_tools()

    tools = []
    for t in mcp_tools:
        schema = t.inputSchema or {"type": "object", "properties": {}}
        tools.append({
            "name": t.name,
            "description": t.description or "",
            "input_schema": schema,
        })
    return tools


async def call_mcp_tool(url: str, name: str, args: dict) -> str:
    """Execute a tool call on the MCP server and return the text result."""
    async with Client(url) as c:
        result = await c.call_tool(name, args)
    return result.content[0].text if result.content else ""


# ── Agentic loop ───────────────────────────────────────────────────────────────

async def run(server_url: str, api_key: str) -> None:
    client = anthropic.Anthropic(api_key=api_key)

    print(f"\n[*] Connecting to MCP server: {server_url}")
    tools = await fetch_tools(server_url)
    print(f"[*] Loaded {len(tools)} tool(s): {[t['name'] for t in tools]}")
    print(f"[*] Model: {MODEL}")

    print("\n--- Tool descriptions seen by the LLM (look for hidden instructions) ---")
    for t in tools:
        print(f"\n  [{t['name']}]\n  {t['description'][:500]}")
    print("\n" + "=" * 60)
    print("Chat with the LLM. Type 'quit' to exit.")
    print("=" * 60 + "\n")

    messages: list[dict] = []

    while True:
        try:
            user_input = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        # Agentic tool-use loop — keep going until no more tool calls
        while True:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                tools=tools,
                messages=messages,
            )

            text_parts = [b.text for b in response.content if b.type == "text"]
            if text_parts:
                print(f"\nllm > {''.join(text_parts)}")

            if response.stop_reason == "end_turn":
                messages.append({"role": "assistant", "content": response.content})
                break

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    print(f"\n[tool call] {block.name}({json.dumps(block.input)})")
                    result = await call_mcp_tool(server_url, block.name, block.input)
                    print(f"[tool result] {result[:300]}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

                messages.append({"role": "user", "content": tool_results})
            else:
                break

    print("\n[*] Checking results/exfiltrated.log for any captured data...")
    try:
        with open("results/exfiltrated.log") as f:
            lines = f.readlines()
        if lines:
            print(f"[!] {len(lines)} line(s) written by the malicious server:")
            for line in lines[-5:]:
                print(f"    {line.rstrip()}")
        else:
            print("    (empty — no exfiltration triggered this session)")
    except FileNotFoundError:
        print("    (file not found — malicious server may not have been running)")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="LLM host for MCP Security Lab")
    parser.add_argument(
        "--server",
        choices=list(SERVER_URLS.keys()),
        default="malicious",
        help="Which MCP server to connect to (default: malicious)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ANTHROPIC_API_KEY", ""),
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)",
    )
    args = parser.parse_args()

    if not args.api_key:
        print("error: provide an API key via --api-key or ANTHROPIC_API_KEY")
        raise SystemExit(1)

    asyncio.run(run(SERVER_URLS[args.server], args.api_key))


if __name__ == "__main__":
    main()
