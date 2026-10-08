# Reverse Essay Scaffolding Specification

**Status:** Implementation specification
**Scope:** Specification only
**Target environment:** OpenCode on an Apple Silicon Mac mini with 32 GB unified memory
**Target repository:** `MisterDataScience/local-ai-environment-`

## 1. Status language and evidence base

This document uses the following labels to prevent implementation proposals from being mistaken for established workflow rules.

- **Required:** established by the reusable report-writing workflow, the Assignment 2 artifacts, or the integration requirements for this specification.
- **Proposed:** an implementation detail that is useful but was not fixed by the established workflow. A proposed item must not become mandatory without an explicit project decision.

The established sequence is evidenced by these working artifacts:

- `09-Reusable-Report-Writing-Workflow.txt`
- `Assignment-2-Report-Architecture-Stage-4.md`
- `Assignment-2-Question-Led-Scaffold.md`
- `Assignment-2-Question-Led-Scaffold-Sources-Attached.md`
- `Assignment-2-Stage-7-Source-Index.md`
- the Assignment 2 numbered answer drafts

In this workflow, "reverse" means working backwards from the required assessed outcome, assessment criterion and command word to the small questions the author must answer. It does not mean reconstructing an author's intentions from a finished essay, and it does not author an essay on the user's behalf.

## 2. Purpose and boundaries

### 2.1 Purpose

**Required.** Reverse essay scaffolding converts an authoritative assignment brief and its supporting requirements into a traceable, question-led writing plan. It:

1. extracts the assessed requirements;
2. gives every criterion an appropriate beginning, explanatory or analytical middle, evidence need and conclusion;
3. audits that architecture before any questions are written;
4. assigns realistic word budgets;
5. decomposes each section into small, stable, numbered questions;
6. identifies which questions need evidence and what kind;
7. maps checked sources to question identifiers when sources are supplied; and
8. creates a numbered answer template in which the author writes the substantive content.

The workflow protects authorship by moving planning and evidence organisation to the model while leaving the substantive answers to the author.

### 2.2 What it does not do

**Required.** Reverse essay scaffolding does not:

- draft the answers to the scaffold;
- rewrite, polish or compile an essay;
- change the author's argument, structure or intended meaning;
- invent an assessment requirement, quotation, reference, bibliographic field, page number or source location;
- claim that a source supports a proposition when only its title or broad subject is known;
- retrieve files or browse from the tool-free document profile;
- save or overwrite source files;
- continue past a required review checkpoint without approval;
- silently omit material that does not fit a handoff; or
- create extra agent turns to evade the two-attempt budget.

### 2.3 Relationship to essay editing

**Required.** Reverse essay scaffolding and essay editing are separate, explicitly activated workflows.

| Reverse essay scaffolding | Essay editing |
| --- | --- |
| Starts with the brief, specification and planning material | Starts with author-written prose |
| Produces requirements, architecture, questions, evidence directions and an answer template | Produces edited prose and separate editorial notes |
| Does not draft or rewrite answers | May edit only within its own permission and review rules |
| Stops before compilation into finished prose | May receive an approved scaffold and author answers as inputs |

Completing reverse scaffolding must not activate essay editing. If the user later asks to compile or edit answers, the coordinator must invoke the essay-editing workflow separately and preserve its existing original, edited-output, editorial-note and author-review rules. If both are requested in one message, the coordinator must finish the scaffold, present the author checkpoint, and wait for explicit approval before any editing operation.

The existing documents `docs/ESSAY-EDITING-SPECIFICATION.md`, `docs/ESSAY-EDITING.md`, `docs/WORK-AGENT.md` and `docs/MODEL-TEAM-AND-HANDOFFS.md` remain authoritative for editing and handoff behaviour. This specification must not weaken them.

## 3. Activation and permissions

### 3.1 Explicit activation

**Required.** The coordinator must invoke this workflow only after an explicit user request to create, continue, audit or revise a reverse essay scaffold. Merely attaching an essay, brief or specification is not activation.

**Proposed.** Use the internal control value:

```text
workflow: reverse_essay_scaffolding
requested_stage: <stage number>
```

User-facing wording does not need to match that exact token. Requests such as "apply Stage 3 to the report architecture" or "create the numbered question scaffold" count as explicit activation when the intended workflow and stage are unambiguous.

### 3.2 Permission levels

**Required.** The default permission is read-only analysis of supplied material.

| Action | Default permission |
| --- | --- |
| Extract a requirement stated in a source | Allowed |
| Interpret what a command word requires | Allowed, labelled as interpretation |
| Reorder material inside a proposed architecture | Proposal only; author approval required |
| Add a topic not required by a source | Proposal only; label `PROPOSED ADDITION` |
| Remove or weaken an assessment requirement | Not allowed |
| Change the author's argument or intended meaning | Not allowed without explicit, specific permission |
| Draft a missing substantive answer | Not part of this workflow |
| Correct source text | Not allowed; record a gap or apparent conflict |
| Persist a generated artifact | Coordinator or client only, under existing authorisation rules |

