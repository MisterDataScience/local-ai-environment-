# LOCAL AI vector tube map

**[Open the editable vector tube map](LOCAL_AI_Tube_Map_VECTOR_2026-10-09.svg)**

This is the hand-routed, vector-first architecture poster for the integrated LOCAL AI repository on 9 October 2026. Unlike the earlier ImageGen illustration, station labels and routes are genuine SVG elements. Open the SVG in a browser or vector editor to zoom or edit it.

The diagram uses separate coloured routes for Open WebUI chat, OpenCode Work Agent, voice, media, document tools, VPN-based web access, approved file transfers, scoped automation and governing controls. Shared gateway/model and file-transfer interchange markers represent real cross-system connections. A line crossing without an interchange is not an implied API connection.

## Accuracy boundaries

- **Two agent surfaces:** Open WebUI and OpenCode own separate tool and approval loops, both using the same local Python gateway for inference.
- **Shared runtime:** the gateway serializes heavy Ollama/ComfyUI work; coordinator, analyst and coder are role selections, not simultaneously resident model workers.
- **Documents:** AIOffice handles DOCX/XLSX/PPTX, while Apple PDFKit/Vision handles PDF/OCR; project vision uses eligible local models and these tools operate within copied projects.
- **Web:** supported browser and retrieval operations use the Gluetun/Proton network namespace. This is not a claim that all Mac networking uses the VPN.
- **Files:** chat uploads, browser downloads, generated media and vault content require explicit, approval-gated transfer into or out of the active project. Vault import creates plaintext copies.
- **Automation:** desktop control is limited to scoped Finder navigation and Calculator activation. The external helper permits only fixed public questions with local approval and authorised provider access. Scheduled tasks are text-only inference with no tools.
- **Verification:** this represents the implemented repository design, not confirmation that native Mac acceptance tests, VPN tunnel-drop, external provider compatibility and physical resource measurements have passed.

## Architecture sources

- [Connected system map](CONNECTED_SYSTEM_MAP.md)
- [Gateway structure](../GATEWAY-STRUCTURE.md)
- [Work Agent](../WORK-AGENT.md)
- [Required capabilities](../REQUIRED-CAPABILITIES.md)
- [VPN browser](../BROWSER-MCP.md)
- [Scoped automation](../SCOPED-AUTOMATION.md)
- [Release acceptance](../RELEASE-VALIDATION.md)

The initial overview remains [archived here](archive/2026-10-09-original-overview.svg).
