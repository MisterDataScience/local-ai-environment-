# Agent Village: first secure slice

Residents now use an [owner-curated starting map](RESIDENT-MEMORY.md): fast-access memories, a glossary of deeper own memories, and preferred Library or Archive workflows. The owner previews and approves map changes separately from approving memories or documents.

The optional [Village Commons](VILLAGE-COMMONS.md) adds explicitly opened, finite social and creative gatherings. It has four active places in Max, read-scoped sources, isolated transient work, individual memories and separate exact owner approvals for every lasting change. This mode does not start from login or ordinary Captain requests.

The Village adds a durable archive, source-linked lessons, a daughter register and
bounded Captain routing to the existing five worker permission templates. It has
no daemon, schedule, model training, automatic reviews or promotions. The raw
archive and SQLite database stay outside Git and outside the synchronised vault.

The [Village infrastructure guide](VILLAGE-INFRASTRUCTURE.md) covers the workshop,
persistent project noticeboard, suggestion box and practice ground, including
natural-language requests and exact owner approval commands. No conversation
export is needed to try them with fabricated data.

## Storage and privacy

The operational directory is `~/LocalAI-Automated/village`. Private imports and
reads require macOS FileVault to report **On**. The directory and database use
owner-only permissions. The live SQLite WAL database must stay on the local
FileVault volume, never in iCloud or the mounted Cryptomator drive. This release
does not yet include a verified encrypted Village backup or restore workflow.
Keep the original ChatGPT export safe until that workflow is implemented and
tested. A locked vault does not cause a plaintext fallback backup.

New messages enter the `private` collection. Captain tools can read only
`general`, even if a citation is guessed. Collection membership can be
changed deliberately with the owner command below. Every Village tool call
checks the current registered identity and collection grant in host code.
Worker prompts, web pages, historical messages and peer notes cannot grant
access or change profiles. The local owner command is privileged: run it only
from your trusted Mac account.

## Owner commands

The installer places `Agent Village.command` in the main LOCAL AI folder.
Invoke it from Terminal with the indicated arguments. The command prints a
source and destination preview before an import; `--confirm` is required to
read and ingest the file. Extract the OpenAI export locally and select its
`conversations.json`. The original bytes are preserved under a SHA-256 name.

```sh
./Agent\ Village.command status
./Agent\ Village.command import /path/to/conversations.json
./Agent\ Village.command import /path/to/conversations.json --confirm
./Agent\ Village.command search researcher.general 'concise R' --collection private
./Agent\ Village.command read researcher.general msg:CITATION --collection private
./Agent\ Village.command classify CONVERSATION_ID general --owner-approval 'owner decision'
./Agent\ Village.command propose coder.r coder.general coder --tag r --instruction 'Use cited R examples'
./Agent\ Village.command approve PROPOSAL_ID --owner-approval 'owner decision'
./Agent\ Village.command activate coder.r --owner-approval 'owner decision'
```

The read-only Captain commands `village_status`, `village_search` and
`village_read` expose the active roster and passages classified as general.
`team_run` can select an approved active daughter by tag or an explicit
`specialist_id`. It freezes the role and revision for the temporary worker,
keeps the five-worker and one-coder limits, and rechecks the revision on memory
calls. Experimental daughters are not routable. An unrelated task falls back
to the corresponding general worker. Specialist profiles use the shared model,
not resident daughter models.

Manually approved lessons require an exact citation. An
`explicit_preference` must cite a user-authored message. Use
`lesson SPECIALIST CITATION KIND CLAIM --owner-approval '...'` and
`revise-lesson ID STATUS CLAIM --owner-approval '...'` to add or retract
versioned interpretations. A lesson never overwrites its source. Private
lessons are not included in general worker packets.

## Import and correction

The importer reads one bounded conversation object at a time from a JSON
array, preserves original conversation and node JSON, parent IDs, roles,
timestamps, unsupported content descriptors and original source bytes.
Text parts are indexed with SQLite FTS5. Images, voice and attachments are
descriptors only when the export contains them; this release does not OCR or
transcribe them. Import checkpoints commit per conversation. A duplicate
identical export is skipped; a changed message gets a new citation and the old
version remains stored but inactive. A paused or failed import resumes only
when the owner reruns the command. Quoted source text is historical data and
never current authorisation.

Corrections to a lesson create another revision. The source archive remains
intact. Source deletion, derivative redaction, encrypted export/restore,
automated founding review, broader task-scoped private access and comparative
assessments are **not implemented** in this slice. Do not treat the Village as
the sole copy of private history until these are finished.

## Native acceptance on the owner's Mac

1. Verify FileVault is On, install from the canonical ZIP, and run
   `Agent Village.command status`.
2. Import a disposable branching `conversations.json` with `--confirm`;
   rerun it to confirm deduplication. Search as owner and open the citation.
3. Confirm Captain cannot find private content. Classify the disposable
   conversation as general, then search and open it through Captain.
4. Propose, approve and activate a disposable R daughter. Compare an R task
   and unrelated C task in the Captain task reports. Confirm native approval
   prompts, one-coder enforcement and retirement.
5. Restart the Mac and switch the underlying model configuration. Confirm the
   same archive citation, lessons and specialist ID remain.
6. Keep backup/restore and real private corpus import pending until the
   encrypted Village backup and deletion policy are verified.

Synthetic local tests do not prove these Mac checks or model quality.

## Architecture decision and threat notes

The Captain plugin is the authenticated dispatch boundary. It invokes the
small local Python storage service with a fixed specialist identity; model
arguments cannot choose collections. The database stores source, library,
registry and audit in separate logical tables. FTS is rebuildable from stored
messages. Inheritance references the parent's live grants. A navigation
pointer is never a grant. The schema version is recorded; unknown versions
fail closed. Imported source text is never interpreted as a shell command or
agent instruction. The local owner CLI remains a privileged administrative
surface, so access by another account with owner-level filesystem privileges
is outside this boundary.