Approval to build a scaffold is not approval to alter an existing essay. Approval of one proposed structural change does not grant general permission for other changes.

## 4. Inputs

### 4.1 Required inputs

**Required.** Stage 1 requires:

1. the official assignment brief or task statement;
2. the unit or module specification when the brief depends on it;
3. the required word count or an explicit statement that none is supplied;
4. the required referencing style or an explicit statement that none is supplied; and
5. any marking guidance, submission rules and mandatory examples supplied by the institution.

Every input must have a stable source ID and a location scheme supplied by the coordinator, such as page, section, paragraph or line anchors.

### 4.2 Inputs required by later stages

| Stage | Additional input |
| --- | --- |
| 2 | Approved Stage 1 requirements checklist |
| 3 | Stage 2 architecture plus the authoritative Stage 1 sources |
| 4 | Audited architecture and total word allowance |
| 5 | Approved architecture and word budget |
| 6 | Approved numbered scaffold and referencing requirements |
| 7 | Approved scaffold, citation map, source register and source text or verified metadata supplied by the coordinator |
| 8 | Approved scaffold and source labels |
| 9 | The author's numbered answers and approved word budget |

### 4.3 Optional context

Optional material may include:

- tutor feedback;
- a house style or institutional template;
- an approved case study;
- the author's topic choices;
- the author's earlier work, solely to understand preferences or examples;
- already checked sources; and
- previously approved stage outputs.

Optional context must not override the official brief unless the user identifies an authoritative amendment.

### 4.4 Source packet

**Proposed.** The coordinator should serialise each handoff as:

```text
[CONTROL]
workflow: reverse_essay_scaffolding
requested_stage: 3
artifact_status: draft

[SOURCE_MANIFEST]
BRIEF | official assignment brief | Assignment-2.pdf
SPEC  | unit specification        | Unit-H6505563.pdf
ARCH  | Stage 2 architecture      | report-architecture.md

[SOURCE BRIEF]
[BRIEF:p4:AC1.1] Explain probability distribution with examples.

[SOURCE ARCH]
[ARCH:AC1.1:introduce] Define a probability distribution...
```

The manifest and all anchor IDs are host-supplied. The model may reproduce them but must not manufacture new source locations.

### 4.5 Missing, conflicting or excessive input

**Required.** Missing information is handled as follows:

- If an official brief or task statement is absent, stop before Stage 1 and request it.
- If the unit specification, word count, referencing style or marking guidance is absent, continue only when the brief is independently sufficient. Record each absence as an `UNRESOLVED GAP`.
- If authoritative inputs conflict, report the conflict with both anchors and stop the affected decision. Do not choose one silently.
- If a later-stage artifact is supplied without its prerequisite, audit only what can be checked and mark the result `INCOMPLETE`.
- If the complete handoff would exceed 12,000 characters, do not truncate. Ask the user to select a criterion or approve a later user turn for the remainder. Any partial output must name the material processed and omitted.

## 5. Content classes and traceability

Every substantive output item must use one of these classes:

| Class | Meaning | Required treatment |
| --- | --- | --- |
| `SOURCE STATEMENT` | Directly stated by supplied authoritative material | Include one or more exact source anchors |
| `INTERPRETATION` | Reasoned implication of a source, including command-word depth | Include anchors and explain the inference briefly |
| `PROPOSED ADDITION` | Potentially useful but not required by supplied material | Keep separate and require author approval |
| `UNRESOLVED GAP` | Information missing, ambiguous, conflicting or unsupported | State what is needed and stop the affected decision |

The model must not disguise an interpretation as a source statement. A source title, abstract, search result or filename is not enough to support a detailed claim. A quotation is allowed only when the exact quoted text is in the supplied packet and its anchor is retained.

## 6. Exact workflow

The stages are serial. A later stage may start only from an approved or explicitly imported output of the preceding stage. An imported artifact keeps its original status and must be audited before it is treated as approved.

### Stage 0: Preflight and activation

**Input:** explicit activation, requested stage and supplied material.
**Output:** a preflight record containing activation status, requested stage, inputs received, missing inputs, character count and prerequisite status.

**Decision rules:**

- Reject implicit activation.
- Reject a request to combine editing automatically.
- Confirm the full serialised handoff is within the 12,000-character limit.
- Confirm that the requested operation can be completed within the remaining attempt budget.

**Stop when:** activation is absent, a required input is absent, the packet is over limit, or the requested stage would require an unauthorised change.

### Stage 1: Establish assignment requirements

