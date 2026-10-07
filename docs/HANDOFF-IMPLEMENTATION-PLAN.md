# Handoff implementation status and next steps

Updated 2026-10-07. Target: 32 GB unified memory, one generative model at a time.
The first implementation now uses OpenCode, as agreed after feasibility review.
Open WebUI remains the general chat interface. Native Mac validation is pending.

## Implemented

1. **Verified artifact preparation and role profiles.** `model_team.py` defines
   the 4-bit 4B/9B/12B team and 8K/32K/16K context limits. The document profile
   shares 4B weights with a 32K context. `team_setup.py` checks Qwen manifest IDs,
   SHA-256 verifies and imports the coder GGUF, verifies backend metadata and
   records full installed digests. Known stock presets migrate once with a
   private backup; custom entries, credentials, timeouts and disabled-team flags
   survive reinstalls. Profile names cannot disguise an unknown model.
2. **Native OpenCode roles and routing.** Plan/Build use the 4B coordinator.
   Their instructions choose analyst/coder only when useful. Native task executes
   the selected specialist and returns to the parent loop. `/code`, `/analyse`
   and `/document` use direct native primary-agent commands. No duplicate agent
   loop, custom shell tools or hidden inference service was added.
3. **Bounded delegation policy.** `opencode-team.mjs` binds attempts to native
   explicit user messages. A durable ledger reserves at most two attempts per
   turn; one same-role retry requires a concrete failure. Replays, concurrency,
   reconnects, process restarts and compaction do not grant a fresh budget.
   Specialists cannot call tools or delegate. Task resumption and background
   delegation are disabled. Input/result envelopes are bounded and native
   implicit `@file` expansion is escaped. Results retain visible clipping notices.
4. **Memory and lifecycle.** All requests use the existing serial gateway.
   Outgoing weights/context profiles unload before the next profile starts;
   unload failure blocks it. Parent inference completes before child inference
   is queued. Gaming stays 4K context/1K output and excludes the work agent and
   specialists. Normal/Max output ceilings remain 4K/8K, bounded to half context.
   Gateway mode epochs and instance IDs invalidate stale work-agent bindings.
5. **Native startup and acceptance gates.** Task is denied in base configuration
   and enabled only by successful plugin initialization. Startup inspects effective
   native agent permissions. The installer exercises each text preset, context
   rejection and cutoff behavior, then actual OpenCode analyst/coder handoffs and
   parent resumption. It checks child model identity, no child tools and a final
   parent answer. These Mac checks have not been run in the authoring environment.
6. **Packaging and authoring tests.** Policy, setup and role modules are included
   in the installer and acceptance fingerprint. Tests cover migration, permissions,
   artifacts, accounting and real gateway HTTP with simulated inference.

## Deliberate scope boundaries

Routing currently uses the coordinator's native task selection and explicit
commands. It is not a separately scored deterministic semantic classifier.
Specialists return analysis/proposed code; the parent uses native file/shell
approvals to apply work and execute tests. Direct specialist agents also have no
tools. Thinking is off by default for predictable output budgets; changing that
requires checking the exact model's native template and behavior.

WebUI has no delegation adapter in this release. Its built-in delegate_task uses
the current model, so merely enabling it would not implement this team. Its global
compaction trigger remains conservative for the smallest profile. OpenCode has
per-model context/input/output budgets. Image/audio input and visual document
reading remain unimplemented. Buffered responses and optional native task/session
inspection remain; no extra monitoring model runs.

## Next validation and implementation order

1. Run the updated full installer on the Mac. Resolve any failing artifact,
   metadata, tool-format, context, native permission or handoff acceptance before
   treating the team as operational. No model fallback or context protection
   bypass occurs when a check fails.
2. Measure cold/warm 4B -> 9B -> 4B and 4B -> coder -> 4B time, memory pressure,
   swap and long-context accuracy with normal background applications. Compare
   direct vs routed task quality. Reduce profile contexts if necessary. Claims
   about M6 speed or usable maximum context remain unmeasured.
3. Validate saved sessions, errors, cancellations, explicit user retries,
   compaction replay, permission denial and startup after a failed plugin load
   against the pinned native executable. The policy tests simulate those hooks;
   they do not replace this native validation.
4. Tune routing only using observed wrong choices or unnecessary handoffs.
   Keep the two-attempt limit and foreground lifecycle. Add lightweight timing
   reporting only if useful, without another inference call.
5. Add a trusted WebUI adapter using its native user/chat/message metadata and
   the same policy guarantees. Verify independent per-role compaction before
   claiming long-context WebUI integration.
6. Add bounded image input through existing authorized attachment paths, then
   validate the document reader. Keep media generation on the existing serial
   lifecycle and preserve Gaming restrictions.

See [WORK-AGENT.md](WORK-AGENT.md) for use, storage and rollback, and
[MODEL-TEAM-AND-HANDOFFS.md](MODEL-TEAM-AND-HANDOFFS.md) for the target policy.
