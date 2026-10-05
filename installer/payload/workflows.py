"""ComfyUI workflow preparation and saved-output discovery. No backend I/O."""

import copy
import secrets


def fill_workflow(template, prompt):
    workflow = copy.deepcopy(template)
    found = False
    seed = secrets.randbelow(2**31)
    for node in workflow.values():
        for key, value in node.get("inputs", {}).items():
            if isinstance(value, str) and "__LOCAL_AI_PROMPT__" in value:
                node["inputs"][key] = value.replace("__LOCAL_AI_PROMPT__", prompt)
                found = True
            if key in {"seed", "noise_seed"} and isinstance(value, int):
                node["inputs"][key] = seed
    if not found:
        raise ValueError("Workflow has no __LOCAL_AI_PROMPT__ marker.")
    return workflow


def output_files(history):
    for output in history.get("outputs", {}).values():
        for values in output.values():
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict) and item.get("filename") and item.get("type") == "output":
                        yield item
