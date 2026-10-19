# Let the Village organise your history

The system can now preserve your exported conversations, review them locally,
and prepare useful knowledge, preferences, memories and specialist residents.
You choose the source and approve lasting changes. You do not need to design the
agents, invent a folder structure, write their prompts or enter memory references.

## First use

1. Install the single current installer from `main`. Unlock the registered
   Cryptomator workspace and use Max resource mode. FileVault must be On.
2. Open `Village Commons.command` and expand **Prepare the Village from your
   conversation history**. Opening the page starts no inference.
3. Select your exported `conversations.json`. The upload goes to the authenticated
   local gateway, not an external model service. The original bytes are retained
   privately with a SHA-256 receipt; reimport is resumable and deduplicated.
4. Click **Import and prepare review**. The initial ceiling is 24 hours, 4,096
   inference attempts and 64 million conservative input-byte/output units. You can
   choose smaller time/turn limits. These are local-compute ceilings, not charges
   from a remote provider. The review can finish earlier.
5. The host processes bounded passages, checks exact supporting quotations,
   consolidates identical pending extracts, and prepares recurring specialists
   when a role/topic has evidence from at least two conversations. It builds
   the proposed knowledge organisation itself.
6. Pause or let the review finish, then inspect its proposals. **Review exact
   content and destination** shows the extract and evidence. Approve or reject
   each lasting item. The host performs the accepted changes.
7. Check **Prepared resident changes** for the proposed starting maps. Approving
   a document or memory does not approve its placement in an agent's prompt.
   Those maps remain a separate final decision.

An existing imported source can be reviewed without uploading it again. Foreground
work pauses the review, preserving its cursor. Use **Resume explicitly** to continue.
Exhausted budgets need explicit extension; nothing resumes just because the machine
became idle. **Add 30 minutes / 24 turns** authorises an additional finite window.
Long imports are processed incrementally; the whole corpus is never put in one prompt.

A malformed extraction receives one bounded repair attempt. A repeated failure
pauses that passage for explicit retry or skip. Skipped passages are reported as
unreviewed, never silently labelled successful. **Forget this review's pending
work** clears its processing records; the raw import and approved records remain.

## What gets prepared

| Proposal | Result after approval |
| --- | --- |
| Knowledge, workflow or writing example | An approved Markdown Library document with source references |
| Owner preference | A labelled preference document; explicit claims need actual user evidence |
| Historical procedure/open thread/revised belief | A resident memory labelled as imported history, not that resident's lived experience |
| Recurring specialist | A resident with a generated identity, instructions, topic tags and existing role permissions |
| Starting map | A short approved guide to important memories and useful Library/Archive references |

Assistant statements are not treated as user preferences. Every extract requires
real supplied citation IDs and exact supporting quotations. Those checks establish
provenance, not that the interpretation is correct; the owner reviews its meaning.
The original historical text is untrusted data and cannot grant permissions.

Approved documents also appear as owner-only Markdown files under
`~/LocalAI-Automated/village/library/`, in `workflows`, `preferences`, `writing`
and `knowledge`, with a generated index. The operational database remains the
source used by agents. Unapproved extracts never enter that Library or normal
agent retrieval. Existing approved workflow references can be used immediately;
new references in a resident's starting map require final map approval.

## Private originals and approved extracts

Raw imports stay in the private Archive. Approval of an extract does not give
ordinary agents access to the raw conversation corpus.

For Library items, choose normal-agent access (**General**) or an **owner-only**
private document. Agent memories and specialists require explicit General approval.
General content can be used by ordinary local agents and may inform public
research when you explicitly enable that research. Choose the destination after
reviewing the actual content. Sensitive material can remain owner-only or be rejected.

Published memory evidence contains checked references and hashes, not the raw
private quotations. Owner-only pending review retains quotations for inspection.
Personalised directions never silently acquire broader collection grants.
Founding runs only the existing local Captain, with no browsing, outsourcing,
account tools, shell commands or recursive delegation.

## Encrypted backups and recovery

The existing workspace backup now includes the Village databases, SQLite WALs,
accepted raw Archive sources, approved Library Markdown, Commons data and founding
progress. It writes directly into the registered Cryptomator mount. There is no
plaintext backup destination when the vault is locked. Incomplete upload buffers
and partial raw-import copies are excluded; keep your original export independently.

The supervisor uses this path before startup and after a clean shutdown when the
vault is unlocked. **Back Up Village.command** also performs an explicit snapshot.
That helper requests a graceful stop if needed, checks that writers have stopped,
and refuses a busy store. It creates no model work and does not collect a vault
password. Current backups plus the two previous generated backups are retained.

**Restore Village.command** accepts an archive path printed by the backup helper,
such as `Archive/Backups/UUID.zip`. Restoration checks file paths, sizes, checksums,
SQLite integrity and deletion restrictions before replacing data. Previous WebUI
and Village data are retained separately. A failed validation does not replace the
current stores. Restored running sessions become paused; open Local AI explicitly.
A Village-only snapshot does not replace unrelated WebUI data.

The encryption is provided by the already registered Cryptomator workspace.
The live Village database stays on the local FileVault volume rather than a
synchronised mounted vault. Actual Mac mount/recovery acceptance remains a target
machine check; authoring recovery tests simulate the mount with real SQLite/ZIPs.

## Forgetting an imported source

For an individual memory change, use its correction, withdrawal or deletion control.
**Forget Village Source.command** is a larger privacy reset for an entire imported
export, including managed overlapping exports that contain the same conversations.
It stops Local AI, displays the plan and requires explicit approval before erasing.

The conservative plan removes:

- The selected raw export, overlapping managed copies and their indexed messages.
- All derived Village Library records/files, memories, maps, revision histories,
  lessons, workshop/practice material and pending proposals. Uncited copied material
  cannot be attributed reliably, so this reset does not guess which derived records
  are safe to retain.
- Derived specialists and their stored identities/instructions. The five baseline
  roles remain. Retained unrelated raw sources can be reviewed again to rebuild.
- Commons/founding caches, previous Village restore copies, managed Captain session
  history, managed working-project copies and runtime logs.
- Managed encrypted workspace backup archives. A minimal deletion ledger is retained
  locally and in the encrypted vault; it contains source/conversation hashes, not text.

The ledger is written before erasure. An interrupted operation blocks Village use
until the owner helper resumes it. Recovery unions the current local/vault ledger
with its restrictions, so an old backup cannot restore a forgotten source, even
on a clean local installation. Reimporting a forgotten source or a recognised
forgotten conversation is refused. A stale deletion preview cannot authorise a
changed live store. Damaged exports can be erased with a clearly reported broader
raw-source reset rather than manual database repair.

This covers data managed by this installation and its registered backup archives.
It cannot erase owner downloads, independently copied/exported projects, external
backups, provider version history or forensic remnants on storage devices. It does
not identify arbitrarily rewritten facts in new sources. Close/reload old owner
pages and other clients that already received content; deleting a stored record
cannot erase an already supplied browser/process context.

Manual preview/approval arguments are available for auditing, but normal source
forgetting uses the dedicated launcher. No resident or model can approve erasure,
restore an old snapshot or override a deletion ledger.

## What remains a native check

The implementation, migrations and recovery paths are present in the consolidated
installer. Real Mac installation, Cryptomator mount semantics, local-model output
quality, native approvals, GPU behaviour and browser layout must be measured on
the target Mac. They are tests of the implementation, not missing agent setup
that you are expected to perform manually.