**Input:** official brief, specification and submission requirements.
**Output:** a requirements checklist, not an essay.

The checklist must identify:

- every learning outcome;
- every assessment criterion;
- the command word for each criterion;
- mandatory topics, examples, technologies, calculations or case studies;
- word count, referencing and submission rules;
- exclusions and boundaries stated or necessarily implied by the sources; and
- unresolved contradictions or omissions.

Each row must include a stable requirement ID, content class and source anchor.

**Decision rules:** preserve the source wording for the assessed requirement; interpretation of command words must be labelled. Do not add common academic expectations as if the brief stated them.

**Checkpoint:** author confirms the checklist before architecture begins.

### Stage 2: Build the report architecture

**Input:** approved Stage 1 checklist.
**Output:** one proposed report architecture in which every assessment criterion is a main assessed section.

For every criterion, specify:

1. what must be introduced;
2. what must be explained, compared, analysed or evaluated;
3. what evidence or worked material is needed;
4. what judgement or conclusion the command word requires; and
5. what belongs outside the section.

Also define the report introduction, conclusion and overall narrative order. Every architecture element must link to requirement IDs.

**Decision rules:** a criterion may not disappear into another section. Shared context can be cross-referenced, but each criterion must remain independently auditable. Optional enrichment is a `PROPOSED ADDITION`.

**Checkpoint:** author may accept, reject or amend structural proposals. Unapproved changes remain proposals.

### Stage 3: Audit the architecture

**Input:** Stage 2 architecture and authoritative requirements.
**Output:** an audit table and a corrected architecture proposal, if corrections are required.

The audit must detect:

- missing requirements;
- irrelevant or unrequired material;
- repeated material;
- sections too descriptive for their command word;
- sections receiving too much or too little space;
- indicative content that should be explicit;
- material assigned to the wrong criterion; and
- any unsupported structural assumption.

**Decision rules:** do not create the question scaffold until all blocking findings are resolved or explicitly accepted as unresolved by the author.

**Stop when:** any criterion is missing, any source conflict changes coverage, or a required correction needs author permission.

### Stage 4: Set realistic word budgets

**Input:** audited architecture and total word count.
**Output:** a word-budget table whose allocations sum exactly to the allowed main-text total.

The budget must reflect criterion importance, command word, number of mandatory topics and required depth. The established starting proportions are approximately 5% for the introduction, 85% to 90% for assessed criteria, and 5% for the conclusion. Every allowance is a maximum, not a target.

**Decision rules:** in-text citations count when the assignment counts them as main text. Excluded front matter, diagrams, references and appendices must follow the official brief rather than a generic assumption.

**Later progress rule:** after approximately one third of the answers, compare actual and planned writing rates. If the author is consistently around 50% over the planned rate, remove low-value remaining prompts or optional detail. Do not merge questions while retaining all their demands.

### Stage 5: Create the question-led scaffold

**Input:** approved architecture and word budget.
**Output:** a question-led scaffold with stable identifiers such as `1.1.1`, `1.1.2` and `2.3.1`.

Each question must:

- normally ask for one intellectual task;
- map to one or more requirement and architecture IDs;
- state a maximum word allowance;
- be answerable without seeing hidden chat history;
- avoid drafting the answer inside the question; and
- retain its identifier through all later stages.

Every assessed section must end with a question appropriate to its command word. For example, `explain` requires how and why, `assess` requires a reasoned significance judgement, and `critically evaluate` requires strengths, weaknesses, assumptions, limitations and a contextual judgement.

**Decision rules:** reject disguised double or triple questions. Split them unless the components form one inseparable worked procedure. Question maxima must sum to the section maximum, and section maxima must sum to the report budget.

**Checkpoint:** the author approves the questions before citation mapping or answer writing.

### Stage 6: Map evidence needs to questions

**Input:** approved Stage 5 scaffold and referencing rules.
**Output:** the same scaffold with an evidence cue under every question, plus a criterion-level research direction table.

Allowed evidence cues are:

```text
Citation required: <claim type and preferred source type>.
Evidence already cited in section: <question IDs that must provide it>.
No citation normally required: <reason>.
UNRESOLVED GAP: <missing evidence information>.
```

Definitions, academic concepts, empirical findings, technical architecture, laws, current capabilities and claims about risks or benefits normally need evidence. Signposting and the author's own judgement may not need a new citation when the judgement clearly follows from evidence already cited in that section.

**Decision rules:** Stage 6 identifies evidence needs. It must not invent actual references. Citation mapping and source collection are distinct.

### Stage 7: Conduct question-led source research and mapping

Stage 7 has three serial parts because the document model has no tools.

#### Stage 7A: Research plan

The model identifies claims requiring evidence and the source types most capable of supporting related questions. It should prefer a small number of strong, reusable sources over one source per question.

