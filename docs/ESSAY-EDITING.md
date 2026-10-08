# Optional essay editing

The implementation follows [the writing specification](ESSAY-EDITING-SPECIFICATION.md).
It reuses the existing Qwen3.5 4B document profile through the native task tool.
No extra model, external humanisation service or always-on editorial pass is added.
The document agent remains tool-free. The host supplies text and saves files.

## Use

Run the updated installer, start Local AI in Normal or Max, then open
**Edit Essay.command**. Select a UTF-8 `.md` or `.txt` draft by entering its path.
The launcher submits a conservative copyedit, with no reordering and no randomiser.
It can attach to the already-running work-agent or Discord harness without ending
its call or restarting models. Otherwise it starts the usual OpenCode work-agent.
Keep that harness running until the task ends. Stopping it or changing modes can
interrupt the edit. This is not a durable background-job service.

The original file is never overwritten. Results are under the active project:
`work-agent/projects/<project>/.local-ai-essays/<turn>/`.
Each turn preserves `essay.original.md` and `request.json`. Each attempt creates
separate versioned editorial notes and a machine-readable review. An edited `.md`
file is saved only when the mechanical checks find no issue. Read its notes and
review the draft before using it. A successful mechanical check is labelled
`review_required`, not independent proof of meaning preservation.

Word/PDF input is not supported by this launcher. Export a plain-text working
copy first. These files are local plaintext outside the encrypted vault, as are
the existing OpenCode project copies and handoff reports.

## Explicit options in an existing OpenCode chat

Send a plain text message beginning with `ESSAY_EDIT` on its own line, followed
by a JSON object. Do not send this through an OpenCode slash command: the pinned
version evaluates shell snippets in slash-command arguments before policy hooks.
The launcher uses the plain session API and never invokes that expansion.

```text
ESSAY_EDIT
{"draft":"First paragraph.\n\nSecond paragraph.","author_request":"Copyedit this essay.","constraints":"British English. Preserve the supplied citations.","source_material":"","reorder":"none","randomiser":false}
```

Only `draft` is required. `author_request`, `constraints` and `source_material`
are optional strings. `reorder` is `none` (default), `local` or `structural`.
Setting it explicitly authorises the named movement scope. A request for smoother
writing does not. `randomiser` defaults to false. If true, this implementation
asks for at most two labelled alternatives in the notes; it does **not** perform
host random selection, create seeds or raise model temperature. No alternative
is silently applied. This is the specification's documented fallback.

Activation is bound to the current explicit user turn. An attachment alone, an
embedded marker in ordinary text or a previous editing turn does not enable it.
The coordinator calls the document task with `{}`; the host constructs the
handoff from the saved original and settings, not from a coordinator rewrite.
The mode ends with that turn. Ordinary `/document` requests keep their existing
read/summarise behavior.

## Checks and limits

- The bound native handoff, including its contract, must fit 12,000 characters.
  Oversized submissions are preserved but rejected before coordinator inference.
  No text is silently cut and no extra turns are invented to process chunks.
- Document attempts share the existing two-attempt turn budget with other
  specialists. A repeated attempt needs a concrete failure and retains its
  acceptance checklist. There is no automatic extra review-model call.
- Native serial execution, mode checks, context/output limits and depth-one
  delegation remain in place. A response with a length finish, missing native
  child identity or invalid result structure cannot release an edited file.
- Stable paragraph IDs check omissions, duplicates and unauthorised paragraph
  moves. Per-paragraph checks compare detected quotations, citations, numbers,
  common units and qualifications. Suspected abridgement is flagged.
- Removed notes must be explicitly marked and preserved with their location.
  Rhythm diagnostics, uncertain beat labels and movement records stay outside
  the finished prose. Masks are descriptive alternatives, never imposed templates.
- Mechanical checks are deliberately conservative and incomplete. They cannot
  prove semantic equivalence, detect every factual change or confirm all citation
  and qualifier relationships. Sentence-level order, attribution and logical
  dependencies still require author review. A model's explanation is not proof.

Failures retain the original and the full model response in review/handoff
records. Notes identify what failed; no clean edited file is released for that
attempt. Prior versions are not overwritten. Separately scoped sections require
new explicit user requests and are not labelled a complete whole-essay edit.

The launcher can reuse a running harness through a mode-0600 local credential
file, `work-agent/state/native-session.json`, outside model project copies.
It is removed on clean shutdown. A hard crash can leave a stale record; attachment
checks the owning process and authenticates with the fixed loopback endpoint.
No credentials are passed in draft content or sent to the document model.

## Validation and target-Mac acceptance

Automated checks use simulated model results. They cover explicit activation,
original integrity, per-turn binding, attempt and input limits, native result
recovery, separate persistence, failed/truncated outputs, protected-text changes,
reordering scope and disabled random selection. They do not establish local-model
editing quality or Mac memory/latency. The installer records essay quality as
`not_run` and verifies that the effective document agent is tool-free.

On the installed Mac, edit a short draft containing a direct quotation, a citation,
a numerical result, a meaningful “may” and a purposeful fragment. Compare the
original and result, read the notes, and confirm the native task used the document
profile without tools. Repeat with an ordinary non-editing message and confirm
that it does not create an essay artefact. Test an oversized draft, a denied or
interrupted operation and a mode change; none should be reported as a completed
edit. Inspect writing fidelity and memory pressure before relying on larger work.
