> Update: global Gaming/Normal/Max controls are now implemented separately. See [RESOURCE-MODES.md](RESOURCE-MODES.md). The original preset design below is retained for context.

# Text model selection and idle unloading

Implemented 2026-10-05, covering steps 1 and 2 of the easiest-first feature list. This is not Gaming Mode or the global profile selector.

## Selected defaults

| UI name | API model ID | Ollama model | Idle timeout | Context cap |
| --- | --- | --- | --- | --- |
| Everyday · Qwen3 14B | `local-ai` | `qwen3:14b` | 300 seconds | 8192 tokens |
| Small · Qwen3 4B | `local-ai-small` | `qwen3:4b` | 120 seconds | 4096 tokens |
| Large · Qwen3 30B-A3B | `local-ai-large` | `qwen3:30b-a3b` | 60 seconds | 4096 tokens |

Thinking is disabled by default. The new installer downloads and checks every configured model. Approximate downloads are 2.5 GB, 9.3 GB and 19 GB respectively. Download size is not runtime memory. The largest option must pass generation on your Mac before installation is considered successful.

Open WebUI receives all three entries from `/v1/models`. It uses its existing model selector; no frontend fork is needed. Depending on the UI version, it may display the friendly name or the API model ID. Model-listing and selection do not preload weights. Sending a message loads the selected model. Existing chats using `local-ai` continue using the Everyday entry.

## Memory handoff

The serial executor checks Ollama's loaded-model list before text inference. If any loaded model differs from the requested one, it explicitly unloads all loaded models and polls for an empty list before starting inference. Failure to confirm unloading prevents the next model from loading. The same selected model may be reused while idle retention remains active.

Each chat request supplies its configured `keep_alive_seconds` to Ollama. Idle expiry is handled by Ollama, not a new background polling process. A new inference refreshes retention. Listing models does not refresh it. The setting applies after generation; it is not a generation timeout. All presets remain eligible, and `/image` or `/video` still works with every preset. Selecting Small does not prevent another chat from selecting Large.

## Change settings

Stop Local AI, edit `~/LocalAI-Automated/control/config.json`, then restart. Its `text_models` object contains entries like:

```json
{
  "local-ai-small": {
    "name": "Small · Qwen3 4B",
    "model": "qwen3:4b",
    "keep_alive_seconds": 120,
    "num_ctx": 4096,
    "thinking": false
  }
}
```

This example shows one entry, not the full configuration. Keep the other entries and credentials. Keep a `local-ai` default entry. `keep_alive_seconds` accepts integers 0–3600; 0 unloads after each reply. Negative values and indefinite retention are rejected. `num_ctx` accepts integers 512–8192. Client requests cannot override these settings. Changed models need downloading; rerun the installer to download configured models and perform native acceptance checks.

## Upgrade behaviour

Stop the running services and run the updated installer bundle. An older configuration receives the new presets once, retaining its existing default model, thinking setting, secrets and unrelated fields. A private `config.before-text-presets.json` backup preserves the prior settings. Repeated installs preserve edited presets. A standalone gateway with an old `text_model` setting continues to expose only `local-ai` until configuration is migrated.

The updated acceptance fingerprint includes `text_models.py`, so the installer does not reuse the old single-model acceptance result. Its report records the selected API ID for each check. Ollama cloud features are disabled in the supervised environment.

## Verification limits

26 authoring tests passed: 10 installer and 16 gateway tests. New tests cover model-list exposure without loading, correct backend model/timeout/context forwarding, rejection of unconfigured model IDs and invalid timeouts, client override prevention, unload-before-switch sequencing, unload failure blocking inference, reuse of the existing model, HTTP/SSE response model identity and preservation of migrated settings.

The native installer exercises each configured text model and the original media handoffs. Actual idle-expiry timing, browser menu presentation, memory use and generation speed require checks on the Mac. No global Gaming restrictions, automatic selection, VPN or background startup were added.

## Primary references

- [Qwen3 4B](https://ollama.com/library/qwen3:4b)
- [Qwen3 14B](https://ollama.com/library/qwen3:14b)
- [Qwen3 30B-A3B](https://ollama.com/library/qwen3:30b-a3b)
- [Ollama chat API](https://docs.ollama.com/api/chat)
- [Ollama lifecycle FAQ](https://docs.ollama.com/faq)
