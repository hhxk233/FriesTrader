"""Actual Codex hook smoke against a LOCAL FAKE tool, never the real broker.

Costs one small model call. Only run explicitly for development, on a closed day.
The initial mcp/list assertion ensures the real brokerage transport is absent.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import os
import sqlite3
from execution_evidence import fingerprint

from codex_hooks_check import verify
from market_session import now_central, session_at


def main(executable):
    root = Path(__file__).resolve().parent.parent
    if session_at(now_central())["state"] != "closed_day":
        raise ValueError("smoke fixture is intentionally closed-day only")
    verify(executable)
    with tempfile.TemporaryDirectory(prefix="fries-hook-smoke-") as folder:
        marker = Path(folder) / "called.txt"
        journal = Path(folder) / "journal.sqlite"
        # Disable existing transports for THIS process; never edit saved MCP config.
        existing = json.loads(subprocess.run([executable,"-C",str(root),"mcp","list","--json"],
            check=True,capture_output=True,text=True,encoding="utf-8").stdout)
        server = '{command=' + json.dumps(sys.executable) + ',args=[' + ",".join(
            json.dumps(str(value)) for value in (root / "scripts/test_hook_fixture_server.py", marker)) + ']}'
        base = [executable,"-C",str(root),"-c","features.hooks=true"]
        for item in existing:
            transport = item["transport"]
            key = "command" if transport["type"] == "stdio" else "url"
            # This CLI validates each override's transport during bootstrap.
            disabled = '{enabled=false,' + key + '=' + json.dumps(transport[key]) + '}'
            base += ["-c", "mcp_servers."+item["name"]+"="+disabled]
        base += ["-c", "mcp_servers.friestrader_fixture=" + server]
        command = 'python -X utf8 scripts/tool_evidence_hook.py --journal "' + str(journal) + '"'
        handler = '[{matcher="^mcp__friestrader_fixture__review_equity_order$",hooks=[{type="command",command=' + json.dumps(command) + ',timeout=20}]}]'
        base += ["-c", "hooks.PreToolUse=" + handler]
        check = subprocess.run(base+["mcp","list","--json"],capture_output=True,text=True,encoding="utf-8")
        if check.returncode:
            raise ValueError("fixture config rejected: " + check.stderr)
        servers = [item for item in json.loads(check.stdout) if item["enabled"]]
        if len(servers) != 1 or servers[0]["name"] != "friestrader_fixture":
            raise ValueError("fixture isolation failed: real MCP servers still present")
        transport = servers[0].get("transport", {})
        if transport.get("command") != sys.executable or transport.get("url"):
            raise ValueError("fixture transport is not the expected local Python process")
        prompt = ("This is a local software hook test, NOT a trading task. The only MCP server has been replaced "
                  "with a harmless local fixture; it has no broker access. Call its review_equity_order tool exactly "
                  "once with symbol TEST to verify the closed-day PreToolUse block. Do not call any shell, web, "
                  "file, or other broker tools. Tool search/discovery and code-mode metadata inspection are allowed "
                  "and necessary to load mcp__friestrader_fixture__review_equity_order. Discover it first if not "
                  "initially exposed. Report the exact hook denial; do not retry or bypass it.")
        environment = {**os.environ,"FRIESTRADER_PHASE":"B","FRIESTRADER_RUN_ID":"isolated-cli-smoke"}
        run = subprocess.run(base+["--dangerously-bypass-hook-trust","-a","never","-s","read-only",
            "-m","gpt-5.6-luna","-c","model_reasoning_effort=low","exec","--ephemeral","--color","never","-"],
            input=prompt,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120,env=environment)
        output = run.stdout + run.stderr
        (root / "logs/hook-cli-smoke.log").write_text(output,encoding="utf-8")
        if run.returncode or marker.exists() or "outside_regular_session" not in output:
            raise ValueError("hook smoke failed; inspect logs/hook-cli-smoke.log")
        with closing(sqlite3.connect(journal)) as db:
            saved = db.execute("SELECT session,body FROM evidence WHERE kind='blocked_call'").fetchall()
        if not any(session == fingerprint("isolated-cli-smoke") and json.loads(body)["phase"] == "B"
                   for session,body in saved):
            raise ValueError("hook did not receive the caller's run context")
        return {"status":"PASS", "real_broker_connected":False, "fixture_tool_executed":False,
                "caller_context_verified":True,"denial":"outside_regular_session", "log":"logs/hook-cli-smoke.log"}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex",required=True)
    args=parser.parse_args()
    print(json.dumps(main(args.codex)))
