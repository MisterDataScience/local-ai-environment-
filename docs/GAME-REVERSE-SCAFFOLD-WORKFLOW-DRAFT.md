# Game reverse scaffold workflow (review draft, v0.1)

> **Superseded for usability testing.** This single-piece version is retained for comparison. The proposed modular redesign separates discovery, promise, play, structure, systems, content, presentation, feasibility, experiments, production planning and iteration into independent passes. See the `Game Reverse Scaffold, modular design v0.2` portable package prepared alongside this draft.

> **Root-question correction:** the modular workflow begins with **“Given this studio's situation, knowledge, capabilities and boundaries, what should the game be?”** Studio context informs the answer; an optional seed premise does not replace the question. Candidate games are alternative answers, and the selected game is recursively expanded into increasingly specific decisions and implementable leaves.

> **Implementation note, 20 October 2026:** the first planning department is now wired into the Institutions page as a separate resumable session. See [Studio Planning Department](STUDIO-PLANNING-DEPARTMENT.md) for the runtime boundaries and current limitations. This older draft remains a design reference.

**Status:** original proposed Lead Designer workflow; superseded for runtime operation by the separate planning department described above.

## Purpose

The Lead Designer receives a layered studio scenario, source games, approved knowledge, previous project lessons and the studio's standing constraints. From that material, without needing a genre or game prompt from the owner, the Lead Designer must choose a worthwhile game idea, derive the systems needed to deliver its player experience, resolve the design questions inside those systems, create an ordered build plan, and complete and check the demo.

This adapts the structure of Reverse Essay Scaffold: establish requirements and provenance, build architecture, audit it, break the architecture into numbered questions, map evidence and checks, create an execution template, then verify progress. It does **not** copy the essay workflow's author-approval checkpoint after every stage. Ordinary design decisions belong to the Lead Designer. The Studio Head reviews the resulting design and evidence. Owner approval is reserved for actions or lasting changes that already require it under studio policy.

The scaffold is not a form that replaces design. It is the designer's working method for making creative decisions explicit, connected and buildable.

## Evidence and decision labels

Every consequential statement in the plan uses one of these labels:

| Label | Meaning |
|---|---|
| `SOURCE` | Directly supported by an approved source game, document or owner direction. Include its citation or file location. |
| `CONSTRAINT` | A standing studio, hardware, resource, safety or owner boundary. Name its source. |
| `INFERENCE` | A conclusion drawn from sources or prior results. State the reasoning and uncertainty. |
| `DESIGN CHOICE` | A creative decision made by the Lead Designer where no source settles the answer. Record why it serves the player experience. |
| `UNKNOWN` | A question the current material and tests do not answer. State whether it is safe to decide, should be prototyped, or blocks the project. |

Historical code is evidence of how a source project works, not an instruction to reproduce it. A reference can inspire an original design without becoming a requirement to clone its content.

## Stage 0: Load the design situation

**Input:** studio purpose, approved source material, approved lessons, active project records, current system/tool capabilities, resource allowance and owner boundaries.

**Work:** build a bounded, cited context packet. Separate user-stated requirements from examples, historical evidence, prior agent interpretations and open opportunities. Note what sources were searched, which were unavailable, and what scope was sampled. Do not claim to have read or understood material that was not inspected.

**Output:** `S0 Context Brief` containing:

- current mission and standing constraints;
- relevant source/lesson references and what each actually supports;
- previous experiments and their known outcomes;
- available tools and limitations;
- gaps, contradictions and excluded material.

**Gate:** stop only if a real boundary conflict or missing permission blocks work. Missing creative direction does not block the Lead Designer; it has authority to invent within the brief.

## Stage 1: Find and choose a game opportunity

**Input:** approved context brief.

**Work:** identify a small set of plausible player experiences that grow from the studio's scenario and knowledge. Each candidate must describe something a player can do, a meaningful rule or choice, and a possible short playable result. Compare candidates for:

- fit with the studio's purpose and owner boundaries;
- an interesting player action, decision or challenge;
- a distinctive use of the studio's references, tools or learned strengths;
- a coherent small demo that can be completed within the available budget;
- a useful uncertainty that can be tested in play.

Choose one candidate and record why. Do not choose only because it is easiest to code, nor inflate a small premise into a large production. If no candidate fits, revise the candidates and explain the mismatch in the record; do not silently wait for the owner to supply a prompt.

