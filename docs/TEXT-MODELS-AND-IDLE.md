# Text models, profiles and idle retention

**Captain update:** ordinary installs add a shared 8K captain profile backed by
the existing 4B weights. MiniCPM installs select a shared 16K desktop GGUF profile
and use it for temporary workers, retaining the 4B fallback/32K document profile and omitting the stock
9B/12B download selections. Parallel shared requests have their own backend;
the serial specialist path described below remains available on standard installs.
See [Captain and workers](CAPTAIN-AND-WORKERS.md).

The updated installer configures three abliterated 4-bit models, with four role
profiles. Installation records artifact metadata in `control/model-artifacts.json`.

| Role | Stock API ID | Model | Context |
| --- | --- | --- | ---: |
| Coordinator | `local-ai` | Huihui Qwen3.5 4B | 8192 |
| Compatibility small alias | `local-ai-small` | Same 4B coordinator profile | 8192 |
| Analyst | `local-ai-large` | Huihui Qwen3.5 9B | 32768 |
| Document | `local-ai-team-document` | Same 4B weights, larger profile | 32768 |
| Coder | `local-ai-team-coder` | Huihui Gemma4 12B Coder Fable5 Composer2.5 v1 | 16384 |

If a stock ID has custom settings, that entry is preserved and the team uses a
separate `local-ai-team-coordinator` or `local-ai-team-analyst` ID. The authoritative
mapping is `model_team.roles` in `control/config.json`. OpenCode uses that mapping.
Model lists and selection do not load weights; only inference does.

All inference shares the serial gateway. A model or context-profile change
explicitly unloads and confirms release of the previous runner. Same-model,
same-profile requests may reuse its resident state. Failures to unload block the
next model. Ollama is configured for one loaded model and one parallel request.
No GPU memory safeguards are disabled.

New team profiles use 120-second idle retention. Existing stock timeouts are
preserved when upgrading, so legacy coordinator/analyst entries can retain 300/60
seconds. Edit `keep_alive_seconds` while services are stopped; integers 0–3600
are accepted and 0 releases after each answer. This is retention, not an inference
timeout. Profile changes take effect after restart.

`num_ctx` may be reduced to at least 512. Validated coordinator/document/analyst/
coder maxima are 8192/32768/32768/16384. Unknown custom presets remain limited to
16384. `role` must match a known artifact; it cannot be assigned to arbitrary
weights to bypass mode/context restrictions. The 32K profiles require actual Mac
memory and recall validation and may need reducing with background applications.

Gaming clamps eligible coordinator/legacy-small profiles to 4096 context and
1024 output. Normal allows the team and images; Max also allows video and other
configured text models. Normal/Max output ceilings are 4096/8192, additionally
limited to half each profile's context. The 8K coordinator therefore remains
limited to 4096 output even in Max. Use analyst/coder for longer output.

OpenCode advertises per-model input/output/context limits and uses native
compaction. WebUI still uses a conservative global trigger determined by the
smallest eligible profile; full per-role WebUI compaction is future work.
See [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md).

Stop services and rerun the updated full installer to upgrade. The private
`control/config.before-model-team-v1.json` preserves pre-migration settings.
Custom presets, timeouts, credentials and integrations are preserved. Retired
weights are not deleted from disk. Repeated installs preserve later edits.
Set `model_team.enabled` to false to disable OpenCode delegation, or restore the
backup with services stopped to return to old presets (keep a copy of current
config first). Native acceptance must be rerun after configuration changes.

The installer checks Qwen published manifest IDs and records the full digests;
it downloads the exact coder GGUF with a full SHA-256 check and imports a local
Ollama alias. Changed tags or incompatible metadata stop installation. No cloud
model or unmodified/larger fallback is selected. See the artifact constants in
`installer/payload/model_team.py` and [MODEL-TEAM-AND-HANDOFFS.md](MODEL-TEAM-AND-HANDOFFS.md).
