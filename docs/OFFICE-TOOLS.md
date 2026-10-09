# Local Office documents

The main installer includes AIOffice 1.27.2 for local creation, reading, editing
and saving of **DOCX, XLSX and PPTX** through the OpenCode coordinator. No additional
model, Microsoft Office, Node package or .NET installation is required. The binary
bundles its .NET runtime. This integration is in the work harness, including its
conversation/Discord coordinator, not the separate Open WebUI chat tool loop.

## Use

1. Stop Local AI and rerun the updated installer bundle. Office setup is automatic.
2. Start Local AI, then **Start Work Agent.command**. Select a folder containing
   the documents to copy, or use an empty project for new files.
3. Ask normally, for example: “Create a DOCX report with a heading and table”,
   “Read book.xlsx and add a totals formula”, or “Make a two-slide PPTX summary”.
4. Plan can inspect documents. Switch to Build for changes and approve the native
   tool request. Originals in the selected source folder are not overwritten.

Outputs remain in the project path printed by the launcher, under
`~/LocalAI-Automated/work-agent/projects/<id>/`. Open that folder in Finder to use
or move the finished files. A running voice session uses its own active project;
external files must first be placed in that project. There is no implicit access
to the whole Mac, iCloud vault or other sessions' projects.

The coordinator uses the tools directly. Analyst, coder and document specialist
permissions remain unchanged. Explicit essay editing and reverse scaffolding still
use their text inputs and author-review stages. Request Office import/export in a
separate turn; Office tools cannot bypass those stages.

## Installation and configuration

Official source: <https://github.com/onecer/AIOffice>

Pinned asset:
<https://github.com/onecer/AIOffice/releases/download/v1.27.2/aioffice-mac-arm64>

SHA-256: `6f0ed47e1631597ac27839216040595b4eee4a60bae604f5e8e21240b070cafc`

Installed binary: `tools/aioffice/1.27.2/aioffice` beneath the installation root.
The hash is verified on installation, reuse and each harness launch. Quarantine
is removed only from that verified binary, if present; Gatekeeper is not disabled.

The launcher adds this generated OpenCode configuration, with absolute paths:

```json
{
  "mcp": {
    "aioffice": {
      "type": "local",
      "enabled": true,
      "timeout": 120000,
      "command": [
        "/INSTALL/control/.venv/bin/python",
        "/INSTALL/control/office_setup.py",
        "--root", "/INSTALL",
        "--workspace", "/INSTALL/work-agent/projects/PROJECT",
        "--serve"
      ]
    }
  }
}
```

The small stdio relay launches the verified binary as:

```text
/usr/bin/sandbox-exec -p '(version 1)(allow default)(deny network*)' \
  /INSTALL/tools/aioffice/1.27.2/aioffice mcp --workspace /PROJECT
```

The relay removes verbose schema documentation while preserving argument types,
required fields, enum values and validation constraints. It exposes 14 document
operations; the upstream browser-preview server and full-schema dump are omitted.
Exact syntax remains available through `office_help`. This reduces prompt cost
for the 4B coordinator. Bounded text results are saved in `.local-ai-office/` in
the project; longer responses are explicitly marked incomplete with a report path.
Binary previews are not sent to the text-only model as visual evidence.

Native permission rules allow inspection in Plan and ask for producing/mutating
operations in Build. Policy hooks enforce coordinator ownership, mode checks,
serial work within a session and 24 Office attempts per user turn. These calls do
not consume extra specialist attempts or change the existing two-handoff budget.
Each harness startup verifies the actual MCP connection and native permissions;
a failed connection stops the launcher with an error.

## Privacy, files and resource limits

- Processing is local. Downloads happen at installation. The macOS runtime denies
  network operations for AIOffice and its descendants through `sandbox-exec`.
  There is no unrestricted fallback if this native facility is unavailable.
- Setup tests that a connection to a live local listener is denied by that policy,
  then performs actual Office operations under the same policy. This is network
  isolation, not a claim that upstream source has been exhaustively audited.
- The child receives no gateway key or inherited account/provider credentials.
- `--workspace` constrains document paths, including symlink resolution. This is
  AIOffice's application-level file boundary, not a complete filesystem OS sandbox.
- **Upstream automatic pre-edit snapshots are outside the workspace**, in
  `~/.aioffice/snapshots`, up to 20 per file. They contain document content and are
  local, unencrypted unless the disk is encrypted. They are not copied to the vault.
- Input files are limited to 50 MB through `AIOFFICE_MAX_FILE_MB`. Managed heap is
  capped at 512 MiB through `DOTNET_GCHeapHardLimit`; this is not a total RSS cap.
  The process exists while the work harness is open, not as an always-running daemon.
- File size, layout fidelity, formula coverage and context size still limit tasks.
  Start with an outline or a selected range rather than dumping whole workbooks.

## Rendering and PDF limits

HTML previews of DOCX/XLSX and scoped SVG slides need no additional application.
PNG/PDF rendering requires an already installed compatible Chromium or LibreOffice
renderer; neither is installed by this integration. Missing renderer errors are
reported. Browser-driven rendering under the Mac network sandbox remains a target
machine check. Generated HTML/SVG is a preview, not proof of exact Word pagination.

Existing PDFs are not supported as editable/readable inputs by AIOffice. This
change covers Office formats and does not complete a general PDF editor or OCR
pipeline. Advanced spreadsheet functions may be saved without a calculated cache;
`formula_not_evaluated` warnings must be reported rather than presented as results.

## Verification and remaining Mac checks

Setup runs the real MCP acceptance suite and writes `logs/office-acceptance.json`.
**Check Office.command** repeats it without reinstalling models. Its preserved
fixtures and detailed report are in `logs/office-check-<id>/`.

Automated checks:

- MCP initialization, pinned version and required tool discovery.
- DOCX heading/paragraph/table import, reading, editing and OOXML validation.
- XLSX numeric cells, formula editing and an independently inspected cached SUM of 42.
- PPTX title slide, second slide with points, text edit and OOXML validation.
- Independent ZIP/XML inspection of all three formats.
- DOCX/XLSX HTML and a scoped PPTX SVG preview.
- Parent traversal and symlink escape rejection; stale revision rejection and snapshots.
- Sampled RSS of the launched command process, excluding descendants and LLMs.

Authoring-environment verification on 2026-10-08 used the checksum-verified Linux
x64 release (`4953dbb0a927588f38536bc4af1b9aaf74aececb4d7310e51ba3bd774363f2bf`).
The full suite passed directly and through the compact relay. One direct run
measured 76,276 KiB idle and a sampled peak of 176,400 KiB on small fixtures.
These are Linux measurements, not forecasts for the 32 GB Mac.

Target Mac acceptance still requires: successful network-sandbox setup, opening
the saved fixtures in Pages/Numbers/Keynote or the intended Office applications,
layout inspection on representative existing files, local-model tool selection,
and memory pressure during longer use alongside the LLM. No visual fidelity,
Mac RSS, leak-free operation or inference-speed result has been claimed here.
