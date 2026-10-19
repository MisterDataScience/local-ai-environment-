# Using the Village infrastructure

The Village can keep useful work between conversations. Ask the Captain to save
a small solution in the **workshop**, leave a project **notice**, collect an
improvement **suggestion**, or prepare a **practice case**. Each operation happens
because you requested it. There is no background learning or automatic execution.

This is development code in the Agent Village pull request. Deployment remains
`main` and its single installer ZIP. Native Mac/OpenCode acceptance is pending.
Encrypted Village backup, restore and source deletion are also pending: begin
with fabricated, non-sensitive examples. No ChatGPT history import is needed.

## Start here

After the reviewed change is deployed, run the normal installer once and restart
the Work Agent. FileVault must be on. In your working project, ask:

> Show me the Village workshop and this project's noticeboard and suggestions.

First use initializes the five general Village roles and local stores if
needed. Start new workers after initialization so they receive a Village
identity. Reading works in Plan and Build. Saving contributions or preparing
practice requires Build and a native approval prompt showing the proposal.
Rejecting it leaves no contribution.

The launcher may create a fresh project copy on each import. A noticeboard
belongs to the **exact working folder**, not its display name. Reopen the same
existing project through the native project/session interface to continue its
board. Approved workshop items are shared across projects. Notices and
suggestions stay with the project that created them.

| Building | Keeps | Typical request |
| --- | --- | --- |
| Workshop | Versioned scripts, templates, checklists and examples with purpose and reported evidence | “Propose the reusable part of this solution for the workshop, including what we checked.” |
| Noticeboard | Durable project findings, blockers and requests, attributed to role and task | “Leave a notice explaining the missing fixture so the next session can pick this up.” |
| Suggestion box | Proposed improvements and owner decisions | “Record the recurring download problem as a suggestion. Do not implement it.” |
| Practice ground | A brief, explicit checks, fabricated inputs, a frozen workshop revision and reported results | “Prepare a practice case for this approved checklist using two small examples.” |

The existing team board, notes and peer messages still coordinate a live
Captain turn. The project noticeboard is a separate durable record. A notice
does not summon another agent, create work or change an assignment.

## Save a solution, then reuse it

1. Complete a real task using the existing Captain and coder.
2. Ask: “Propose its useful part for the workshop. Include its limits and the
   exact checks that ran. Remove project secrets and personal data.”
3. In Build, inspect the native publishing prompt. Approval saves a **pending**
   proposal and returns its ID, revision and digest. Other agents cannot use it.
4. Inspect the full pending revision using the owner command below. Approve the
   exact revision and digest after reviewing its content and evidence.
5. Later ask: “Search the workshop for a solution to this problem, inspect the
   relevant item, and check whether it fits this project before using it.”

An installation fix might leave a short diagnostic checklist or a helper for
one known failure. Prefer small contributions with clear inputs, expected
outputs and limits. An entire project with embedded credentials is unsuitable.

An approved script stays inert stored text. To use it, the coder reviews it,
copies/adapts it into the selected project and uses existing native edit/command
approvals. Storing or sharing it never executes it. A new revision starts
pending; the earlier approved revision remains available until you approve its
replacement or withdraw it. Reported checks are evidence claims, not an
independent test certificate. Approval records who reviewed it and when.

## Owner review and decisions

The Captain searches and proposes through ordinary language. Final workshop
approval and lifecycle decisions use the installed `Agent Village.command`.
This keeps a model from approving its own proposal. It is a command helper,
not another installer. Set these variables to your actual installed command
and the working folder printed by the Work Agent launcher:

```bash
VILLAGE_COMMAND="$HOME/LocalAI-Automated/Agent Village.command"
VILLAGE_PROJECT="/absolute/path/to/the/actual/work-agent/project"

"$VILLAGE_COMMAND" workshop --project "$VILLAGE_PROJECT" list
"$VILLAGE_COMMAND" workshop --project "$VILLAGE_PROJECT" show tool:ITEM_ID
```

