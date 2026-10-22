# Required LOCAL AI capabilities

Status: integrated on `main`; owner-Mac end-to-end acceptance remains pending. The code is present, but native performance, device behavior and account-bound approvals are not established by authoring tests.

## Vision

Ordinary WebUI image inputs resolve owned upload IDs or local file URLs through the installed global attachment filter. Inline and uploaded PNG, JPEG and WebP are normalized locally: metadata removed, EXIF orientation applied, image dimensions bounded, maximum 12 MB source and 1 MB normalized image. The gateway allows two images per message and four per request. External image URLs are rejected.

Pinned WebUI 0.11.1 converts image URLs before inlet filters. A verified, idempotent patch disables that pre-filter conversion so a remote URL cannot trigger a direct fetch before gateway validation. Installer/startup refuse an unknown upstream resolver. The filter converts owned local references instead; no network fallback exists.

The gateway checks Ollama's actual `/api/show` vision capability before inference. Model names alone do not establish support. Vision is blocked in Gaming Mode. Existing Qwen3.5 artifacts are reused; no additional resident model is installed. Browser tool image parts preserve their call IDs and reach the multimodal backend.

The Work Agent advertises image input for Qwen3.5 and exposes `projectvision_inspect_image`. This reads only the active project and performs inference through the existing serial gateway. Import browser screenshots, chat attachments or generated images first if they are outside the project. Generated vault images use explicit `vault-import` from `Outputs/Media/...`, with plaintext disclosure and approval.

## PDF and OCR

The existing Apple PDFKit/Vision reader is integrated into both ordinary WebUI upload processing and the chat attachment filter, plus `projectpdf_read_pdf` in the Work Agent. The native WebUI PDF loader adapter replaces only the pinned local PDF branch; other native format loaders remain intact. No document cloud service or OCR model is added.

OCR runs on mixed pages as well as image-only pages, preserving embedded text and adding recognized text absent from it. Extraction reports page numbers, method, empty pages, OCR errors and per-page truncation. Results are bounded to 35 MB source, at most 40 pages for the underlying reader, and a bounded overall text response. MCP/OpenAPI reads limit batches to 20 pages. Chat uses a smaller initial batch to protect coordinator context.

Use `start_page=next_page` to continue a long document. `limited=false` only means the requested page range reached the end; it does not erase a page's `truncated`, `empty` or `ocr_error` flag. Truncated page text is explicitly incomplete. Password-locked/corrupt files, subprocess timeouts and invalid ranges return errors rather than invented evidence.

Chat exposes `read_attachment_pdf` for subsequent page ranges. Chat imports preserve an immutable upload reference, which can be transferred into the Work Agent for further PDF reads and AIOffice work. Source descriptors refuse symlink ancestors and hard links; extraction does not expose arbitrary host paths.

## Connected file workflows

The existing authenticated gateway exposes a file-workflow OpenAPI connection to WebUI. `list_workflow_files` discovers bounded references; `transfer_workflow_file` requires native user approval and uses the running Work Agent's published project. An arbitrary project ID is never accepted from chat. Stale/missing agent connections fail.

Work Agent tools: `projectfiles_list_files` and approval-required `projectfiles_transfer_file`.

| Direction | Source | Destination |
| --- | --- | --- |
| browser-import | `web/browser-outputs` | Active project `Inbox` |
| browser-export | Active project | Browser `Export` |
| chat-import | Owned staged chat upload | Active project `Inbox`, upload ID in filename |
| media-import | Generated local `control/media` | Active project `Inbox` |
| vault-import | Manually unlocked vault | Active project `Inbox`, explicit PLAINTEXT copy |
| vault-export | Active project, including AIOffice outputs | Vault `Outputs` |

AIOffice and PDF tools share the existing project. A document can be imported, read/OCRed, used to create DOCX/XLSX/PPTX, validated/read back with AIOffice and exported to the vault without manual copying. Permissions still apply to each operation. Plan cannot write Office outputs; switch to Build.

