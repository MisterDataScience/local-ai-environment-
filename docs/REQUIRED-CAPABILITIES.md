# Required LOCAL AI capabilities: vision, PDFs, automatic operation and connected files

These four capabilities are **mandatory**, not optional extensions. This branch introduces the initial runtime paths; do not classify the project as complete until the acceptance conditions below pass on the target Mac.

## 1. Vision and image input

The existing gateway now accepts OpenAI-format user `image_url` message parts containing a **base64 inline data URL**, with JPEG/PNG/WebP only. Pillow decodes locally, applies EXIF orientation, flattens transparencies, strips image metadata and bounds output to 1536 pixels and 1 MB. There are limits of 2 images/message and 4/request. The gateway passes normalized Ollama `images` fields to an eligible Qwen3.5/Gemma4 local model. No new resident model or image-downloading proxy is added.

**Not yet supported:** remote image URLs, URL attachments, multi-frame/video inputs, native Open WebUI upload transformations that do not send inline image parts, agent introspection of saved generated images, or a proof that each installed model tag accepts visual input. The earlier blanket text-only gateway rejection is removed for valid inline images. No claim of a working chat upload on the Mac until tested.

Acceptance: upload a picture through Open WebUI and check the actual backend request and accurate interpretation; test multiple images, corrupted data, oversized images, non-vision presets and Gaming mode. Confirm the current UI really sends inline data URL parts.

## 2. PDF and scanned documents

`installer/pdf_reader.py` reads local project PDFs through macOS PDFKit. Pass `--ocr` to attempt on-device Apple Vision OCR for pages without readable embedded text. It limits source size to 35 MB, page count to at most 40 per request, and text returned per page to 12,000 characters. Use:

```bash
"$HOME/LocalAI-Automated/Read PDF.command" "Inbox/document.pdf" --root "$HOME/LocalAI-Automated/work-agent/projects/PROJECT_ID" --ocr
```

This is a **local extraction CLI**, not yet an editable PDF workflow, embedded chat PDF tool, full indexed PDF retrieval, or a tested production-quality OCR integration. The Work Agent is told about the scoped command and still requires native approval for shell invocation. PDFKit/Swift compiler availability, scanned-page rasterization, language accuracy and resource use must be tested on the Mac.

Acceptance: embedded-text PDF, image-only scanned PDF, multipage mixed PDF, corrupt/password-protected PDF, huge-page rejection, symlink escape rejection and offline operation. Compare OCR text against known references. No silent export of PDF data to cloud endpoints.

## 3. Automatic operation

`Enable Login Startup.command` registers an owner-only macOS LaunchAgent to start the **existing** Local AI.app after user login. `Disable Login Startup.command` removes it. The heavyweight model still loads only on demand. This is **login-time startup**, not a silent headless daemon, boot-before-login service or automatic computer wake. The existing interactive Terminal supervisor remains part of startup.

Acceptance: cold login, repeat login, two simultaneous starts, VPN unavailable, Docker unavailable, sleep/wake, app crash, device restart, Gaming mode and shutdown. Inspect actual launchctl status. Unattended restart and scheduled autonomous jobs are **still unimplemented** and must be handled as an additional milestone; do not mistake login automation for full automatic operation.

## 4. Connected browser-to-project file handoff

`installer/file_transfer.py` explicitly imports files from the Playwright browser-output directory into an active Work Agent project's `Inbox`, or exports a project file to browser `Export`. The transfer allows only known formats, rejects traversal and symlinks, limits files to 50 MB, and refuses to overwrite existing output files. Example:

```bash
"$HOME/LocalAI-Automated/File Transfer.command" --root "$HOME/LocalAI-Automated" --project PROJECT_ID --file downloaded.pdf --direction import
```

This command moves **a copy** of the file, with no unrestricted agent access to filesystem roots. No implicit write into the Cryptomator vault, iCloud, other agent sessions or chat history is permitted.

Acceptance: import/export, filename collisions, symlink escape, no overwrite, 50 MB budget, concurrent source modification and user-scoped permissions. Browser container output mount location must be confirmed: the file must exist in `web/browser-outputs` before import. Vault-to-project approvals and transfer to/from WebUI uploads remain separate additional milestones. No silent copying of encrypted data into plaintext agent sessions.

## Implementation and validation boundary

The branch includes source and regression-test cases but there is no executed native Mac acceptance evidence. Existing browser network/approval hardening remains necessary. For the complete requirement, the following must also be delivered after these initial building blocks:

- Safe model-aware direct image inspection by the Work Agent and review of generated images.
- PDF tool exposure as first-class functionality instead of CLI/bash only.
- Login/restart/sleep-wake supervisory reliability and recurring scheduled user-approved tasks.
- Consent-based transfers across **all** storage boundaries, including encrypted vault and Open WebUI uploads, with plaintext disclosures and audited copies.

These improvements must avoid new cloud inference providers and preserve the serial model queue and strict resource modes.