`show` prints full revisions, content, reported evidence, authors, states and
digests. Replace all example IDs and digests with the exact returned values:

```bash
"$VILLAGE_COMMAND" workshop --project "$VILLAGE_PROJECT" decide tool:ITEM_ID approved \
  --revision 1 --digest EXACT_DIGEST \
  --owner-approval "Reviewed this exact checklist and its evidence"
```

Use `rejected` for a pending revision or `withdrawn` for an approved revision.
Stale digests and revisions are refused. Withdrawal prevents new reads; it
cannot erase copies previously fetched into projects or sessions.

You can submit an existing small UTF-8 file yourself. Use an absolute path
because the launcher runs inside the installed control directory:

```bash
"$VILLAGE_COMMAND" workshop --project "$VILLAGE_PROJECT" propose "CSV input checklist" \
  --kind checklist --purpose "Check headers before processing a small CSV" \
  --file "/absolute/path/checklist.txt" --tag csv \
  --evidence "Two fabricated inputs reviewed manually; no code execution"
```

Kinds: `python`, `shell`, `template`, `checklist`, `text`. A replacement proposal
adds `--id tool:ITEM_ID` and keeps its title and kind. The owner can revise an
agent's contribution in its original project. Artifacts have a 16,000-character
limit; descriptions have 1,600 characters, with eight short evidence references.
Use concise entries rather than storing whole projects.

## Noticeboard and suggestions

Try these requests:

> Show this project's unresolved notices before we continue.

> Post a notice: the parser handles the current CSV but still needs an empty-file
> check. Include the actual test-report reference.

> Review our recorded suggestions and explain the most useful next improvement.
> Do not change anything yet.

Suggestions start `proposed`. The owner can mark one `accepted`, then
`implemented` after actual work, or `declined`. Accepting it only records a
decision; ask the Captain separately to implement it. Notices start `open` and
can be `closed` by the owner:

```bash
"$VILLAGE_COMMAND" suggestions --project "$VILLAGE_PROJECT" list
"$VILLAGE_COMMAND" suggestions --project "$VILLAGE_PROJECT" show entry:ENTRY_ID
"$VILLAGE_COMMAND" suggestions --project "$VILLAGE_PROJECT" decide entry:ENTRY_ID accepted \
  --digest EXACT_DIGEST --owner-approval "Worth doing when I request it"

"$VILLAGE_COMMAND" noticeboard --project "$VILLAGE_PROJECT" post \
  "Missing empty-file check" "Current fabricated CSV passes; empty input is untested."
"$VILLAGE_COMMAND" noticeboard --project "$VILLAGE_PROJECT" decide entry:NOTICE_ID closed \
  --digest EXACT_DIGEST --owner-approval "Checked and resolved"
```

Show or list again after a decision: its digest changes. Lists return ten
matching cards; `list --query TEXT` narrows older records and `show ID` opens a
known entry. Decided records remain visible as history. The Captain filters
states when asked for open work. Free-text findings may be mistaken.

## Practice with a frozen example

Approve a workshop item, then ask in Build:

> Prepare a practice case for tool:ITEM_ID with two fabricated CSV headers.
> Check whether the checklist detects a missing column and accepts the valid
> example. Do not execute anything yet.

The approval prompt shows the brief and fixtures. Preparation creates:

- `candidate.txt`: the exact approved contribution, without executable permission.
- `inputs/`: up to twelve small text fixtures, 16 KB in total.
- `manifest.json`: the selected revision and hashes of the original material.
- `README.md`: the brief, expected checks and execution limits.

Preparation runs no commands. The disposable folder is not an operating-system
sandbox. Begin in Plan with fabricated inputs. Approved Build commands can still
affect files outside a folder if the command itself does so.

Open the returned folder as an existing project in the native interface, or
import a copy through `Start Work Agent.command`. The original prepared folder
is linked to the case automatically. If the launcher makes a new copy, link
that actual copy explicitly using the owner command from the original project:

