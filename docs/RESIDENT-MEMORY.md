# Resident memory and starting maps

Each resident starts with its approved identity and instructions, followed by a
compact, owner-curated map of what it knows and where to look. The same map is
supplied in Commons and in ordinary Captain worker assignments. It is not a list
of whichever three memories happen to be newest.

| Layer | What the resident receives | How to use it |
| --- | --- | --- |
| Identity and instructions | Existing approved specialist profile and permissions | Defines its role and working habits |
| Fast-access memories | Up to three deliberately selected own-memory summaries | Keep important approved lessons readily available |
| Deeper-memory glossary | Up to eight named memory references or memory-search topics | Follow a topic when the current work needs its deeper history |
| Preferred sources | Up to six named Library/Archive documents or collection areas | Find workflows, examples and source material relevant to its specialism |

A humaniser's map could name “Editing principles”, “Previous editing experiences”,
“Humaniser workflow” and “Writing examples”. Its workflow entry can open an exact
approved Library document; its examples entry can search a permitted Archive
collection. This release does not invent a humaniser profile, manufacture a
workflow, or guess a file location. You select an existing approved resident and
real approved references or permitted collection areas.

## Normal use: the system prepares, you approve

The five baseline residents are created automatically. You do not need to create
agents, invent tags, write their prompts or assemble maps before using the system.

Use the Captain normally in Build. It reuses existing approved residents. When
recurring work warrants a durable specialist, the Captain can prepare a complete
creation proposal: identity, parent role, instructions, tags, intended active or
experimental state, and reason. It can also propose a revision or retirement.
These are pending proposals, not new inference processes. No agent can approve
its own creation, profile change or map.

Approved memories, material pointers and matching Library document titles also
prepare map suggestions automatically when the owner dashboard opens or refreshes.
The host retains valid existing owner choices, proposes suitable procedure or
revised-belief memories for fast access, indexes other own memories, and suggests
relevant source references. This preparation uses bounded local bookkeeping, with
no extra model calls and no background inference. It is a simple candidate policy,
not a claim to understand every document's meaning. The Captain can propose a
more deliberate complete map when needed.

The ordinary owner flow is:

1. Do your work or open a Commons gathering. Existing residents already work
   without a configured map.
2. Review any proposed durable memories or material in **Final review inbox**.
   Only approved inputs can become suggestions for a lasting map.
3. In **Prepared resident changes**, read the proposed profile or complete map,
   its reason, scope and exact content. Approve or reject it. No manual map entry
   or terminal command is required.
4. The host creates/updates the approved resident or publishes the approved map.
   Approved active specialists become available to normal routing and subsequent
   Commons gatherings. New assignments receive their updated starting context.

Open `Village Commons.command` for owner review; opening it does not start a
Commons session or any inference. Pause/finish a gathering before final review.
Rejected identical suggestions are not repeatedly presented. Pending proposal
content expires after seven days. Existing residents keep working while you leave
proposals undecided. There is no automatic publication, grant expansion, extra
model loading or increase to concurrency.

Commons residents still cannot spawn agents, delegate or outsource. Persistent
specialist proposals come from the ordinary Captain, outside Commons. System map
preparation can follow a Commons memory approval, but approval of the memory and
approval of its new starting-map placement remain separate decisions.

## What the agent actually sees

The specialist packet contains its existing profile, scoped lessons and a
`personal` section:

- `fast_access`: the selected memory summaries, names and applicability.
- `glossary`: short directions to specific deeper memories or scoped search topics.
- `preferred_sources`: named document/Archive references or collection-search areas.
- `navigation`: instructions explaining how to follow the map and retrieve only
  what the current work needs.
- `map_revision`: the approved starting-map revision supplied to the agent.

Every entry includes a `map:ENTRY NAME` reference. The resident follows it with
`village_read`; in Commons it uses `read_source`. The host resolves the current
approved entry for that resident and either reads its exact target or executes
its approved query in the designated area. A Library-area lookup searches
approved Library documents. An Archive-area lookup searches Archive messages.
A personal-memory topic searches only that resident's own approved memories.
Search results supply exact citations for further reading.

This prevents a preference for “the Humaniser workflow area” turning into a
full Library dump in every prompt. A preference guides reading; it does not
force the resident to consult every source on every task. Fast-access claims
are bounded summaries, and full approved memories remain available by reference.

The resident can also use ordinary `village_search`/`village_read` or the Commons
search actions for relevant permitted material beyond its map. A map is a guide,
not the entirety of its knowledge. If no map has been approved, no recent memories
or recently approved pointers are automatically substituted; deeper search still
works. The model's actual choices and usefulness need native acceptance.

## Separate approvals and permissions

Approving a memory makes it a durable, searchable own-memory record. It does not
pin it into the resident's starting context. Approving a Library document does
not add it to a resident's map. Pinning a memory, adding a glossary topic, adding
or changing a preferred source, and clearing the map require a separate final
owner approval of the complete revised map.