Copies are create-only and capped at 50 MB. Source modification, growth, path traversal, link escapes and overwrites fail. Vault mount identity is rechecked during transfer. A private append-only transfer ledger records operation IDs, direction, project, completion/failure and output metadata, never document content. A failed-or-needs-review operation must be inspected before retrying; an output may already exist if bookkeeping failed after copying.

## Automatic operation

`Enable Login Startup.command` registers a per-user LaunchAgent running `runtime.py --background`. Background startup opens no Safari window and requires no Terminal window. Abnormal exits restart with a 60-second throttle. A clean `Stop Local AI.command` exits without triggering a crash restart. `Disable Login Startup.command` removes the startup job.

The runtime uses its existing process lock to prevent duplicates. It tracks private child process identities and only signals orphan groups whose command/start fingerprint still matches this installation. PID reuse or unrelated occupied ports never authorize a kill. Core health failures cause cleanup and a supervised restart. VPN recovery retries through the existing Docker/Gluetun stack; web remains unavailable while the VPN is down. Wake resumes readiness checks without changing resource mode or loading a model.

Scheduled tasks use native per-user launchd jobs, not another scheduler daemon. `Schedule AI Task.command` displays the exact prompt/model/schedule and requires an explicit authorization phrase. Supported schedules: daily local time or interval of at least 15 minutes. `Remove Scheduled Task.command` unregisters a job; `Scheduled Task Status.command` and chat's `scheduled_task_status` report actual results.

Unattended tasks are bounded **text inference only** through the existing gateway with `tool_choice=none`. Tool/browsing/file actions require the existing interactive approval workflow and are reported as needing approval. This is not unattended authorization for arbitrary agent work. Tasks do not change modes, wake a sleeping Mac, unlock the vault or bypass approvals. Gaming, a locked configured vault and offline services block execution. Unknown/failed results are not silently retried within the same slot. Concurrent/duplicate runs are prevented with file locks and persistent slot records.

Task definitions are local plaintext, disclosed by the configuration UI. Results go to the configured vault or, without a vault, the local scheduled-output directory. Protected results never fall back to plaintext when the vault locks.

## Verification and rollout

Run the updated installer from main on the Mac to deploy the adapters, helper commands and dependency patches. Existing installation files do not update merely because repository code changes. Start LOCAL AI in Normal or Max and start the Work Agent when testing connected document workflows.

`Check Required Capabilities.command` uploads randomized synthetic visual and raster-PDF fixtures through the real WebUI API and checks actual model answers. It does not use a mocked inference backend, change modes, unlock a vault or auto-approve agent actions. It writes `required-capabilities-acceptance.json`. Unperformed physical/UI journeys remain pending and keep the overall project incomplete.

Automated regression coverage includes real gateway HTTP authentication/handoff, owned-upload normalization/staging, real stdio MCP initialization/tool discovery, page continuation, vision capability rejection, Gaming restrictions, protected scheduled-output failure, duplicate scheduled execution, source boundaries and the pinned WebUI resolver/loader patch.

CI runs complete Python installer/gateway suites. The macOS job executes PDFKit/Vision against text, raster-only, mixed-content, multipage, corrupt and password-locked PDFs, including the chat inlet path. macOS runner evidence is not owner-hardware acceptance.

The following checks still require the running owner installation and must never be marked passed from mocks or source inspection:

- Ordinary UI image and scanned-PDF uploads with accurate actual model responses.
- OpenCode tool selection, live MCP connections and real approval/denial behavior.
- Real Playwright download to PDF/OCR to AIOffice XLSX to live Cryptomator output.
- Cold login, crash, duplicate starts, Docker/VPN failure, sleep/wake and safe shutdown.
- Actual launchd scheduled execution and failures surfaced to the user.
- Target memory use, model unload and VPN-drop behavior.

All four original acceptance journeys must succeed before claiming end-to-end completion or merging as finished.
