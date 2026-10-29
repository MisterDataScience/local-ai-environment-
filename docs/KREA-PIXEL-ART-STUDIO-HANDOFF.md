# Krea pixel-art studio handoff

## Current boundary

The optional installer component downloads and verifies Krea 2 Turbo and the pixel-art LoRA. A bundled `pixelart_runner.py` can validate a batch, load the model once, extract 32×32 PNGs, save per-sprite prompt/tag/seed/hash receipts, resume verified outputs and search exact tags. Its GPU dependencies are not installed by this component and no native Mac render has passed. The Studio Lead cannot invoke this runner yet. The existing studio workflow is a portable-C game-production lane and does not accept image batches. The review gallery prototype is not connected to generated files or studio records.

Do not describe model installation or the gallery prototype as an operational pixel-art studio.

## Synod integration

Captain routes ordinary sprite briefs to the Pixel Art Studio Lead. Requests to create, redesign or repair a studio go through `studio_contact` to The Synod, preserving its explicit design review and construction blockers. The Captain instruction must retain both routes.

The current Synod construction adapter supports text studios only. A Pixel Art Studio specification that requires `image_generation` must remain blocked until a real, tested Krea 2 + LoRA generation adapter is installed and Synod supports it. The currently provisioned inbox is not evidence that the Synod has built or trialled an operational image studio. Do not mark it Synod-built or ready for sprite generation based on prompt instructions alone.

## Accepted user workflow

1. The owner asks Captain to route a sprite task to the pixel-art studio. Captain creates or resumes one durable batch with the user's brief and links it to the studio conversation.
2. The Studio Lead owns the batch and its state. It asks the Designer to turn the brief into a compact visual specification, then the Pixel Artist to prepare prompts, seeds, model settings and generation constraints. The Lead reviews those records before generation.
3. A local generation runner uses the installed Krea 2 Turbo base model and LoRA. Model loading, batch execution, restart recovery and resource limits belong to the runner. Keep generation batches large enough to avoid repeatedly unloading and reloading the image model. Review-page rendering must not impose a generation batch size.
4. The Review Agent is the last studio worker. It packages the generated images, seed/prompt metadata, objective file checks and a review manifest. It may flag verifiable issues such as wrong dimensions, missing alpha, duplicate file hashes, unreadable files, or a failed extraction. It must not claim to judge subjective visual quality as fact.
5. When the batch is ready, Captain posts one chat message with a link to the durable review page and a short summary. The page is a continuous gallery of the whole batch. It renders previews incrementally, around 40 at a time, as the owner scrolls; it does not create 25 separate review pages.
6. The owner can keep or reject each sprite and optionally add a note. The page saves decisions against stable batch and sprite IDs. Submitting the review sends the decision to Captain, which routes it to the Studio Lead. The Lead either closes the batch with the kept sprites or assigns revisions to the Pixel Artist or Designer as appropriate.

## Ownership and routing

- Captain owns the user conversation and is the only studio-to-chat delivery point.
- Studio Lead owns the batch, stage order, handoffs and next assignment.
- Designer owns the visual brief and changes to its direction.
- Pixel Artist owns prompts, seeds and generation revisions.
- Review Agent owns the deliverable manifest and objective checks. It is not the user's decision-maker.
- The owner makes the final visual selection. Review Agent reports and Captain conveys; neither silently approves assets.

A chat reply such as “keep 12, 19 and 23; revise 31” is a valid review decision. A page submission must produce the same durable decision record. Both paths converge on Captain and then the Studio Lead, so neither path creates a second workflow controller.

## Required durable records

A batch record needs a stable ID, institution/project, brief revision, state, timestamps, generation settings, count, and links to its review manifest and conversation thread. Each sprite record needs a stable ID, safe relative asset path, content hash, prompt, a 3–8 item lowercase hyphenated tag list, seed, generation settings and review state. Tags cover subject, asset type, visual style and intended use, use consistent vocabulary, and remain searchable with the prompt. Owner decisions must be append-only events with actor, timestamp, selected IDs and note. A retry creates new sprite IDs and preserves previous outputs and decisions.

The page must not trust filenames, browser-provided paths or model-generated markup. Serve images through an authenticated local route, enforce institution/batch scope, and validate every submitted sprite ID against that batch. Keep selections server-side as soon as the user changes them, and show saved/pending status. Export only owner-kept files with a manifest.

## Chat delivery constraint

The current OpenCode Captain tool can send a message to the Studio Lead and retrieve that saved conversation. It has no verified API for injecting a new assistant message into an idle chat when a background studio job finishes. Do not promise an unsolicited chat notification until a supported delivery hook exists. The first implementation can return a stable review link when the task is routed and let that page show queued/running/ready states; a true completion message requires an explicit integration with the Captain chat host. Keep the review record durable so an ordinary restart cannot lose the job or selections.

## Implementation and acceptance gates

The studio integration is not complete until all of these work in the installed application:

- Captain can route a pixel-art request to a distinct workflow without entering the C-game production lane.
- The Studio Lead resumes a queued batch after a normal gateway restart and never schedules a second generation process for the same active batch.
- The generation runner uses the installed model and LoRA, records model revisions/settings, and can resume or safely mark an interrupted batch.
- A batch of 1,000 sprites can be reviewed in one continuous page. Only nearby previews need to be decoded/rendered at once; selection state survives scrolling, refresh and restart.
- Keeping/rejecting assets in the page and replying in Captain chat produce equivalent durable decisions.
- The Review Agent reports only reproducible checks and packages exact assets; it does not make the final visual choice. Every prompt remains paired with its searchable tags through generation, review and export.
- Studio Lead routes revision notes to Designer or Pixel Artist and closes a batch only after the owner's selection.
- Authentication, path scoping, request limits, storage quotas and export hashes are tested.
- Native Mac generation speed, memory use and a representative 1,000-image review are measured before claiming capacity or overnight completion.

Until those gates pass, the branch provides model installation and the agreed workflow contract only.