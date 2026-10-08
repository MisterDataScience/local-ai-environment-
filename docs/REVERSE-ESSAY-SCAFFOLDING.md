# Reverse essay scaffolding

This implementation follows the supplied [specification](REVERSE-ESSAY-SCAFFOLDING-SPECIFICATION.md).
It works backwards from an authoritative assignment brief to requirements,
architecture, numbered questions and an empty author-answer document. It does
not write answers or activate essay editing.

## Use the installed workflow

Update with the rebuilt installer, start Local AI in Normal or Max, then open
**Scaffold Essay.command**. It reuses a running Discord/work-agent harness or
starts the usual OpenCode harness. No new model download is needed.

Press Enter for guided setup and enter a run name. For a new run, select the
brief, unit specification and additional rules as UTF-8 `.txt` or `.md` files.
Enter the supplied main-text word allowance and referencing style. Blank values
are recorded as missing, not guessed. If the specification is absent, you must
confirm that the brief independently establishes the task.

Only the requested stage runs. Reopen the launcher with the same run name to
review its saved proposal. The launcher prints the exact Markdown file and
approval hash. Type `approve` only after reviewing that version. Approval records
an author decision; it does not execute the next stage. Reopen the launcher again
to request the next stage. Failed or incomplete output cannot be approved by this
shortcut; inspect the failure and use a corrected explicit request.

| Stage | Result |
| --- | --- |
| 1 | Source-bound requirements checklist |
| 2 | Proposed criterion-by-criterion architecture |
| 3 | Architecture audit and corrected proposal |
| 4 | Main-text word budget with checked arithmetic |
| 5 | Numbered questions with checked maxima and mappings |
| 6 | Evidence cues and research directions |
| 7A | Question-led source research plan |
| 7B | Authorised source acquisition outside the specialist |
| 7C | Supplied passages mapped to questions |
| 8 | Host-generated empty answer template |
| 9 | Optional host-generated progress measurements |

After Stage 7A, acquire and check the proposed references. This update does not
add an automatic web-search or download service. Existing authorised tools or
the user can acquire them. Stage 7C's launcher reads a JSON list of local checked
sources, each containing `id`, `path`, `reference` and `verified_metadata`.
The client reads the chosen text files, assigns paragraph anchors and retains the
supplied reference data. Only set `verified_metadata` to true after checking it.
For example:

```json
[{"id":"S01","path":"/Users/you/Documents/source.txt","reference":"Exact checked bibliographic reference","verified_metadata":true}]
```

A title or abstract alone cannot pass the detailed source-support check. The
mapping must point to a supplied passage, preserve its reference and location,
and still undergo author review for actual evidential support.

Approve Stage 8 to complete the scaffold. Stage 9 is optional and accepts a JSON
object mapping question IDs to your own answer text. It measures progress and
proposes optional reductions; it never edits answers or removes prompts.

## Storage, approvals and lifetime

Outputs live at:
`~/LocalAI-Automated/work-agent/state/reverse-scaffolds/<run>/`.
Each explicit request has its own directory containing the preserved packet,
preflight receipt, versioned JSON result and Markdown stage artifact. The manifest
records sources, approved versions, pending versions and explicit author-turn
approvals. It retains incomplete model output for diagnosis. The selected source
files are never overwritten. These are local plaintext files outside the vault.

Approvals are tied to exact artifact hashes. Approving a revised earlier stage
invalidates downstream approvals. A result produced from changed prerequisites
cannot become approved. Imports retain their imported status until audited.
Changing authoritative source text or assignment rules requires a new run so old
approvals cannot silently apply to a different assignment.

Keep Local AI and its work-agent running while a model stage executes. Stopping
that harness or changing resource modes may interrupt it. Saved stages persist;
this does not implement durable background execution. An interrupted model task
still consumes its attempt, and no automatic retry is started.

## Explicit packets and imported work

Instead of guided setup, the launcher accepts a local request JSON file. The
same object can be sent in an ordinary OpenCode text message after the marker
`REVERSE_SCAFFOLD` on its own line. Do not use a slash-command template: the pinned
OpenCode version expands shell snippets in slash-command arguments.

