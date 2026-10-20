# Studio planning and documentation department

The planning department turns the studio's mission and approved lessons into a
reviewed design tree. It runs before implementation and does not edit project
files, build a game, run a machine, publish knowledge, or start a coding session.
The owner does not need to choose a genre or supply a game prompt.

## How the design tree grows

1. Four design roles propose different game opportunities.
2. The Lead Designer selects one, records why it fits the studio, and opens the
   tree with five to seven broad questions under **“What should this studio
   make?”**
3. A department role answers one question. It either splits the question into
   two to five necessary, narrower questions, or produces one bounded design
   deliverable for the Lead Designer.
4. A separate Design Auditor turn checks the answer before it is accepted. The
   review records five checks: contract met, specific, traceable to the game
   promise, complete for this stage, and checkable. A failed review must name a
   repair; repeated failure blocks the run instead of silently passing it.
5. Host checks validate the tree structure and prerequisite IDs. A final review
   checks the top-level branches together for missing coverage or conflict.

There is no minimum depth, fixed fan-out, or 1,000-leaf requirement. A branch
stops when its design question has a complete, bounded result. It splits further
when consequential decisions remain unresolved. The result may have hundreds or
thousands of nodes when the design needs them, but the count is not treated as
evidence of quality.

## What a design leaf contains

A leaf is work the Lead Designer can complete, not a coding ticket. It names one
deliverable, the instruction for producing it, its inputs and outputs, the IDs
of any earlier design decisions it depends on, a sufficiency check, and evidence
to retain. For example, a leaf could require a movement specification with a
state table and worked edge cases. The sufficiency check can verify that those
parts are present and agree with the parent design decision.

The leaf's decision is then available to the later implementation workbench.
This planning release does not yet turn every design leaf into a separately
scheduled code task or execute those tasks. Implementation remains a separate
stage.

Dependencies must refer to existing, audited design-decision leaves. Unknown,
self, duplicate, or unaccepted prerequisite IDs fail host validation. This
produces traceable prerequisites, but it does not yet schedule implementation
tasks in parallel.

## Starting and continuing a plan

Open **Institutions → Planning and documentation department → Start hands-free
game planning**. The job uses the existing local inference scheduler. It saves
each bounded turn and can pause and resume without loading the entire dossier
into one prompt. Open **Design dossier** to inspect the tree, review checks,
decision deliverables, dependencies, and source inputs.

Planning runs are mutually exclusive with other studio sessions in the same
institution. The job uses the installed local model and consumes computer time
and electricity. Increase the time or turn allowance only if a run stopped
because it reached that limit.

## How the roles operate

The four department roles and auditor use the same installed local Captain
model in separate, sequential turns. They are not four concurrently loaded
models. Separate role prompts and bounded packets help organize the work, but
the auditor is not an independent model and can share the generator's blind
spots.

## Checks and limits

Host validation can prove that required fields exist, question links are valid,
leaves have sufficiency checks, prerequisite IDs point to accepted decisions,
and the tree is complete and within its safety limit. The language-model review
judges whether the content satisfies its design contract; it cannot prove that
the game is good, fun, technically feasible, or free of subtle contradictions.
The final integration review receives a summary of every top-level branch,
while each node receives its own review. No player test or build is run by this
department.

## The next department in the studio line

The next planned stage is a **Design Integration and Production Planning
department**, between the Lead Designer's design tree and implementation. It
will not choose a different game or quietly fill gaps with new rules. It will
take the accepted dossier and produce an implementation package:

- bounded code, asset, and content tasks linked to the design decision IDs they
  implement;
- explicit input files, outputs, prerequisites, ownership, and acceptance
  evidence for each task;
- code checks, deterministic simulations, content inspections, or player tests
  chosen to match the claim being checked;
- a coverage check that every build-relevant design decision is implemented,
  tested, or explicitly deferred;
- a dependency graph that rejects missing references and cycles, then marks
  only prerequisite-ready tasks as runnable.

