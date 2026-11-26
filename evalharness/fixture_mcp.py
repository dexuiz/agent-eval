import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evalharness.runner import execute_call


def main():
    fixture_path, journal_path = map(Path, sys.argv[1:])
    tools = json.loads(fixture_path.read_text())
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        method = request["method"]
        params = request.get("params", {})
        if method == "initialize":
            result = {"protocolVersion": params["protocolVersion"], "capabilities": {"tools": {}},
                      "serverInfo": {"name": "benchmark", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [
                {"name": name, "description": tool["description"], "inputSchema": tool["parameters"]}
                for name, tool in tools.items()
            ]}
        elif method == "tools/call":
            action = execute_call({"id": request["id"], "name": params["name"],
                                   "arguments": params.get("arguments", {})}, tools)
            with journal_path.open("a", encoding="utf-8") as journal:
                journal.write(json.dumps(action) + "\n")
            result = {"content": [{"type": "text", "text": json.dumps(action["result"])}],
                      "isError": not action["ok"]}
        elif method == "ping":
            result = {}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": request["id"],
                              "error": {"code": -32601, "message": "Unknown method"}}), flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)


if __name__ == "__main__":
    main()