Only the authenticated owner controls can write maps. Residents cannot call a
map-approval action or update their own persistent directions. Existing approved
legacy material pointers remain in the approved store and owner inspection, but
they are not automatically inserted into a new map. Use their actual target
citations when choosing preferred sources.

Host checks enforce all of the following:

- Personal memory targets must belong to that exact resident, be approved and
  have live evidence. Another resident's experience cannot be pinned or indexed.
- Exact source targets must exist, be approved/active and be within current grants.
  Pending Commons drafts and proposals cannot be used as map targets.
- Area targets must name an existing permitted collection. A memory-search topic
  defaults to General unless you explicitly select other granted collections.
- Every map entry is filtered against the current request/session scopes. A
  private entry is absent from General context even when its resident has private
  grants. A guessed `map:` label cannot bypass this filter.
- Exact targets are bound to their reviewed content revision. Editing, deleting,
  withdrawing or reclassifying a target can hide the entry until you preview and
  approve a suitable updated map. Target changes between preview and approval
  reject the old digest. A concurrent map revision also invalidates that preview.
- An area entry refers to a collection and query, so it can discover material
  approved into that area later. It grants no access to unapproved material.

The map does not grant filesystem access, add tools, execute workflows, change
permissions, or make old source text authoritative. There is no embedding service,
external model call, semantic ranking or automatic map-writing background job.

## Inspecting and correcting memory

Use **Approved memories and documents** for the underlying memory claims,
evidence, current revisions, correction, withdrawal and deletion. Use **Resident
starting maps** for the resident's directions and their revision history. Both
operate without inference. In Commons, **Context supplied** records the actual
map directions and memory/source summaries supplied on that turn.

Correcting a pinned memory changes its binding, so the old fast-access entry is
withheld until you approve the updated map. Approved deeper memory search can
still find the corrected record. Source withdrawal also blocks dependent memory
retrieval. Clearing or editing a map does not retroactively erase context already
supplied to an active worker. Start a fresh worker assignment to inspect its new
starting packet; subsequent Commons turns rebuild their scoped context.

## Advanced: manual overrides

Manual editing is optional. To override a prepared map, open
`~/LocalAI-Automated/Village Commons.command`. You can edit maps without opening a
Commons gathering or running inference. FileVault must be On for Village access.

1. Open **Advanced: edit a resident map yourself** and select the resident.
2. Click **Load approved map**. Its current map and revision history are shown.
   A resident without a map begins with three empty layers.
3. Under **Fast-access memories**, click **Add entry**, name it, select one of
   that resident's approved memories and explain when it is useful.
4. Under **Deeper-memory glossary**, add a specific own memory or choose **Search
   my deeper memories**, give it a useful name and search words, and select the
   permitted memory collections to search. For example, “R plotting lessons”
   could search the resident's own records for “ggplot”.
5. Under **Preferred Library and Archive sources**, select an approved document,
   a Library area, an Archive area, or an exact citation from existing Village
   search. Area entries need search words. For example, name a Library area
   “Humaniser workflow” and search for “humaniser”, or select the exact workflow
   document if it has already been approved into the Library.
6. Click **Preview exact map**. Inspect the resident, references, scopes, selected
   memory claims, intended use and digest. Preview makes no persistent map change.
7. Pause/finish any Commons session and wait for active requests to drain. Click
   **Approve previewed map** to approve that exact content and revision.

Labels must be distinct across the whole map, with at most 60 characters each.
The combined navigation record is limited to 5,000 UTF-8 bytes, so the entry-count
limits are ceilings, not a promise that every field can be filled to its maximum.
Keep labels and directions short. Selective reading supplies the detail later.
The chooser lists the bounded owner inspection results; an older existing
reference can also be entered using **Advanced JSON editing**.

To remove an entry, use **Remove entry**, preview and approve. To clear the
starting map, remove all entries, preview and approve the empty layers. This
clears the current map without deleting deeper memories or its map revision
history. No map changes are made by merely editing the form or switching pages.


## Upgrade, retention and acceptance

The additive resident-memory schema migration from v1 to v2 runs on the next
explicit approved write or owner dashboard maintenance operation. It preserves approved documents, memories, pointers,
evidence and correction history. Ordinary memory reads do not manufacture a map. Dashboard maintenance may
initialize the proposal store, but only approval can publish a starting map. Unknown future versions are refused by the write path.
Migration failure rolls back the map tables and version change together.

Map revision history preserves prior approved directions. Removing a target or
clearing the current map does not purge that history, old session copies, downloads
or backups. The explicit managed-source forgetting workflow is a larger privacy
reset that does remove managed derivative stores and backups, with a durable
deletion ledger. Encrypted recovery is also included; see
[Founding and recovery](FOUNDING-AND-RECOVERY.md).

Developer acceptance checks are listed in [Village developer acceptance](VILLAGE-DEVELOPER-ACCEPTANCE.md).
They are not everyday setup instructions and do not mean you must build residents
or maps by hand. Real local-model behaviour and Mac installation remain unverified
on this authoring host. Implementation limits are tracked separately in
[Village implementation status](VILLAGE-STATUS.md).