#### Stage 7B: Authorised source acquisition

The coordinator or client searches, downloads and persists sources under its existing permissions. The model does not perform or claim this action. Complete reference data and an accessible copy should be recorded when the source is selected.

#### Stage 7C: Source mapping

The coordinator supplies verified metadata and enough source text for the model to map sources to question IDs. The output source register contains:

- source ID;
- complete reference only when verified;
- stable link or saved path supplied by the coordinator;
- relevant page, chapter, section or supplied anchor;
- supported question IDs;
- exact claims or concepts supported; and
- limits on use.

**Decision rules:** never map a source from topical similarity alone. If the supporting passage is unavailable, label the mapping `UNVERIFIED` and do not present it as evidence. Never fabricate a reference field.

**Checkpoint:** author confirms that required sources are actually available before answering begins.

### Stage 8: Create the author answer document

**Input:** approved scaffold and source labels.
**Output:** a separate plain-text or Markdown answer template retaining every scaffold number.

```text
1.1.1 [Author's answer]

1.1.2 [Author's answer]

1.1.3 [HELP NEEDED: describe the specific difficulty]
```

The template must distinguish author writing, missing content, factual verification needs and explicit requests for help. It must not include model-written answers.

**Stop condition:** reverse scaffolding is complete when the approved answer template and its traceability material have been delivered.

### Stage 9: Optional progress check after author answers

**Input:** author-written numbered answers.
**Output:** words written, criteria completed, average rate, projected final count, remaining allowances and a list of low-value unanswered prompts proposed for removal.

This is a measurement and scaffold-adjustment stage, not editing. Removing a required prompt is forbidden. Any reduction to optional content requires author approval.

### Downstream stages outside this workflow

The established parent report workflow continues with compilation, explicitly requested gap filling, citation insertion, factual checking, proofreading, final assessment audit and Word conversion. In this implementation those operations belong to the separately activated essay-editing or document-finalisation workflows. Their historical stage numbers may be retained in documentation, but the reverse-scaffolding agent must not execute them.

## 7. Model judgement and mechanical checks

Model self-assessment is not independent verification. The host may validate form and consistency mechanically; a human or separately grounded review is required for substantive correctness.

| Stage | Model judgement | Host-checkable mechanics | Required human review |
| --- | --- | --- | --- |
| 0 | Resolve whether request wording is unambiguous | Activation flag, character count, attempts remaining, prerequisite presence | Ambiguous activation or permissions |
| 1 | Interpret command words and boundaries | Unique IDs, source-anchor existence, criterion counts | Accuracy and completeness against official documents |
| 2 | Choose coherent structure and analytical depth | Every criterion mapped once or more; no orphan IDs | Proposed structure and argument order |
| 3 | Identify weak depth, duplication and drift | Missing IDs, duplicate mappings, unresolved blocking status | Substantive audit findings |
| 4 | Allocate relative space | Arithmetic sums and maximums | Whether weighting is academically sensible |
| 5 | Decompose into atomic questions | ID format, uniqueness, word-sum checks, final command-word question present | Whether questions would elicit adequate answers |
| 6 | Decide evidence needs and source type | Every question has one allowed cue | Adequacy of evidence plan |
| 7 | Judge whether supplied text directly supports a claim | All mapped IDs and anchors exist; reference fields present or marked missing | Source quality and support strength |
| 8 | Word instructions clearly | Every question ID appears exactly once | Template usability |
| 9 | Identify genuinely low-value optional prompts | Word counts and projections | Approval of any scope reduction |

Independent validation must not be described as complete merely because the generating model says its own output is complete.

## 8. Output contract

### 8.1 Run-level header

Every output starts with:

```text
Workflow: reverse_essay_scaffolding
Stage: <number and name>
Status: COMPLETE | INCOMPLETE | BLOCKED | AWAITING AUTHOR REVIEW
Inputs processed: <source IDs and bounded locations>
Inputs not processed: <none or explicit list>
Attempt: 1 of 2 | 2 of 2
```

### 8.2 Required artifact set

**Required.** Source material remains unchanged. Generated outputs are separate artifacts.

| Artifact | Required content |
| --- | --- |
| Requirements checklist | Requirement IDs, source wording, command words, mandatory content, anchors, gaps |
| Report architecture | Criterion sections, beginning, middle, evidence, conclusion, boundaries and links |
| Architecture audit | Finding, severity, affected IDs, evidence, proposed resolution and approval status |
| Word budget | Per-section maxima, arithmetic total and inclusion/exclusion basis |
| Question scaffold | Stable IDs, atomic questions, maxima, requirement links and content classes |
| Citation map | One evidence cue per question and research directions |
| Source index | Verified source data, question map, relevant locations and use limits |
| Author answer template | Every question ID exactly once with empty answer slots |

