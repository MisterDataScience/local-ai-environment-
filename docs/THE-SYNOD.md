# The Synod

The Synod creates and repairs studios. It is installed with six resident roles and requires no founding event. Opening its page starts no inference. Its Studio Lead owns each commission through department reviews, owner design approval, construction, independent trials and archive closure.

The implementation follows [Institutions and studios](INSTITUTIONS-AND-STUDIOS.md) and the [studio implementation contract](STUDIO-IMPLEMENTATION-CHECKLIST.md): workflows before staffing, explicit leadership, saved handovers, bounded permissions, independent acceptance and private knowledge. It shares the existing studio dispatcher and Village storage. It does not replace the C game's production controller.

## Commissioning workflow

Open **Village Institutions.command** and select **The Synod**. Enter a creation or repair commission in its panel, or ask the Captain to contact The Synod with `studio_contact`. A repair names an existing institution ID. The inbox retains the request and replies.

| Department | Required handover |
| --- | --- |
| Purpose and Scope | Deliverable, users, scope, comparison with existing studios, assumptions and, for repair, the reported fault. |
| Workflow Design | Stages, required inputs, concrete outputs, acceptance tests, revision routes and the user feedback destination. |
| Institution Design | Complete specification with lead instructions, department roles, capabilities, founding decision and a representative trial. |
| Construction | Installation assessment, followed by host installation of the exact approved specification. |
| Trials and Review | Independent assessment of actual trial and follow-up output against approved acceptance criteria. |

The Lead accepts or returns every department handover. Reports preserve decisions and reasons, rejected alternatives, assumptions and blockers. A department cannot advance itself. Two revisions per stage are allowed before work blocks for a specific repair direction. Jobs default to one hour and 96 turns, with the existing explicit extension/resume controls.

After Institution Design, **Review complete studio design** displays the entire specification, target, effect and content digest. Approval is an explicit owner operation. The Captain, a worker or a model-authored report cannot activate it. A changed digest invalidates review. Rejection retains the dossier and cancels the commission.

Construction creates staff only from that approved specification. Its host receipt records the runtime, dependencies and message route. Unsupported requirements stop construction with a concrete blocker. Repairs preserve the studio's stable identity and previous specifications. The previous live package remains selected until its replacement passes trials; queued ordinary jobs pin their specification.

## Trials and delivery

The host sends a representative commission through the actual Studio Lead inbox and shared dispatcher. Each department produces a saved handover in an independent context. The Lead reviews it before advancement. The host then sends a follow-up on the same thread. Both runs must return accepted, nonempty output.

Host receipts identify the jobs, messages, shared thread, specification, actual input/output and result. The independent Trials and Review resident cites both receipts and judges the content against approved trial criteria. The Synod Lead performs final review. Closure requires matching receipts, independent acceptance, a complete dossier and a valid archive chain. Model reports cannot manufacture receipts.

The studio then becomes available for ordinary Captain or owner messages. Replies return to its saved Lead conversation. In `studio_contact`, a thread alone reads the conversation; message plus thread sends a follow-up. The owner inbox offers **New conversation** or an existing thread.

Approved operating specifications enter the studio's private Library with resident navigation maps. Routine outputs and operational history do not become approved personal memories. The Synod has a built-in construction contract and maps pointing to it. Residents can search approved documents, page full records, and consult evidence-linked patterns and failures.

## Institutional archive

Each studio receives a stable `synod-studio:` dossier ID. Commissions, approvals and repairs link to it. Institution names may change without breaking those links.

| Category | Contents |
| --- | --- |
| Commission | Original request, sender, conversation and target. |
| Design | Department findings, workflow and proposed specification. |
| Decision | Lead review or exact owner approval/rejection with reason and references. |
| Construction | Installation assessment, implementation receipt or missing adapter. |
| Trial | Actual input/output receipts and independent acceptance report. |
| Specification | Current operating specification and verification scope. |
| Repair | Fault report, repair direction and links to prior records. |
| Pattern / failure | Reusable workflow or failure evidence, applicability and supporting record IDs. |

**Proposed, approved, implemented and verified are distinct statuses.** Observations and rejected/blocked work are explicit. Verification of message transport is separate from an agent's judgement about content quality.

Records are append-only. SQLite triggers reject ordinary updates and deletes. Each record includes its predecessor digest and SHA-256 of its canonical contents, including identity, author, state, body and evidence links. **Check archive integrity** checks the sequence and chain. This is not a signature against an administrator able to rewrite the whole database.

One dossier pointer identifies the current specification; earlier versions remain readable. Search and full reads have explicit pages and continuation positions. Previews are incomplete evidence. The archive has a 64 MiB budget and stops instead of deleting history. Individual records are limited to 24,000 encoded bytes.

Blocked commissions remain open. Inspect their records, provide a repair direction and choose **Return to design**. Redesigned packages require fresh approval and new trial receipts. Owner cancellation after pausing jobs retains history and releases the commission slot. The Synod cannot authorise changes to unrelated institutions.

## Recovery and privacy

Jobs share the existing four background slots, one executing job per institution, local inference, Max-mode admission and foreground pause behaviour. Ordinary restart recovers interrupted work; explicit Pause remains respected. Replayable completion callbacks recover a crash between worker output persistence and parent notification without duplicating receipts.

Village backups include the archive, approved specifications, maps, inbox and job checkpoints. Restore retains explicit resume requirements. The existing, separately reviewed whole-Village privacy reset also erases Synod tables and studio conversations. Routine operation cannot delete archive history. General Village residents do not gain access to these private records.

## Current capability and validation boundary

The initial executable construction adapter supports **bounded text studios**, such as editing, critique or analysis. Role names do not grant programming, image generation, browser, filesystem or network tools. Unsupported capabilities and founding requirements remain in the design and block construction until a real adapter is implemented and tested.

The Synod can register and assess repair commissions for existing C or other custom studios. It cannot rewrite their runtimes through a text specification; construction records the missing repair adapter. Existing C production and founding retain their current implementation. This version does not autonomously implement arbitrary tools or repair arbitrary source code.

Tests use scripted local-model replies with real SQLite, queues, approvals, handovers, message routes, snapshot recovery and privacy reset. They verify institutional contracts, not real-model design quality or native Mac acceptance.