```json
{
  "run_id": "assignment-two",
  "stage": "1",
  "brief_sufficient": true,
  "word_count": 240,
  "referencing_style": "Harvard",
  "sources": [{
    "id": "BRIEF",
    "kind": "brief",
    "title": "Official assignment brief",
    "anchors": [{
      "id": "BRIEF:AC1.1",
      "kind": "criterion",
      "text": "Explain probability distribution with examples."
    }]
  }],
  "criterion_anchors": ["BRIEF:AC1.1"],
  "omissions": []
}
```

Allowed source kinds are `brief`, `spec`, `rules`, `reference` and `context`.
Allowed anchor kinds are `criterion`, `outcome`, `rule`, `passage`, `abstract`,
`title` and `context`. Anchor IDs must start with the source ID followed by `:`.
The client or user supplies source IDs and locations; the model cannot invent
them. Guided criterion recognition is deliberately limited. The author must
check the Stage 1 inventory against the full brief, especially its formatting.

A later request can contain just `run_id` and `stage`. Exact-version approval is:

```json
{"run_id":"assignment-two","stage":"approve","approve":["<64-character approval hash printed with the artifact>"]}
```

An imported architecture is submitted with `stage: "3"` and `imports` containing
`{stage: "1", payload: <requirements>}` and `{stage: "2", payload: <architecture>}`.
Payloads must conform to the stage schemas in `installer/reverse-scaffold.mjs`,
including source anchors and processing inventory. The import is structurally
checked but is not considered author-approved. Stage 3 audits it directly without
rerunning Stage 2. A source-bound requirements checklist remains necessary.

Revisions use a separate explicit request for the existing stage. Existing
question IDs and requirement mappings cannot silently change. Redesigns requiring
renumbering or removal should use a new run with an explicit scope and retain the
old run for comparison. Proposed additions remain separate; they are never folded
into required content merely because the model recommends them.

## Limits and implementation decisions

- **Profile:** the existing tool-free Qwen3.5 4B document profile, conditionally
  instructed by `reverse-scaffold-prompt.txt`. No larger-model exception.
- **Handoff size:** the exact serialised native task payload must fit 12,000
  characters. It includes the stage data, acceptance contract and return schema.
  The installed agent system prompt is outside this envelope and remains subject
  to the existing model context limit. Neither component is clipped.
- **Attempts:** the existing shared two-specialist-attempt limit applies. A second
  attempt repairs the same stage after a concrete failure. It cannot run another
  stage or hidden chunk. Host-only approvals, templates and arithmetic require no
  model attempt.
- **Over-limit scope:** inputs are preserved, dispatch is blocked and no text is
  truncated. Supply a bounded criterion/section in a new explicit request. List
  excluded material in `omissions`; partial results remain `INCOMPLETE` and cannot
  be promoted as a complete assignment through the guided approval flow.
- **State and approvals:** versioned stage files and a private local manifest,
  rather than conversational claims of approval. All model proposals stop at
  `AWAITING AUTHOR REVIEW`; only a later user action can approve them.
- **Stage 9:** deterministic whitespace-token counts and projections from filled
  answer slots. These are planning measurements, not institutional word-count or
  substantive-completeness certification. Citation/exclusion rules need review.
- **Activation:** the guided launcher or explicit structured text request. This
  first version does not infer a stage or approval from vague natural language.

The host checks source-anchor existence, exact assessed wording, command-word
identity, IDs and mappings, word sums, evidence-cue coverage, supplied metadata,
prerequisites, approvals and output status. It rejects unexpected stage fields,
missing native results and truncated responses. It cannot independently establish
academic depth, atomic question quality, all omitted requirements or the truth of
source-support claims. Author checkpoints remain mandatory.

## Validation

Automated fixtures cover the serial Stage 1–8 path, optional progress counting,
imports, missing inputs, exact approvals, stale prerequisites, budgets, evidence
coverage, invented anchors/metadata, explicit omissions, blocked audits, envelope
limits, native result recovery and the shared two-attempt budget. They use
simulated model output, not local-model planning results.

On the target Mac, run a short official criterion through Stage 1, verify the
actual document-model handoff and source anchors, and approve only after reading
the artifact. Continue through an audit and budget, inspect the generated questions,
and verify that the final answer template is empty. Test a missing word allowance,
a title-only reference and interruption. The installer records native scaffold
quality as `not_run`; actual Mac latency, memory use and planning quality remain
unverified here.