If this department finds an unresolved game rule, it returns that question to
the Lead Designer for a design decision before implementation. It does not ask a
coder to invent the rule.

This is an assembly line in the sense of clear handoffs and quality gates, not a
requirement to keep every resident occupied. The implementation scheduler can
run the ready work that fits the machine's concurrency limit. If no task is
ready, agents can wait; filling idle time with unrelated work would risk
fragmenting attention and context. Some implementation tasks can run in
parallel when their prerequisites are satisfied, while integration-dependent
tasks wait.

The first host stage of that middle department is implemented: `prepare_integration`
accepts only a completed, audited design job from the same institution, saves an
immutable versioned copy of its selected game, context, candidates, entire tree and
final review, and indexes every node with a source reference. `integration_report`
pages through the manifest, while `integration_node` retrieves one original node.
Repeated preparation of the same design job returns the same frozen copy. This
stage performs no model call and creates no implementation tasks. Node decision
statuses are deliberately unclassified until the next pass reviews them. The
existing design leaf is a specification request, not proof that its deliverable
has been produced or its rule settled.

The next saved stage now walks the frozen manifest one node at a time. The
Decision Mapper proposes cited rules and classifies each as settled, hypothesis,
deferred or open. A separate Design Auditor turn checks each proposal. A leaf's
instruction cannot be treated as its completed rule: the Lead Designer produces
that deliverable in a separate saved turn and the auditor checks it before the
node can advance. Audited open questions return to the Lead Designer, then the
same node is reviewed again. Repeated unresolved questions or review failures
block the job and remain visible in its report. Each accepted resolution adds a
new digest to the integration dossier's revision history; the frozen original
design job is retained. The host rejects unsupported quotes, invalid statuses,
missing references and incomplete node coverage. The result is a decision
ledger, not a list of coding jobs.

In the Institutions page, open a completed design job and choose **Start
decision inventory**. The job runs bounded saved turns on the installed local
model and can be paused and resumed. Open **decision ledger** for progress,
questions and the first page of classified decisions. The owner API supports
`prepare_integration`, `run_integration`, `integration_report`,
`integration_node` and `integration_decisions`. Reports are paged; no prompt
needs the entire game tree at once.

After the inventory completes, choose **Start system mapping**. The Systems Integrator assigns decisions to named gameplay systems in bounded batches. A system may span design branches, and one branch may contain several systems. A separate Design Auditor turn reviews each saved assignment. The host verifies exact coverage and derives cross-system links from explicit design prerequisites. If a missing or conflicting rule surfaces, it returns to the Lead Designer; an accepted answer versions the integration dossier and reruns inventory and system mapping.

When system mapping completes, choose **Start work-order planning**. The Production Planner processes one bounded batch of decisions in one accepted system at a time. It creates code, content, asset, experiment or integration work orders with design references, inputs, outputs, prerequisite decisions, responsible specialist, observable done condition, planned acceptance check and saved evidence. Hypotheses require a planned experiment. A deferred rule or work blocked by a deferred prerequisite is recorded explicitly. Checks are marked planned and are not represented as passed.

A separate Design Auditor reviews each work-planning batch. A missing or conflicting core rule returns to the Lead Designer, and any accepted design resolution invalidates the existing ledger, map and work orders before those stages run again. The deterministic handoff gate checks that every decision is covered by a work order or explicit deferral, all references exist, work orders do not depend on deferred decisions, and the derived task dependency graph is acyclic. The owner API adds `start_work_order_planning` and paged `integration_work_orders` reads. This stage creates a plan only; it does not execute checks or schedule implementation.

The Institutions page exposes the system-mapping and work-order start controls after each preceding stage completes, and the integration report shows the saved plan and gate result. Implementation-agent scheduling, including dispatching only prerequisite-ready work, remains the next stage. Actual local-model
planning quality and native Mac acceptance also remain unvalidated.
