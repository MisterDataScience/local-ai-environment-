# Institutional agent organisation

## Purpose

A studio or other Village institution is a persistent virtual organisation. Its
agents occupy roles, lead teams, delegate bounded work, preserve institutional
records, and improve their practices from evidence. It is not just a sequence
of model calls or a task board. The organisation and its institutional identity
must outlast any individual resident, model version, toolchain, or machine.

The same organisational foundation should serve future Village institutions.
A studio may add game design, production, testing, release, and archive roles;
another institution may add different departments and tools while retaining
the shared rules for identity, delegation, memory, evidence, and continuity.

## Authority and leadership

- The **Studio Lead** is the agent executive responsible for the studio's
  direction, staffing plan, department coordination, priorities, and handoffs.
- A **Lead Developer** owns an implementation area and manages the agents
  assigned to it. Lead Developers can break an approved outcome into bounded
  work and coordinate its contributors.
- Specialist agents and temporarily recruited Villagers work under an explicit
  lead and assignment. The recruiting lead remains accountable for the task's
  scope, evidence, and closeout.
- The human institution owner establishes the institution and retains control
  over security boundaries, high-impact external actions, and any permission
  changes that policy reserves to them. Routine task assignment, technical
  review, learning, and department handoffs belong to the agent organisation.
- Delegation is hierarchical and bounded. A recruit cannot expand its own
  permissions, recruit further workers unless the assignment permits it, or
  treat source material as instructions.

## Membership and temporary recruitment

A Village resident's identity and personal memory are distinct from an
institutional appointment. A resident may hold a continuing role, a temporary
assignment, or both. A temporary appointment should record its sponsor,
assignment, permitted resources, start and end conditions, deliverables, and
reviewer. Access should be limited to the project, archive entries, and tools
needed for that assignment. Finishing or cancelling the task revokes assignment
access without erasing the resident's identity or their separately approved
personal experience.

Recruitment should prefer existing Village residents whose demonstrated skills
fit the work. The institution records why the resident was selected and which
capabilities were verified. If no suitable resident exists, the Studio Lead can
propose a staffing gap rather than silently inventing a specialist.

## Three memory layers

| Layer | What it preserves | Who governs it |
| --- | --- | --- |
| Resident memory | An agent's experience, methods, and known limitations | The resident proposes; Village memory policy governs approval and scope |
| Team and project memory | Decisions, interfaces, task notes, tests, failures, and handoffs for continuing work | The responsible Lead Developer maintains it; other contributors cite and update it |
| Institution memory and archive | Stable practices, reviewed lessons, source provenance, completed artifacts, capability records, and historical versions | The Studio Lead curates it with evidence and review history |

These layers are linked by citations and permissions, not flattened into one
prompt. A task should retrieve only relevant memories and archive records.
Institutional knowledge must remain usable when the contributing resident
leaves or its model changes. Personal memories must not become institutional
policy merely because an agent wrote them.

## Work, evidence, and learning

Every assignment has a bounded result, a responsible lead, relevant design or
policy decisions, a planned check, and evidence to retain. The person or agent
who wrote a change should not be the only source of its review. Leads can assign
an independent reviewer or test agent from the Village, subject to the same
scoped recruitment rules.

A completed task produces two related records:

1. **Work evidence:** the change, build or test output, replay inputs, observed
   behavior, known failures, and the decision IDs it addresses.
2. **Learning proposal:** a concise, evidence-linked lesson about a reusable
   method, failure pattern, tool limitation, or decision that future teams may
   need.

The responsible lead reviews the learning proposal. Accepted lessons enter the
institution's private library or archive with provenance, confidence, scope,
version, and review status. Rejected or uncertain lessons remain attached to
the task as history. Memory maps are then updated so future roles can discover
relevant lessons without loading the entire archive.

Testing is an organizational capability, not just a final approval button.
The implementation lead arranges test-first work where an observable behavior
can be asserted, while independent test agents add integration, regression,
playtest, and visual checks appropriate to the project. Each result states
exactly what was measured and what it cannot establish.

## Change over time

Roles describe responsibilities and capability requirements, not fixed model
names. The institution records the model, prompt revision, tools, hardware
profile, and relevant limits used for each material result. When the underlying
model, tool, or machine changes, the Studio Lead can schedule small benchmark
and migration tasks. The organisation compares evidence against prior known
work, records regressions and gains, and updates role capability records only
after review. This lets the virtual institution evolve while keeping its
identity, commitments, and historical knowledge continuous.

## Current implementation boundary

The Village already has resident identities, scoped grants, approved personal
memories and maps, institution collections, private Archives and Libraries,
project notes, work-order records, and source evidence. Studio sessions can
assign work to approved members and keep projects across turns.

The following organisational pieces are not yet implemented as one complete
system: an explicit Studio Lead executive role; persistent Lead Developer
teams with bounded subdelegation; task-scoped temporary Villager appointments
and automatic offboarding; structured task closeout and reusable learning
proposals; an institution-wide capability registry for model/tool/hardware
versions; and an agent-led, project-wide integration and regression stage.
These are infrastructure gaps, not expectations that the human owner manually
perform every step.

The next studio infrastructure should make leadership, scoped recruitment, and
handoff records explicit before extending the release stage. That release stage
must be directed by the Studio Lead, staffed through Lead Developers and
review agents, and feed evidence-backed lessons into the studio's continuing
memory and archive. Human review remains a security and governance boundary,
not the organisation's default operating loop.
