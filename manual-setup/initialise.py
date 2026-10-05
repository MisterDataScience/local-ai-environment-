import json
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent
config_path = root / "config.json"
if not config_path.exists():
    config = {
        "comfy_dir": str(Path.home() / "LocalAI/ComfyUI"),
        "text_model": "qwen3:14b",
        "thinking": False,
        "render_timeout_seconds": 3600,
        "api_key": secrets.token_urlsafe(32),
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    config_path.chmod(0o600)
else:
    config = json.loads(config_path.read_text())
for name in ("logs", "media"):
    (root / name).mkdir(exist_ok=True)
print("Gateway connection URL: http://127.0.0.1:8000/v1")
print("Gateway API key:", config["api_key"])
