"""Validated text presets and bounded output budgets for shared-memory Macs."""
import copy
from model_team import PROFILES, valid_profile

OUTPUT_CAPS = {"gaming": 1024, "normal": 4096, "max": 8192}


def output_ceiling(mode, preset=None):
    """Leave at least half the configured context for input; not a token preflight."""
    ceiling = OUTPUT_CAPS[mode]
    if preset is not None:
        context = min(preset["num_ctx"], 4096) if mode == "gaming" else preset["num_ctx"]
        ceiling = min(ceiling, context // 2)
    return ceiling


DEFAULT_TEXT_MODELS = {
    "local-ai": {"name": "Everyday · Qwen3 14B", "model": "qwen3:14b",
                 "keep_alive_seconds": 300, "num_ctx": 16384, "thinking": False},
    "local-ai-small": {"name": "Small · Qwen3 4B", "model": "qwen3:4b",
                       "keep_alive_seconds": 120, "num_ctx": 16384, "thinking": False},
    "local-ai-large": {"name": "Large · Qwen3 30B-A3B", "model": "qwen3:30b-a3b",
                       "keep_alive_seconds": 60, "num_ctx": 16384, "thinking": False},
}

LEGACY_CONTEXTS = {"local-ai": 8192, "local-ai-small": 4096, "local-ai-large": 4096}


def configured_text_models(config):
    presets = config.get("text_models")
    if presets is None:
        # Existing direct gateway configurations continue to work unchanged.
        presets = {"local-ai": {"name": "Local AI", "model": config.get("text_model", "qwen3:14b"),
                                "keep_alive_seconds": 300, "num_ctx": 8192,
                                "thinking": config.get("thinking", False)}}
    if not isinstance(presets, dict) or not presets or "local-ai" not in presets:
        raise ValueError("text_models must include the default local-ai entry.")
    result = copy.deepcopy(presets)
    for identifier, preset in result.items():
        if not isinstance(identifier, str) or not identifier.startswith("local-ai"):
            raise ValueError("Text preset IDs must start with local-ai.")
        if not isinstance(preset, dict):
            raise ValueError("Each text preset must be an object.")
        model = preset.get("model")
        if not isinstance(model, str) or not model.strip() or model.endswith(":cloud"):
            raise ValueError("Each preset must name a local Ollama model.")
        if not isinstance(preset.get("name"), str) or not preset["name"].strip():
            raise ValueError("Each preset needs a display name.")
        if 'role' in preset and not valid_profile(preset):
            raise ValueError('Unknown model team role or artifact')
        context_max = PROFILES[preset['role']][1] if 'role' in preset else 16384
        for key, minimum, maximum in (("keep_alive_seconds", 0, 3600), ("num_ctx", 512, context_max)):
            value = preset.get(key)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{key} must be an integer between {minimum} and {maximum}.")
        if type(preset.get("thinking", False)) is not bool:
            raise ValueError("thinking must be true or false.")
    return result


def upgrade_text_configuration(config):
    """Migrate stock contexts once; preserve customised models and context values."""
    result = copy.deepcopy(config)
    if "text_models" not in result:
        result["text_models"] = copy.deepcopy(DEFAULT_TEXT_MODELS)
        result["text_models"]["local-ai"]["model"] = config.get("text_model", "qwen3:14b")
        result["text_models"]["local-ai"]["thinking"] = config.get("thinking", False)
        if result["text_models"]["local-ai"]["model"] != DEFAULT_TEXT_MODELS["local-ai"]["model"]:
            result["text_models"]["local-ai"]["num_ctx"] = 8192
    configured_text_models(result)
    if result.get("text_context_version", 0) < 2:
        for identifier, preset in result["text_models"].items():
            default = DEFAULT_TEXT_MODELS.get(identifier)
            if (default and preset.get("model") == default["model"]
                    and preset.get("num_ctx") == LEGACY_CONTEXTS[identifier]):
                preset["num_ctx"] = default["num_ctx"]
        result["text_context_version"] = 2
    configured_text_models(result)
    return result