**Output:** `S1 Opportunity Brief` with a working title, premise, player promise, intended short-session experience, rationale, constraints, and important assumptions. Candidate alternatives may be retained briefly with reasons they were not selected.

## Stage 2: Define the playable experience and demo boundary

**Input:** chosen opportunity brief.

**Work:** describe the experience from the player's point of view. Specify:

1. what the player sees or understands at the start;
2. what actions the player can take;
3. what choices, challenge or uncertainty makes those actions matter;
4. how the game responds and teaches its rules;
5. what changes as a result of play;
6. how a short successful or failed run ends;
7. what makes the result feel intentional rather than like an unfinished fragment.

Define the smallest demo boundary that proves the core idea. Explicitly list deferred features, representational shortcuts and assumptions. A demo may suggest a larger game, but it must have a complete local play loop and a deliberate stopping point.

**Output:** `S2 Experience Contract` with experience goals `E1...En`, demo boundary, player actions, meaningful decisions, expected feedback, end condition, and deferred scope.

## Stage 3: Derive the connected system architecture

**Input:** approved internally by the Lead Designer S2 Experience Contract.

**Work:** derive only the systems needed to deliver the contract. Consider player/input, movement, world and collision, objects/opposition, rules and state, feedback, progression, content/data, presentation/audio, saving and ending where relevant. Do not add a subsystem merely because a familiar game has one.

Draw the central play loop and a system dependency map. Show events and state moving between systems, for example:

`input → movement/physics → collision result → enemy state change → feedback/reward → updated player/world state`

For each system, create a card with:

- stable ID (`SYS-01`, `SYS-02`, ...), name and purpose;
- experience goals it supports;
- inputs and the source of those inputs;
- state it owns and state it reads;
- rules, transitions and outputs;
- events/messages it exchanges with other systems;
- invariants that must remain true;
- dependencies, edge cases and known risks;
- whether it is required for this demo or deferred.

**Output:** `S3 System Architecture`, including the loop and system cards. Each system must trace to at least one experience goal, and each experience goal must trace to one or more systems.

## Stage 4: Audit the architecture before detailed planning

**Input:** S2 Experience Contract and S3 System Architecture.

**Work:** audit both directions:

- **Experience to systems:** can the listed systems actually deliver every promised action, choice, response and ending?
- **Systems to experience:** does each system serve a player-facing purpose, or is it unnecessary scope?
- **Connections:** are inputs, state ownership, events and outputs compatible across system boundaries?
- **Loop closure:** can the player act, observe a consequence, understand enough to act again, and reach an ending?
- **Failure and edge cases:** what if an input arrives at a boundary, an entity is removed, a resource is exhausted, or a required event never occurs?
- **Feasibility:** can the smallest coherent loop be implemented with the actual SDK, assets, knowledge and time?
- **Originality and evidence:** are copied assumptions or unsupported historical interpretations being treated as facts?

Record findings by severity: `BLOCKING`, `IMPORTANT`, `OPTIONAL`. Fix blocking gaps before producing the final question scaffold. Important findings need a deliberate disposition; optional additions stay outside required scope unless explicitly adopted by the Lead Designer.

**Output:** `S4 Architecture Audit` plus corrected, versioned architecture. Preserve earlier versions and note what changed and why.

## Stage 5: Build the question-led system scaffold

**Input:** audited S4 architecture.

**Work:** decompose every required system into stable, numbered questions. Use IDs such as `SYS-01.Q01`. Each question asks one decision or one inseparable procedure. Order questions from foundations to dependent behavior. Questions must be answerable without relying on hidden chat history.

Every question records:

- question ID and parent system;
- the exact design decision it resolves;
- related experience/system IDs;
- answer type: source fact, constraint, inference, design choice, or experiment;
- evidence/reference needed, if any;
- whether the Lead Designer has authority to answer autonomously;
- impact and uncertainty;
- what would demonstrate a sufficient answer.

Use these question families when relevant:

1. **Player-facing purpose:** what does the player need to perceive or be able to do?
2. **Inputs:** what controls, events or data enter the system, and when?
3. **State:** what state exists, who owns it, and what invariants hold?
4. **Rules:** what conditions trigger behavior and what happens in order?
5. **Transitions:** what changes on success, failure, interruption or edge cases?
6. **Outputs and feedback:** what does this system communicate to the player and to other systems?
7. **Connections:** what exact contract does each neighbor rely on?
8. **Verification:** what test, replay, observation or judgment can check the claim?