**Proposed.** Store each artifact separately and add a machine-readable run manifest, rather than combining all stages in one large file. Suggested filenames are `requirements-checklist.md`, `report-architecture.md`, `architecture-audit.md`, `word-budget.md`, `question-scaffold.md`, `citation-map.md`, `source-index.md`, `author-answer-template.md` and `reverse-scaffold-run.json`.

### 8.3 Detail level

- Requirements and architecture must be detailed enough that another agent can construct the same scaffold without chat history.
- A scaffold question should normally represent one paragraph component or one step in a required worked procedure.
- Evidence cues identify the claim and source type, not merely "add citation".
- Traceability uses exact supplied IDs and locations. Filename-only references are insufficient when page or section anchors were supplied.
- Gaps and proposed additions remain visible and must not be folded into required content.

### 8.4 Completion rules

`COMPLETE` means all required items for the requested stage were processed and all mechanical checks passed. `INCOMPLETE` means useful partial work exists but some declared material was not processed or a prerequisite is unresolved. `BLOCKED` means no safe stage output can be produced. `AWAITING AUTHOR REVIEW` means the model completed a proposal that cannot become approved without the author.

## 9. Handoff, model and execution constraints

### 9.1 Model selection

**Required.** Reuse the existing Qwen3.5 4B document profile for the first implementation. Reverse scaffolding is bounded document analysis and structured generation, so no model exception is presently justified. The model receives source text from the coordinator and needs no tools.

**Proposed, not enabled:** consider a larger model only after recorded acceptance tests show repeatable failures in command-word interpretation, atomic decomposition or source-support classification that cannot be corrected through prompt or packet changes. Any exception needs a separate configuration decision and memory benchmark on the 32 GB target.

### 9.2 Existing execution controls

**Required.** Preserve:

- serial execution;
- existing context and output limits;
- existing permissions;
- depth-one delegation;
- the 12,000-character handoff-input limit; and
- no more than two specialist attempts per user turn.

The specialist must not delegate further. The coordinator remains responsible for source loading and authorised persistence.

### 9.3 Attempt policy

Attempt 1 produces the requested stage. Attempt 2 may repair a failed or materially nonconforming output. It is not permission to process a hidden second chunk, run an additional stage, or restart until the model gives a preferred answer. After attempt 2, report the work as incomplete or blocked.

The host must count the exact serialised handoff it sends. If the runtime counts the installed profile prompt as part of the limit, that prompt must be included in the 12,000-character calculation. No component may be silently clipped.

### 9.4 Over-limit work

When material is over limit, the coordinator must:

1. identify the exact material that does not fit;
2. avoid semantic summarisation that could erase requirements unless the summary is already approved;
3. ask the user to select a criterion, section or later turn;
4. process only the declared bounded subset; and
5. mark the artifact `INCOMPLETE` until all required subsets have been reconciled.

The coordinator must not invent extra user turns or use repeated specialist calls to evade the two-attempt limit.

## 10. Self-contained model prompt

The following prompt is intended for the existing tool-free document profile. The coordinator supplies the requested stage and source packet. The prompt itself contains no reliance on this chat.

