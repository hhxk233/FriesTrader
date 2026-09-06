"""Inspect the actual CLI's loaded hooks without starting a model or broker tools."""
import argparse
import json
from pathlib import Path
import queue
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parent.parent


def list_hooks(executable, root=ROOT):
    process = subprocess.Popen([executable, "-C", str(root), "app-server", "--stdio"],
        cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8")
    messages = queue.Queue()
    def reader():
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                pass
    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    def send(value):
        process.stdin.write(json.dumps(value) + "\n")
        process.stdin.flush()
    def request(call_id, method, params):
        send({"jsonrpc": "2.0", "id": call_id, "method": method, "params": params})
        deadline = time.monotonic() + 20
        for _ in range(100):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Codex hook inspection timed out")
            value = messages.get(timeout=remaining)
            if value.get("id") == call_id:
                if "error" in value:
                    raise ValueError("Codex hook inspection failed")
                return value["result"]
        raise ValueError("too many unrelated app-server messages")
    try:
        request(1, "initialize", {"clientInfo": {"name": "friestrader-preflight", "version": "1.0"},
                                  "capabilities": {"experimentalApi": True}})
        send({"jsonrpc": "2.0", "method": "initialized"})
        return request(2, "hooks/list", {"cwds": [str(root)]})
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        thread.join(timeout=1)
        process.stdout.close()


def verify(executable):
    result = list_hooks(executable)
    own = []
    expected_path = ROOT / ".codex/hooks.json"
    config = json.loads(expected_path.read_text(encoding="utf-8"))
    expected = {(event[0].lower() + event[1:], group["matcher"], handler["command"])
                for event, groups in config["hooks"].items() for group in groups for handler in group["hooks"]}
    for entry in result["data"]:
        if entry["errors"]:
            raise ValueError("loaded hook source has errors")
        for item in entry["hooks"]:
            if Path(item["sourcePath"]).resolve() == expected_path.resolve():
                if not item["enabled"]:
                    raise ValueError("FriesTrader hook is disabled")
                own.append((item["eventName"], item["matcher"], item["command"]))
            elif item["enabled"] and item["trustStatus"] not in ("trusted", "managed"):
                raise ValueError("another unreviewed hook source exists; refusing broad hook-trust bypass")
    if set(own) != expected or len(own) != len(expected):
        raise ValueError("required FriesTrader hooks are not loaded by this CLI")
    return {"status": "hooks_verified", "count": len(own), "scope": "project hooks plus already trusted/managed hooks"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.codex)))