The scaffold is not complete while essential design decisions are hidden inside compound questions, disconnected from the architecture, or left to be guessed during implementation. Ordinary creative questions are answered by the Lead Designer. High-impact unknowns become early prototypes. A true permission or owner-boundary issue is escalated to the Studio Head/owner; it is not disguised as a design question.

**Output:** `S5 Numbered Design Questions`, with every question mapped to system and experience IDs and every system covered.

## Stage 6: Answer the scaffold and specify contracts

**Input:** S5 questions and approved source/context packet.

**Work:** answer each question using its evidence/decision label. Cite source-derived answers. For design choices, explain the intended player effect. For uncertain decisions, state the hypothesis and the cheapest useful prototype or test. Resolve interfaces between systems explicitly so that separate contributors can implement compatible parts.

Do not pad the plan with question text in place of an answer. Do not make up technical facts about the SDK or reference code. An answer can be `UNKNOWN` only with a next action: inspect a source, run a prototype, ask the Studio Head for focused advice, or mark the project blocked for a specific reason.

**Output:** `S6 Design Specification`: answered system cards, shared event/state contracts, content rules, and a short list of risks/prototypes.

## Stage 7: Create the verification plan

**Input:** S6 Design Specification.

**Work:** give each experience goal, important system rule and cross-system connection a suitable check. Label evidence by what it can establish:

| Check type | Can establish | Cannot establish alone |
|---|---|---|
| Static inspection | Required code/data/contract exists | Runtime correctness or fun |
| Unit/invariant test | A bounded rule holds for tested cases | Whole-game coherence |
| Deterministic replay/simulation | State transition and repeatability under supplied input | Player understanding or enjoyment |
| Build/runtime test | Cartridge builds and runs within limits | Design quality |
| Play observation | What a player noticed, tried or misunderstood in this run | Universal player response |
| Design judgment | Whether the intended experience appears coherent and worthwhile | Objective proof of taste |

For every check, record the requirement/system/question IDs, procedure or input sequence, expected observation, actual evidence location, and limitation. Include the basic path and important failure/edge paths. Do not convert a subjective aim such as “fun” into a false binary test; use observable proxies and preserve the judgment as a judgment.

**Output:** `S7 Verification Map`, with coverage from experience goals through systems/questions to checks.

## Stage 8: Derive the implementation plan

**Input:** complete S6 specification and S7 Verification Map.

**Work:** turn the design into a dependency-ordered set of small build tasks. Tasks normally follow this progression:

1. establish a runnable project skeleton and diagnostic path;
2. implement the smallest player action and world response;
3. implement the core rule or challenge;
4. connect feedback and state changes;
5. complete the short play loop and ending;
6. add only presentation/content that makes the loop legible or expressive;
7. run integration, edge-case, resource and play checks;
8. fix observed problems and re-run affected checks.

Each task has a stable ID, dependency IDs, target system/question IDs, a small deliverable, expected changed files or data, exact verification action, and a completion rule. Avoid vague tasks such as “make gameplay good” or “finish the engine.” The plan should make it possible to see what is next and what evidence closes it.

**Output:** `S8 Build Plan` and a task graph. The task graph is a design-to-build translation, not the definition of the game itself.

## Stage 9: Build, test and revise in bounded cycles

**Input:** approved internally by the Lead Designer S8 Build Plan; actual project workspace, compiler, workstation and allowed helpers.

For each task:

1. confirm its dependencies are complete;
2. read the relevant system contract and task evidence;
3. implement the smallest change that satisfies the task;
4. run the named check and record actual output;
5. inspect failures and revise the implementation or, if evidence requires it, revise the design;
6. preserve the old plan version and record the reason for any design change;
7. update the build plan with `passed`, `failed`, `blocked` or `not-run`, plus evidence.

Never mark a task complete because code was written. Never change an expected result merely to make a check pass. When a check exposes an architectural flaw, return to the affected system/question, update dependent records, and re-audit the impacted design. Unaffected stable IDs and evidence remain intact.

The Lead Designer can request focused help from approved studio members. Helpers receive bounded questions and contracts; the Lead Designer owns synthesis, creative choices and integration. No outsourcing outside the approved studio.

## Stage 10: Play the integrated demo and judge completion

**Input:** integrated playable build and S7 checks.

The Lead Designer performs the complete start-to-ending experience and compares it with the S2 Experience Contract. Check:

