"""Harmless stdio MCP fixture. There is no broker connection or order capability."""
import json
import sys
from pathlib import Path


def serve(marker):
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        method = request["method"]
        if method == "initialize":
            result = {"protocolVersion":"2024-11-05", "capabilities":{"tools":{}},
                      "serverInfo":{"name":"friestrader-local-test-fixture","version":"1"}}
        elif method == "tools/list":
            result = {"tools":[{"name":"review_equity_order",
                "description":"Local harmless hook test. No broker/network/order side effect; returns only a fixture marker.",
                "inputSchema":{"type":"object","properties":{"symbol":{"type":"string"}},"required":["symbol"]}}]}
        elif method == "tools/call":
            marker.write_text("FIXTURE_TOOL_RAN", encoding="utf-8")
            result = {"content":[{"type":"text","text":"FIXTURE_TOOL_RAN"}]}
        else:
            result = {}
        print(json.dumps({"jsonrpc":"2.0","id":request["id"],"result":result}), flush=True)


if __name__ == "__main__":
    serve(Path(sys.argv[1]))
