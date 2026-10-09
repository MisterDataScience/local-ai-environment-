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

The extractor is now also available as a **first-class scoped Work Agent MCP tool**, `projectpdf_read_pdf`. It is not a PDF editor, an indexed retrieval engine or a standalone Open WebUI PDF tool. The Work Agent is told about the scoped command and still requires native approval for shell invocation. PDFKit/Swift compiler availability, scanned-page rasterization, language accuracy and resource use must be tested on the Mac.

Acceptance: embedded-text PDF, image-only scanned PDF, multipage mixed PDF, corrupt/password-protected PDF, huge-page rejection, symlink escape rejection and offline operation. Compare OCR text against known references. No silent export of PDF data to cloud endpoints.

## 3. Automatic operation

`Enable Login Startup.command` registers an owner-only macOS LaunchAgent to start the **existing** Local AI.app after user login. `Disable Login Startup.command` removes it. The heavyweight model still loads only on demand. This is **login-time startup**, not a silent headless daemon, boot-before-login service or automatic computer wake. The existing interactive Terminal supervisor remains part of startup.

Acceptance: cold login, repeat login, two simultaneous starts, VPN unavailable, Docker unavailable, sleep/wake, app crash, device restart, Gaming mode and shutdown. Inspect actual launchctl status. A throttled crash-restart policy is now configured through launchd; scheduled autonomous jobs remain **unimplemented** and must be handled as an additional milestone; do not mistake login automation for full automatic operation.

## 4. Connected browser-to-project file handoff

`installer/file_transfer.py` explicitly imports files from the Playwright browser-output directory into an active Work Agent project's `Inbox`, or exports a project file to browser `Export`. The transfer allows only known formats, rejects traversal and symlinks, limits files to 50 MB, and refuses to overwrite existing output files. Example:

```bash
"$HOME/LocalAI-Automated/File Transfer.command" --root "$HOME/LocalAI-Automated" --project PROJECT_ID --file downloaded.pdf --direction import
```

This command moves **a copy** of the file, with no unrestricted agent access to filesystem roots. No implicit write into the Cryptomator vault, iCloud, other agent sessions or chat history is permitted.

Acceptance: import/export, filename collisions, symlink escape, no overwrite, 50 MB budget, concurrent source modification and user-scoped permissions. Browser container output mount location must be confirmed: the file must exist in `web/browser-outputs` before import. Vault-to-project transfers are now implemented as explicit create-only copies using the Cryptomator mount-checked file boundary, with plaintext disclosure; integration with WebUI chat uploads is still missing. No silent copying of encrypted data into plaintext agent sessions.

## Implementation and validation boundary

The branch includes source and regression-test cases but there is no executed native Mac acceptance evidence. Existing browser network/approval hardening remains necessary. For the complete requirement, the following must also be delivered after these initial building blocks:

- Safe model-aware direct image inspection by the Work Agent and review of generated images.
- PDF tool exposure as first-class functionality instead of CLI/bash only.
- Login/restart/sleep-wake supervisory reliability and recurring scheduled user-approved tasks.
- Consent-based transfers across **all** storage boundaries, including encrypted vault and Open WebUI uploads, with plaintext disclosures and audited copies.

These improvements must avoid new cloud inference providers and preserve the serial model queue and strict resource modes.

## Tested progress in the second pass (2026-10-09)

- Linux GitHub Actions smoke/protocol regression suites now execute on pull requests. New file-transfer tests exercise browser/project and a mock-mounted vault, including create-only output and refusal to overwrite existing files.
- **Actual macOS GitHub runner:** an embedded-text PDF and a raster-only scanned PDF were generated and extracted using the Apple PDFKit and Vision OCR implementation; assertions passed. This is real macOS execution on a runner, **not** validation on the user's Mac hardware.
- First-class Work Agent tools `projectpdf_read_pdf` and `projectfiles_transfer_file` use stdio MCP; the former is a bounded read tool and the latter requests native approval before moving any file.
- The login LaunchAgent now supervises the existing Python runtime directly rather than opening a Terminal app, and uses a throttled crash-restart policy. It does not install a new inference backend.
- Vision integration tests exercise OpenAI image message parts through the gateway to the mocked Ollama API and reject external image URL fetching. Actual Qwen3.5 image recognition on the user's Mac and Open WebUI's current attachment representation are still outstanding.
- **Unfinished:** integrated chat file uploads to Work Agent project files; scheduled autonomous jobs with tested permissions; sleep/wake and real-GPU/VRAM performance; UI permission denial and actual Mac installation tests.