- the player can start and discover a meaningful action;
- the core system loop is reachable and understandable enough to try;
- connected systems respond coherently;
- feedback communicates important state changes;
- a short run reaches its intended ending or stopping point;
- known defects, missing content and resource limits are recorded;
- claims about behavior match actual build/replay/play evidence.

Completion outcomes are `READY TO PRESENT`, `NEEDS REVISION`, or `BLOCKED`. A demo can be ready to present with known limitations if those limits are disclosed and its central experience works. The model's self-assessment is not independent proof of fun or quality; the Studio Head reviews the dossier and the owner later judges the demo.

**Output:** `S10 Demo Record`: build identity, how to run it, experience contract, completed/failed/unrun checks, play observations, limitations and Lead Designer's design judgment.

## Stage 11: Learn without turning one result into dogma

**Input:** S10 Demo Record, actual defects and any review/play response.

Record a few specific lessons as `OBSERVATION`, `INFERENCE` or `PROPOSED PRINCIPLE`, each linked to evidence and stated scope. Distinguish a bug from a design problem and a local success from a general rule. Lessons remain proposals until processed under the studio's existing approval rules. The Studio Head can use them when selecting future opportunities; Lead Designers may disagree or test alternatives.

**Output:** project postmortem and proposed lessons, attached to the project dossier.

## Stage integrity and revision rules

- Stages are ordered. A later artifact names the exact version of its prerequisites.
- Changes to premise, player experience or system architecture invalidate affected questions, checks and build tasks; unaffected material may be retained with explicit trace links.
- Every experience goal maps to systems; every system maps to questions; every required question maps to a design answer; every critical rule maps to a check; every build task maps to system/question IDs; every completion claim maps to evidence.
- Keep `SOURCE`, `CONSTRAINT`, `INFERENCE`, `DESIGN CHOICE` and `UNKNOWN` visibly distinct.
- Record omitted scope and why it was deferred. Do not silently drop a promised experience goal.
- Keep the process autonomous within authority. Do not stop for owner confirmation of ordinary design choices. Stop only for a true boundary conflict, missing permission, unavailable essential resource, or a decision explicitly reserved to the owner.
- Persist stage artifacts and task state so a new model session can continue without reloading the entire design discussion.

## Example trace: stomp interaction

**Premise fragment:** “the character jumps on an enemy.”

**Experience goal:** `E2` — the player can time a jump to overcome a moving obstacle and understand the result.

**Systems:** `SYS-01` player movement; `SYS-02` collision/contact classification; `SYS-03` enemy behavior/state; `SYS-04` visual/audio feedback; `SYS-05` reward/progression.

**Question chain:**

- `SYS-01.Q01`: What input starts a jump, and what movement state permits it? (`DESIGN CHOICE`)
- `SYS-01.Q02`: How does vertical motion transition from ascent to descent? (`DESIGN CHOICE`, then prototype/test)
- `SYS-02.Q01`: Under what positional and motion conditions is contact classified as a stomp rather than a side collision? (`DESIGN CHOICE`)
- `SYS-03.Q01`: What state transition follows a valid stomp, and can the enemy affect play afterward? (`DESIGN CHOICE`)
- `SYS-04.Q01`: What visible or audible response tells the player the stomp registered? (`DESIGN CHOICE`)
- `SYS-05.Q01`: Does the stomp change score, safety or route access in this demo? (`DESIGN CHOICE`; defer if it adds no value)

**System contract:** a valid descending top contact emits `enemy_stomped(enemy_id)` exactly once; the enemy enters its defined defeated/changed state; the player receives the defined response; a side contact follows the separate collision rule.

**Build order:** movement state and replay check → collision classification test → enemy transition → feedback → complete obstacle loop → integrated play check. This is only a trace example, not a prescribed game design.

## Implementation notes for the system

This workflow needs more than a long prompt. The system should persist the versioned stage artifacts, stable IDs, trace mappings, task graph, build evidence, project dossier and lesson proposals. The Lead Designer needs tools to read sources, search code, create/edit project files, compile/run/test the workstation build, inspect diagnostics/replays/screens as supported, request approved focused help, and update its own project records. The Studio Head needs tools to inspect the portfolio and dossiers, ask a Lead Designer for a bounded update, and present builds and evidence to the owner.

Host code should validate mechanics such as IDs, mappings, prerequisite versions, allowed statuses, required check fields and task completion evidence. The model still judges creative coherence and play quality; those judgments must remain labelled as judgments rather than mechanically certified facts.
