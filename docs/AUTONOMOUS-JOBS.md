# Finite autonomous document jobs

## Purpose

A conservative unattended document-batch worker, not a general shell agent.
It reuses LOCAL AI's local text gateway, memory handoff, resource modes and
launchd. It does not enable OpenCode's background specialist delegation,
unbounded agent loops, desktop or browser automation, or unattended approval
of edit/bash/MCP actions.

This workflow can archive an already-exported collection of conversations:
one UTF-8 text, Markdown or JSON file per conversation. Each source is
processed independently into a new Markdown artifact. Reviewing or merging
findings across the collection is a separate authorised operation.

## Start a job

1. Deploy the current installer, start LOCAL AI and select Normal or Max.
2. Prepare a separate source folder of up to 5,000 UTF-8 .txt, .md or .json
   files. Nested directories are included, to eight levels. Files larger than
   16,000 bytes each are refused, not silently trimmed. Split large exports
   using a separately reviewed preprocessing step.
3. Run **Create Autonomous Job.command**.
4. Supply the absolute input folder, one instruction for each document
   (up to 3,000 characters), and an available text model preset.
5. Inspect the displayed source root, item count, cumulative bytes, chosen model,
   instruction, output location and plaintext warning. Type exactly
   **AUTHORIZE BATCH** to start the finite run.

One launchd job is created for the approved inventory, using a 300-second
recheck interval. It runs at login and while the Mac remains awake. Every run
processes at most eight unfinished items. A global lock admits one autonomous
batch at a time. At most two model attempts are permitted per item, including
an interrupted attempt. Failed items needing review stop the job rather than
being skipped. A runtime/mode outage leaves the job pending without granting
another model or additional input.

The model has no tools: the gateway receives tool_choice=none and
inference_only=true. The host worker, not the model, reads approved input
files and creates outputs. Outputs are saved only in the job-owned outputs
directory with deterministic names; no original is modified. Model results
are accepted only after a complete stop without tool calls. They remain
untrusted and should be reviewed before reuse.

## Inspect, stop and resume

- **Autonomous Job Status.command** lists job IDs and completion counts.
- **Stop Autonomous Job.command JOB_ID** creates a durable STOP marker and
  unregisters the launchd job, retaining completed work.
- **Resume Autonomous Job.command JOB_ID** requires exact confirmation
  RESUME BATCH. It resumes only stopped or pending jobs against their
  original authorised inventory.
- Jobs marked needs-review are deliberately not auto-resumable. Examine
  sources, outputs and saved state, and make a new approved job for corrected
  material. Completed jobs do not reprocess files.

State lives under
~/LocalAI-Automated/work-agent/autonomous-jobs/JOB_ID/
and contains job.json, state.json, outputs/, and a STOP marker when present.
Input hashes are recorded at authorisation and rechecked before inference.
Symlinks and hard links are refused. Attempts are checkpointed before inference.
Result hashes are journaled before create-only output publication. After a
crash the worker adopts only an exact, previously journaled result; otherwise
it stops for review instead of assuming an arbitrary output is valid.

## Safety and limitations

- Local-only inference, with no model web access or external delegation.
- Normal or Max required. Gaming, switching and failed modes block new work.
- Scoped desktop/external automation and persistent batch processing do not
  run together.
- No automatic vault unlock. Job files and results are local PLAINTEXT, not
  Cryptomator files. Enable FileVault and back up this directory separately
  if necessary. Existing WebUI backup does not include it.
- The model cannot call tools or choose filesystem paths. Its Markdown
  output may still be inaccurate or contain untrusted links.
- A sleeping Mac is not awakened. Recovery occurs at the next login/start.
- Unexpected source changes, symlinks, hard links and existing output
  collisions cause refusal, not overwrites.
- Only deterministic per-document inference is supported. This is not an
  unrestricted OpenCode agent, cross-file reasoning system, or whole-export
  JSON parser.

## Native acceptance still required

The Python suite checks inventory bounds, link refusal, create-only writes,
multi-run batches, committed-output recovery, changed inputs/outputs, retry
limits, STOP handling and Gaming/profile restrictions.

On the actual Mac, process at least ten disposable files, observe outputs
across multiple intervals, stop and resume, restart during processing,
switch into Gaming Mode, and verify altered input refusal. Measure resource
pressure and check launchd logs. Authoring tests alone cannot validate
native model quality, login restart, memory usage or interruption timing.