```text
You are the Reverse Essay Scaffolding specialist. Your job is to work backwards from authoritative assignment requirements to a traceable, question-led plan that lets the author write the substantive answers. You do not write, compile or edit the essay.

ACTIVATION
Run only when CONTROL contains:
workflow: reverse_essay_scaffolding
and a requested_stage. If either is missing or ambiguous, return BLOCKED.

AUTHORITY AND BOUNDARIES
- Treat only text in the supplied SOURCE packet as evidence.
- Preserve all source wording and source files. Your output is a separate artifact.
- Never fabricate a requirement, fact, quotation, reference, bibliographic field, page number, link or source location.
- Never claim to have opened, downloaded, searched, saved or verified a file. You have no tools.
- Do not draft assignment answers.
- Do not activate or perform essay editing.
- Do not change the author's argument, structure or intended meaning. Structural changes are proposals until the author approves them.
- Do not silently omit or truncate material.

CONTENT CLASSES
Label substantive items as one of:
SOURCE STATEMENT: directly stated in supplied authoritative material; cite exact supplied anchors.
INTERPRETATION: a reasoned implication, including command-word depth; cite anchors and explain briefly.
PROPOSED ADDITION: useful but not required; keep separate and require approval.
UNRESOLVED GAP: missing, ambiguous, conflicting or unsupported; state what is needed.

SERIAL STAGES
0 Preflight: confirm activation, requested stage, prerequisites and supplied material.
1 Requirements: make a checklist of every learning outcome, assessment criterion, command word, mandatory topic/example/calculation/case, submission rule, exclusion and gap. This is not an essay.
2 Architecture: make each assessment criterion a main assessed section. For each, state what to introduce, what to explain/analyse/evaluate, evidence or worked material needed, required conclusion/judgement, and boundaries. Link every item to requirement IDs.
3 Audit: identify missing, irrelevant, repeated, misplaced, over-expanded or underdeveloped material; test depth against each command word. Do not allow Stage 5 while blocking findings remain.
4 Word budget: allocate maxima according to importance, command word, mandatory topics and depth. Use about 5% introduction, 85-90% assessed criteria and 5% conclusion only when consistent with the supplied brief. All maxima must sum exactly to the allowed main-text count.
5 Questions: convert the approved architecture into small numbered questions with stable IDs such as 1.1.1. Each normally asks one intellectual task, links to requirement IDs and has a maximum word count. End each assessed section with a question that elicits the judgement required by its command word. Do not embed answers in questions.
6 Evidence map: put one cue under every question: Citation required, Evidence already cited in section, No citation normally required, or UNRESOLVED GAP. State the claim and preferred source type. Do not invent actual sources.
7 Source research and mapping: first produce a research plan. Map actual sources only when verified metadata and supporting source text are supplied. Record source ID, complete supplied reference, supplied location, question IDs, supported claims and limits. If the passage is absent, mark UNVERIFIED.
8 Answer template: reproduce every question ID once in a separate empty answer document. Use [Author's answer] and permit [HELP NEEDED: specific difficulty]. Do not supply answers.
9 Progress check: from author-written numbered answers, calculate words completed, projection and remaining allowances. Propose removing only low-value optional prompts. Never remove a required prompt.

PER-STAGE RULE
Perform only requested_stage. Use prior-stage artifacts only as inputs. Do not continue automatically. If a prerequisite is missing, return INCOMPLETE or BLOCKED and name it.

OUTPUT HEADER
Workflow: reverse_essay_scaffolding
Stage: <number and name>
Status: COMPLETE | INCOMPLETE | BLOCKED | AWAITING AUTHOR REVIEW
Inputs processed: <source IDs and bounded locations>
Inputs not processed: <none or explicit list>
Attempt: <supplied attempt number> of 2

OUTPUT QUALITY
- Preserve supplied IDs and anchors exactly.
- Keep source statements, interpretations, proposed additions and gaps visibly separate.
- Ensure every requirement maps forward and every output item maps back.
- State partial work as incomplete.
- Never treat your own statement that the work is correct as independent verification.

Now process only the requested stage using the supplied CONTROL, SOURCE_MANIFEST and SOURCE blocks.
```

## 11. Worked examples

These examples use aliases for the available Assignment 2 artifacts. They illustrate transformations already performed in the established workflow. They are not new answers to the assignment.

### 11.1 From criterion to architecture

**Supplied requirement**

```text
[A2-BRIEF:AC1.1] Explain probability distribution with examples.
```

**Stage 1 result**

| ID | Class | Requirement | Command word | Source |
| --- | --- | --- | --- | --- |
| R-1.1 | SOURCE STATEMENT | Probability distributions, with examples | Explain | `A2-BRIEF:AC1.1` |
| R-1.1-I1 | INTERPRETATION | The section must show what the distributions do, how they operate and why they fit different random variables, not merely define them | Explain | `A2-BRIEF:AC1.1` |

**Stage 2 result, condensed**

```text
AC 1.1 Probability distributions
Introduce: define a probability distribution and connect it to a random variable.
Explain: Bernoulli, binomial and normal distributions, including parameters and assumptions.
Evidence/worked material: one concise example of each distribution.
Conclusion: explain how the three differ and why each fits a different variable or situation.
Boundary: do not turn PMFs, PDFs and CDFs into extended independent sections.
Links: R-1.1, R-1.1-I1.
```

The boundary is an interpretation of the required depth and word budget, not a quoted brief requirement.

### 11.2 From architecture to atomic questions

The approved Assignment 2 architecture allocated AC 1.1 a maximum of 240 words. Stage 5 transformed it into:

| ID | Question | Maximum | Requirement link |
| --- | --- | ---: | --- |
| 1.1.1 | What is a probability distribution, and how does it relate to a random variable? | 45 | R-1.1 |
| 1.1.2 | How does a Bernoulli distribution operate in one concise worked example? | 50 | R-1.1 |
| 1.1.3 | How does a binomial distribution arise from repeated Bernoulli trials in one concise worked example? | 55 | R-1.1 |
| 1.1.4 | How does a normal distribution operate in one concise probability or standardisation example? | 50 | R-1.1 |
| 1.1.5 | Explain how the Bernoulli, binomial and normal distributions differ in the variables and situations they represent. | 40 | R-1.1-I1 |

Mechanical checks can confirm that the identifiers are unique and that the maxima total 240. A human must still judge whether the questions adequately elicit an explanation.

