import json
from src.capabilities.primitives.mcp_client import MCPClientManager

mgr = MCPClientManager("config/mcp_servers.yaml")
tools = mgr.discover_tools()
for srv, tlist in tools.items():
    print(f"=== Server: {srv} ===")
    for t in tlist:
        name = t["name"]
        schema = t.get("input_schema", {})
        req = schema.get("required", [])
        props = schema.get("properties", {})
        print(f"\nTool: {name}")
        print(f"  Required: {req}")
        for pname, pdef in props.items():
            print(f"  Param '{pname}': {json.dumps(pdef)}")
