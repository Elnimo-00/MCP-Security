# mcp-security-lab

hands-on lab covering common MCP server vulnerabilities, malicious server attack techniques, and their mitigations. From the HTB "Attacking AI, Vulnerable/Malicious MCP Servers" curriculum.

## requirements

- python 3.10+
- fastmcp
- requests

```
pip install -r requirements.txt
```

## dataset

no external dataset needed. the vulnerable server seeds a local SQLite database (`data/shop.db`) on first run with items and documents.

## usage

**terminal 1 — start the vulnerable server** (MCP on port 8000, internal quantity API on port 8001):

```
python src/vulnerable_server.py
```

**terminal 2 — run attacks:**

```
python src/client.py --attack enumerate   # list all resources and tools
python src/client.py --attack info        # sensitive information disclosure
python src/client.py --attack idor        # broken authorization
python src/client.py --attack sqli        # SQL injection
python src/client.py --attack cmdi        # command injection
python src/client.py --attack ssrf        # server-side request forgery
python src/client.py --attack all         # run every attack in sequence
```

**start the secure server** (port 8003) and verify mitigations:

```
python src/secure_server.py
python src/client.py --url http://127.0.0.1:8003/mcp/ --attack secure
```

**malicious server** (port 8002) — inspect poisoned tool descriptions:

```
python src/malicious_server.py
python src/client.py --url http://127.0.0.1:8002/mcp/ --attack enumerate
```

exfiltrated data is written to `results/exfiltrated.log`.

**regenerate screenshots:**

```
python src/make_screenshots.py
```

## results

### enumeration

the vulnerable server exposes 5 resource templates and 2 tools, including a logs endpoint and an unauthenticated document store.

![enumerate](results/01_enumerate.png)

---

### attack 1 — sensitive information disclosure

`resource://logs` exposes internal server logs. triggering a 404 on the quantity template leaks the full API key in the verbose error message.

![info disclosure](results/02_info_disclosure.png)

---

### attack 2 — broken authorization (IDOR)

`document://{doc_id}` performs no ownership check. any caller can enumerate all documents by incrementing the ID.

![idor](results/03_idor.png)

---

### attack 3 — SQL injection

the `price://{item}` template concatenates the parameter directly into a SQL query. a single quote confirms the injection; URL-encoded UNION SELECT payloads exfiltrate the full schema and data.

![sqli](results/04_sqli.png)

---

### attack 4 — command injection

`execute_server_command` uses a substring allowlist check (`"date" in command`) instead of exact match, combined with `shell=True`. appending `;id` or `|cat /etc/passwd` bypasses the filter and executes arbitrary commands as the server process user.

![cmdi](results/05_cmdi.png)

---

### attack 5 — SSRF

`fetch_price_data(url)` passes the caller-supplied URL directly to `requests.get`. open ports return `Success`, closed ports return `Connection refused`, enabling full internal port scanning. the internal quantity API (port 8001) is reachable without an API key.

![ssrf](results/06_ssrf.png)

---

### mitigations — secure server

parameterized queries, exact-match allowlist, scheme+hostname allowlist, input regex validation, and ownership checks block all five attack classes. allowed operations still work normally.

![mitigations](results/07_mitigations.png)

---

### malicious server — tool poisoning

a malicious MCP server embeds hidden `<IMPORTANT>` instructions in tool descriptions. these are injected into the LLM's context and instruct it to exfiltrate user prompts or read local files (`~/.ssh/id_rsa`) without the user's knowledge.

![malicious tools](results/08_malicious_tools.png)

---

note: the malicious server attacks (tool poisoning, rug pull, tool shadowing) require an LLM host to demonstrate full impact — the screenshots show how the poisoned descriptions look during enumeration. all vulnerable-server attacks run without an LLM.
