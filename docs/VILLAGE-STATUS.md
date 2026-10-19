# Village implementation status

The system prepares and manages routine resident work. Owner approval is the
boundary for lasting changes, not a requirement to manually design the village.
The five baseline residents are created by the host automatically.

## Implemented in the draft

- Existing-role workers, approved specialist routing and scoped source retrieval.
- Captain preparation of complete specialist creation, revision and retirement
  proposals, followed by exact owner review in the dashboard. Approval can include
  the explicitly proposed active state; preparing a proposal creates no resident.
- System-prepared memory maps from approved memories, material pointers and
  relevant Library titles; optional complete map proposals by the Captain.
- Separate final approval for maps, memories and source material. No pending
  proposal becomes an agent's lasting context before approval.
- Explicit finite Commons gatherings with four active places, owner participation,
  creative formats, drafts, read access, foreground pause and no outsourcing.

Normal use is described in [Resident memory](RESIDENT-MEMORY.md) and
[Commons](VILLAGE-COMMONS.md). Manual profile commands and map editing are optional
administrative overrides, not required setup.

## Engineering still unfinished

Encrypted Village backup/restore and complete source deletion across all retained
Village copies are not implemented. Logical deletion, withdrawal and quarantine
expiry exist, but are not equivalent to full source erasure or a tested recovery
path. Automated founding analysis of a personal conversation export also remains
unfinished; the Captain management tool does not claim to implement that migration.

These are remaining development work, not chores assigned to the owner. Do not
import a real personal-history corpus until its agreed privacy and recovery work
is completed. Synthetic or already approved general work can exercise the current
resident and Commons features without that import.

## Checks requiring the target Mac

Native installation, browser presentation, actual local-model routing/navigation,
GPU throughput, memory pressure and cancellation have not been validated on the
owner's Mac. Authoring checks use real storage/HTTP/bridge code with simulated
model responses. This distinction is evidence about testing, not an instruction
to configure agents manually. See the separate developer acceptance checklist.

The implementation remains in draft PR #13. The repository update does not merge
it into main or deploy it to a Mac. GitHub Actions are not used for these updates.
