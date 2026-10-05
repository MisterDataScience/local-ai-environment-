"""Validate supplied node names and input names against your installed ComfyUI."""
import json
from pathlib import Path
import gateway

config = json.loads((gateway.ROOT / "config.json").read_text())
engine = gateway.Engine(config)
try:
    engine.unload_ollama()
    engine.start_comfy()
    schemas = gateway.api(engine.comfy, "/object_info", timeout=120)
    for kind in ("image", "video"):
        workflow = json.loads((gateway.ROOT / "workflows" / f"{kind}.json").read_text())
        for node_id, node in workflow.items():
            class_name = node["class_type"]
            if class_name not in schemas:
                raise SystemExit(f"Missing ComfyUI node: {class_name}. Read the troubleshooting section.")
            schema = schemas[class_name]["input"]
            required = schema.get("required", {})
            allowed = {**required, **schema.get("optional", {})}
            missing = set(required) - set(node["inputs"])
            unknown = set(node["inputs"]) - set(allowed)
            if missing or unknown:
                raise SystemExit(f"{kind}: node {node_id}: missing={missing}, unknown={unknown}")
            for name, value in node["inputs"].items():
                choices = allowed[name][0]
                if isinstance(choices, list) and not isinstance(value, list) and value not in choices:
                    raise SystemExit(f"{kind}: node {node_id}: unsupported {name}={value}. Check model files.")
        print(f"{kind}: installed nodes, model names and input names validated.")
    print("This checks API compatibility, not model execution. Run the chat/image/video acceptance tests next.")
finally:
    engine.stop_comfy()
    engine.executor.shutdown()