### 11.3 From question to evidence cue and checked source mapping

**Stage 6 cue**

```text
2.3.3 How are the test statistic and p-value obtained in the worked example?
Citation required: use a statistics text for the test procedure and authoritative statistical guidance for p-value interpretation.
```

**Stage 7 mapping from the supplied Assignment 2 source index**

```text
S01 supports 2.3.1-2.3.5 for core hypothesis-test procedure.
S06 supports 2.3.3 and 2.3.5-2.3.7 for correct p-value interpretation.
Use limit: S06 is not the sole source for confidence-interval computation.
```

This mapping is faithful because the source index supplies both the supported question IDs and the use limit. If only the title "Statement on Statistical Significance and P-Values" had been supplied, the model would have to mark the detailed mapping `UNVERIFIED`.

### 11.4 Missing evidence

**Input:** a scaffold asks for the strengths of a named method, but the packet contains only the assignment brief and no source text.

**Correct output:**

```text
Citation required: use a peer-reviewed method paper or advanced statistics text.
UNRESOLVED GAP: no checked source or supporting passage was supplied, so no source ID is mapped.
```

**Incorrect output:** inventing an author, year, title or page range, or mapping a plausible-looking source from memory.

### 11.5 Boundary with editing

**Input:** an author answer says `[HELP NEEDED: I understand the distinction but cannot phrase it]`.

**Correct reverse-scaffolding action:** preserve the note in the answer template and report that it is a possible input to a separately activated editing workflow.

**Incorrect action:** write the missing paragraph during Stage 8 or silently replace the note.

## 12. Quality checks

### 12.1 Traceability checks

- Every source statement has at least one valid supplied anchor.
- Every interpretation links to the source statement from which it follows.
- Every requirement maps to at least one architecture element.
- Every architecture element maps to at least one scaffold question or is explicitly identified as non-question front matter.
- Every scaffold question maps back to a requirement or an approved proposed addition.
- Every source mapping points to existing source IDs and question IDs.
- No output cites an anchor absent from the source packet.

### 12.2 Coverage and depth checks

- All learning outcomes and assessment criteria are present.
- Each command word is preserved.
- The final question for each criterion elicits the required kind of conclusion or judgement.
- Worked examples and calculations required by the brief appear in the scaffold, not only in an appendix plan.
- Analysis and evaluation are not reduced to description.
- No criterion is satisfied only by an unsupported assertion.

### 12.3 Question quality checks

- Stable ID is unique and correctly nested.
- One intellectual task is the norm.
- A compound worked procedure is split into ordered steps unless keeping it together is essential.
- The wording does not reveal a model-written answer.
- The maximum is plausible for the task.
- The question can be understood without earlier chat history.

### 12.4 Evidence checks

- Every question has exactly one current evidence cue.
- Definitions, methods, assumptions, empirical claims and current capabilities are flagged for evidence.
- A judgement that relies on earlier evidence names the relevant question IDs.
- A source is mapped only to claims supported by supplied text.
- Complete references contain only verified fields.
- Quotations exactly match supplied text and retain their location.
- `UNVERIFIED` and `UNRESOLVED GAP` items are not counted as covered.

### 12.5 Arithmetic and limit checks

- Question maxima equal their section maximum.
- Section maxima plus introduction and conclusion equal the allowed main-text total.
- Character count is measured on the exact handoff before dispatch.
- Attempt count never exceeds two for the user turn.
- Partial packets and outputs are explicitly labelled.

### 12.6 Workflow-specific failure signatures

| Failure | Detection |
| --- | --- |
| Drafting disguised as scaffolding | Questions contain full explanatory claims or the output contains answer paragraphs |
| Requirement laundering | A generic academic convention appears as a `SOURCE STATEMENT` without an anchor |
| Command-word flattening | `assess`, `evaluate` or `critically analyse` sections end with descriptive prompts only |
| Source hallucination | Reference data or locations do not occur in supplied inputs |
| Topical rather than evidential mapping | Source is linked because its title is related, with no supporting passage |
| Silent scope loss | A criterion or over-limit portion disappears without `INCOMPLETE` status |
| Editing leakage | Existing prose is rewritten or completed without separate activation |
| Self-verification | The only evidence of correctness is the generating model's statement |
| Attempt-budget evasion | Extra calls are described as chunks, retries or continuations in the same user turn |

## 13. Acceptance cases

### AC-RS-01: Complete brief to approved scaffold

**Given:** a complete brief, specification, word count and referencing rules within the limit.
**When:** the user explicitly requests Stages 1 through 8 one stage at a time and approves checkpoints.
**Then:** every stage produces its separate artifact, all IDs remain traceable, word sums are exact, every question has an evidence cue, and the final template contains no drafted answers.

### AC-RS-02: Imported architecture

