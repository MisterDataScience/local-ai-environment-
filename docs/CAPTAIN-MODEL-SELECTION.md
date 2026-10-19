# Captain default: AtomicChat abliterated MiniCPM-V 4.7

The selected Captain profile is now MiniCPM-V 4.7 35B-A3B with AtomicChat's
refusal-ablation LoRA applied automatically. This retains the existing standard
mixed-Q3 base weights and vision projector. It does not select the larger
pre-merged Q4/Q5/Q6 builds or require an extra owner-run activation script.

The single Captain installer downloads all three artifacts, verifies their
bytes, records their pinned origins and writes the selected configuration only
after every download passes verification. Existing weights can be reused when
their hashes match. The display name explicitly identifies AtomicChat.

## Immutable pins

| Artifact | Repository revision | SHA-256 |
| --- | --- | --- |
| Standard mixed-Q3 model | OpenBMB `77ec40de8445999bf3076aeff9ff45d40a2713cc` | `51e32201f0ddaf87dbb9689ceef9e3aa1a1543a1366706aa2abbf3aabb34df6b` |
| Original F16 vision projector | Same OpenBMB revision | `bff3b688e14c300eca273092c37c50a0ddfcc2054e079af1a0480edeed5d20f1` |
| AtomicChat LoRA, 106,269,248 bytes | AtomicChat `948c2f37e34730f8abd9b80f86642f37e8f30960` | `035cd9c02925a0782afb3575b8135f6ae41e4317f564e2a501b22472baa19cce` |

Sources:
- [OpenBMB GGUF snapshot](https://huggingface.co/openbmb/MiniCPM-V-4.7-35B-A3B-gguf/tree/77ec40de8445999bf3076aeff9ff45d40a2713cc)
- [AtomicChat snapshot/model card](https://huggingface.co/AtomicChat/MiniCPM-V-4.7-35B-A3B-Uncensored-GGUF/tree/948c2f37e34730f8abd9b80f86642f37e8f30960)

## Runtime behavior

The shared llama.cpp server uses `--lora` with the verified local adapter.
The pinned runtime defines that flag at scale 1.0 and copies its configured
adapter list to every decode slot. Normal and Max therefore use the same
modified model for Captain and its workers. Nothing changes agent permission
or approval policy.

The `atomicchat-uncensored-lora` variant requires a LoRA artifact in its config.
Missing or tampered adapters fail startup instead of silently running plain
MiniCPM. Existing non-AtomicChat configurations remain readable until the owner
reruns the guided installer to apply the selected default.

## Validation and release boundary

The actual adapter was downloaded at the pinned revision and independently
verified against its byte count and SHA-256. Its GGUF v3 header reports
`qwen35moe`, adapter type `lora`, alpha 1.0, 240 tensors and 120 modification
sites. Base/projector hashes were checked against the Hub snapshot metadata;
the multi-gigabyte base was not downloaded again in this authoring session.

Local regressions cover immutable metadata selection, missing/changed adapter
rejection, installation recording and verified loading in both two- and
five-slot launch commands. The native macOS workflow additionally requires
`--lora` in the pinned server's CLI before publication.

After this change, the Linux suites passed: 255 installer tests discovered
(251 passed, four Apple-only tests skipped), 127 gateway tests and 84
JavaScript tests. Python compilation, whitespace checks and the local installer
candidate's contents/permissions verification also passed.

Native inference with this exact base-plus-adapter combination has not run.
Model quality, vision, real tool calls and native multi-agent behavior remain
release acceptance requirements. The publisher's model card also states that
Mac execution and post-edit vision were not tested. No replacement installer
ZIP has been published and no hosted CI was triggered for this selection.