```bash
"$VILLAGE_COMMAND" practice --project "$VILLAGE_PROJECT" attach case:CASE_ID \
  --target "/absolute/path/to/new/practice/project/copy" \
  --digest EXACT_CASE_DIGEST --owner-approval "Link this fabricated practice copy"
```

Only the case and its results are shared with that project. The original
noticeboard and suggestions remain separate. Then ask:

> Inspect case:CASE_ID and review the candidate against its inputs in Plan.
> Report what you checked and what remains uncertain.

If execution is necessary, switch to Build, inspect the code and approve only
the intended native commands. Ask the Captain to record actual outcomes as
`reported_pass`, `reported_fail` or `inconclusive`, with check-output references.
It never promotes a specialist or changes the workshop revision. The service
stores the agent's report; it does not independently run or verify tests.

Inspect a case and review one result using the project that recorded it:

```bash
"$VILLAGE_COMMAND" practice --project "$VILLAGE_PROJECT" show case:CASE_ID
"$VILLAGE_COMMAND" practice --project "$VILLAGE_PROJECT" decide entry:RESULT_ID owner_accepted \
  --digest EXACT_RESULT_DIGEST --owner-approval "Read the actual check output"
```

Use `owner_rejected` to reject a report. The case view includes its ten most
recent results and digests. Acceptance records your review, not a universal
competence score or independently verified execution.

To prepare without chat:

```bash
"$VILLAGE_COMMAND" practice --project "$VILLAGE_PROJECT" prepare tool:ITEM_ID \
  --brief "Review small CSV headers" --checks "Identify missing columns" \
  --fixtures '{"sample.csv":"name,value\nA,1\n"}'
"$VILLAGE_COMMAND" practice --project "$VILLAGE_PROJECT" record \
  "Manual header review" "Found the missing column; no commands ran." \
  --case case:CASE_ID --result inconclusive --evidence "Exact check-output reference"
```

## Storage and boundaries

Additive, versioned tables live in the existing private
`~/LocalAI-Automated/village/village.sqlite`. Existing archives, lessons, stable
specialist IDs and grants are preserved. Unknown future schemas fail closed.
Practice folders live in `village/practice/`. FileVault and owner-only
directory checks apply. No new model, resident service or schedule is installed.

The Captain supplies project identity, specialist revision, task attribution
and replay key. Model arguments cannot select another project, impersonate a
specialist, approve a contribution or change its lifecycle. The host checks
active lineage and general-collection grants. A repeated native call returns
its saved receipt; changing the payload under that call ID is refused.

Use fabricated or explicitly approved general material. Known private or
unavailable archive citations are refused, but arbitrary free text cannot be
reliably screened for every secret. Approved workshop content is visible across
projects. No scripts or notes can grant new tool permissions. Search returns
small cards; only selected items need enter a worker's context. Model replacement
does not change stored contributions.

Withdrawal and decisions preserve history. Permanent deletion, encrypted
export/restore, pagination, and automatic test execution are not added here.
Do not keep important files solely in this database. Existing project reports
may contain plaintext; check them before publishing.

## Acceptance on your Mac

Use fabricated data for these checks:

1. Update through the normal installer, restart the Work Agent and read facilities
   in Plan. Confirm a write is refused in Plan.
2. Reject a publishing prompt in Build; confirm nothing was saved. Approve a
   second publishing request and confirm the contribution stays pending.
3. Inspect and approve its exact digest. Confirm another project can read the
   item but cannot read the first project's notices or suggestions. Withdraw
   the item and confirm new reads are refused.
4. Approve a small replacement and prepare practice. Confirm its files are inert
   and a new project copy requires explicit attachment.
5. Review a case, record actual checks and inspect its revision, hashes and
   evidence. Confirm no automatic execution or promotion occurred.
6. Restart and reopen the same project. Confirm its records remain.

Automated tests exercise real SQLite storage and the Captain subprocess bridge
using synthetic native sessions and approval test doubles. They do not prove
real OpenCode prompt behaviour, Mac filesystem protection, model quality or
hardware performance. Keep these native acceptance checks pending until run.