**Given:** the user says Stage 2 was completed elsewhere and supplies it with the authoritative sources.
**When:** Stage 3 is requested.
**Then:** the workflow audits the imported architecture without rerunning Stage 2, records its imported status, and does not create Stage 5 until blocking findings are resolved.

### AC-RS-03: Ambiguous command word

**Given:** two authoritative documents use different command words for the same criterion.
**Then:** both anchors are reported, the affected depth decision is an `UNRESOLVED GAP`, and the workflow stops that branch for author clarification.

### AC-RS-04: Missing word count

**Given:** the task and criteria are supplied but no word count is present.
**Then:** Stages 1 to 3 may proceed if otherwise supported, the missing count is recorded, and Stage 4 is blocked rather than inventing a total.

### AC-RS-05: Citation plan without downloaded references

**Given:** an approved Stage 5 scaffold but no checked references.
**Then:** Stage 6 supplies evidence types and research directions, but no actual author, year, URL or source ID is invented.

### AC-RS-06: Source title without supporting passage

**Given:** a bibliographic title and abstract but no passage supporting a detailed claim.
**Then:** broad relevance may be noted, detailed question mapping is `UNVERIFIED`, and the criterion is not marked evidentially complete.

### AC-RS-07: Over-limit material

**Given:** the exact serialised handoff would exceed 12,000 characters.
**Then:** no silent truncation occurs; the coordinator identifies the excess, asks for a bounded scope or later user turn, and any processed subset is `INCOMPLETE` with explicit omissions.

### AC-RS-08: Second failed attempt

**Given:** Attempt 1 fails a required output check and Attempt 2 also fails.
**Then:** the coordinator stops, returns the best safe partial artifact as `INCOMPLETE` or `BLOCKED`, lists failed checks and does not make a third specialist call.

### AC-RS-09: Editing requested implicitly

**Given:** an existing essay is attached with a request only to reverse scaffold it.
**Then:** the essay is not rewritten. The workflow may use it only if the user has identified it as authorised context, and any editing requires a separate explicit request.

### AC-RS-10: Proposed new topic

**Given:** the model believes an extra topic would improve the report but the brief does not require it.
**Then:** it appears separately as `PROPOSED ADDITION`, carries no false source anchor and is excluded from the approved scaffold until the author accepts it.

### AC-RS-11: Partial later-stage artifact

**Given:** a question scaffold omits one criterion.
**When:** Stage 6 is requested.
**Then:** the omission is reported; evidence cues may be added to existing questions, but status remains `INCOMPLETE` and Stage 8 cannot be called complete.

### AC-RS-12: Separate editing handoff

**Given:** an approved scaffold, completed author answers and an explicit later request to edit.
**Then:** reverse scaffolding ends; the coordinator invokes the essay-editing workflow separately, passes only authorised inputs, preserves originals and saves edited text and notes separately.

## 14. Proposed implementation notes

Everything in this section is proposed, not an established workflow requirement.

1. Add a dedicated OpenCode specialist profile using the existing Qwen3.5 4B document model and the prompt in Section 10.
2. Make the coordinator run a deterministic preflight validator before delegation.
3. Store stage state in a small manifest containing artifact paths, approvals, source hashes, attempt count and completion status.
4. Add deterministic validators for ID uniqueness, referential integrity, allowed content-class values, evidence-cue coverage, word-budget arithmetic and handoff character count.
5. Keep source acquisition in the coordinator or client because the document profile has no tools.
6. Add fixture-based tests using the Assignment 2 AC 1.1 and AC 2.3 examples in this specification.

These proposals must preserve current serial execution, limits, permissions and depth-one delegation.

## 15. Unresolved decisions

The following decisions cannot be established from the available repository files in this workspace and should be resolved during implementation review:

1. the exact OpenCode profile filename and registration point;
2. whether the 12,000-character limit counts the installed specialist prompt or only the delegated payload;
3. the repository's preferred schema and storage location for stage manifests;
4. whether author approval is represented only in conversation state or persisted in an artifact;
5. whether Stage 9 remains part of this specialist or is implemented as a coordinator-only arithmetic operation; and
6. the exact user-facing activation phrases, if the project requires a fixed command rather than intent recognition.

None of these decisions permits changing the substantive workflow or relaxing its boundaries.

## 16. Next implementation step

Review this specification against `docs/ESSAY-EDITING-SPECIFICATION.md`, `docs/ESSAY-EDITING.md`, `docs/WORK-AGENT.md` and `docs/MODEL-TEAM-AND-HANDOFFS.md`. Resolve the six decisions above, then implement the deterministic Stage 0 preflight and acceptance fixtures before adding the specialist profile. Do not alter model configuration until that review confirms the existing Qwen3.5 4B profile can be reused unchanged.
