# Board additions

Use the current GitHub main branch as the source of truth. Local copies can be
older than the live repository.

When asked to add a motherboard, research its lane sharing FIRST, before the
first BIOS scrape for that board. Use the exact model and PCB revision's official
manual and official specifications. Verify M.2-to-GPU, M.2-to-expansion-slot,
USB4/SATA, BIOS-selectable modes, and CPU-specific limitations. Do not infer that
a sharing rule works in reverse unless the source documents that behavior.

Save the findings once in `lane_sharing.yml`, with sources, page/section, review
date, hardware revision and CPU assumptions. Add the matching `config.yml` board
in the same change. A verified no-sharing finding still needs a sourced record.
If documentation cannot establish the facts, say what is missing and leave the
board addition incomplete instead of silently declaring research complete.

Run the lane-sharing check against the base commit and the focused tests before
finishing an addition. Existing boards marked pending are the initial research
backlog; a new addition must include its own verified record. The pull-request
check detects new models relative to the base branch.

Daily BIOS updates reuse saved research. Do not add daily manual downloads or
automated research requests to `pages.yml`. Revisit a record when explicitly
requested or when its hardware revision or relevant vendor documentation changes.

The new-board check reports missing research; it does not perform web research.
Do not configure a paid research service, credentials or external automation
unless the user specifically requests that workflow.
