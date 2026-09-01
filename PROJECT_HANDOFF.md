# Project handoff — 2026-08-30

## Product direction

Continue evolving Shibutzit into a conversational AI-assisted school class-placement product. The AI is the primary interface and orchestrator; the solver remains the source of truth; structured UI supplies evidence, control, comparisons, and reproducibility. Preserve the existing stack, backend architecture, solver, and API contracts unless a correctness requirement needs a small compatible extension.

## Completed in the latest pass

- Verified and polished contextual handoffs from the classes workspace into chat:
  - class-level analysis;
  - assignment comparison;
  - grounded “why is this student here?” questions;
  - stale-result refresh through the assistant.
- Prevented contextual prompts from being silently dropped while the assistant or solver is busy.
- Synchronized successful visual moves and undo actions with the structured conversation timeline.
- Improved class-board interaction safety:
  - manual edits are serialized, so overlapping requests cannot create out-of-order versions;
  - controls are disabled while an update is pending;
  - the UI restores state after a failed move or lock operation;
  - violation feedback compares before and after counts instead of claiming all existing violations were caused by one move;
  - locked students must be explicitly unlocked before being moved.
- Improved accessibility:
  - the horizontal class wall is a labeled keyboard-focusable scroll region;
  - filtered-out student cards leave the tab order;
  - the student drawer traps focus, restores prior focus, and handles Escape without closing the parent workspace.
- Fixed a conversational lock invariant: a move request without “lock after move” no longer silently unlocks an already locked student. A locked student cannot be moved conversationally until the unlock is explicitly approved.
- Made manual version history and machine-readable project memory accurately describe moves, locks, unlocks, and applied decisions without exposing raw student IDs in user-visible text.
- Strengthened approval/export safety:
  - approval rejects versions with mandatory-rule violations;
  - approval rejects stale results after rules or data change;
  - direct Excel export requires an explicitly approved current version;
  - the class workspace disables approval/export and explains how to refresh a stale result.
- Fixed export provenance: manually adjusted versions export as `MANUAL` and no longer inherit stale solver runtime or objective values.
- Fixed invalid XlsxWriter conditional-format definitions in exported workbooks.
- Fixed class friendship summaries to use authoritative metrics and show “no data” instead of a misleading 0% when the workbook has no friendship requests.
- Audited assignment comparison and version restore end-to-end:
  - every new solve snapshots the authoritative current server version first, so comparisons after a restore or manual edit count moved students against the right baseline;
  - structured restores now appear in the conversation timeline and project decision memory;
  - version history shows moved students, mandatory violations, and locks;
  - recommendation logic never ranks incompatible configurations by raw objective score or recommends a version with mandatory violations;
  - missing friendship or academic data is described as unavailable rather than as 0% success or perfect balance.
- Added a reproducible academic-balance metric to solver results, simulations, structured comparisons, the classes summary, version snapshots, and exported Excel.
- Hardened the exact multi-option Hebrew request `תחלק ותציג לי כמה אפשרויות ותפרט על השיבוצים`:
  - it deterministically requests three real solver runs even if the model only replies in prose;
  - an under-counted model tool call can no longer reduce the request to one run;
  - alternative random seeds remain comparable because seed/search time are execution details, while class-count and priority changes remain distinct configurations.
- Added deterministic visual fixtures for assignment comparison and the dense six-class review board, so these states can be rendered without an API key or backend.
- Rendered and inspected the real UI at 1440px, 1000/900px, and the headless browser's 500px narrow-layout minimum. The rendered audit found and fixed:
  - RTL before/after values displaying in reverse order;
  - a cascade bug that reserved a blank 340px inspector column at tablet/mobile widths;
  - a phone-width top bar that would overflow when start-over, inspector, run-state, and solve controls were all present;
  - a missing accessible name on the class-board search field.
- The compact mobile top bar now preserves every action with a full accessible name; only the visible label is shortened.
- Added grounded, version-aware answers for questions such as “Why did Maya move?”:
  - the agent now compares the student’s actual previous and current stored assignment versions;
  - it reports measured class, friendship, class-composition, and academic-balance changes;
  - it checks whether returning only that student to the previous class would introduce a mandatory-rule violation;
  - it explicitly distinguishes verified blockers and measured observations from unavailable solver causality, rather than inventing one reason for a move.
- Hardened student privacy in read-tool context: relationship and manual-lock rules keep their opaque rule IDs and useful type, but labels sent to the model no longer expose embedded student IDs or names.

## Completed in the 2026-08-30 UI/flow continuation

- Applied interaction patterns inspired by OpenAI/ChatGPT and Anthropic Claude while preserving Shibutzit's evidence-first product model:
  - conversation remains the calm primary surface;
  - solver results and class assignments remain structured, inspectable artifacts;
  - the composer is persistent and users can keep drafting while a response streams;
  - a quiet trust statement below the composer says mandatory rules change only with explicit approval;
  - entry screens no longer show irrelevant assignment status or an unusable solve button.
- Improved chat accessibility and interaction semantics:
  - conversation is a labeled live message log with busy state;
  - user and assistant messages expose authorship;
  - the timeline is keyboard-focusable for scrolling;
  - the composer and send state have explicit accessible names;
  - the thinking indicator is a polite status.
- Proposal cards now use correct RTL decision order: explicit approval is the primary action on the right and rejection is secondary. Proposal cards expose their purpose and busy state.
- Workbook upload now reports truthful stages tied to real operations: reading the file, identifying columns, applying the mapping, and validating the roster.
- Removed the legacy sample workbook's hidden row assumptions from normal uploads:
  - user uploads request automatic header detection;
  - known school headers are detected when the table starts on row 1 or row 4;
  - unknown layouts sensibly expose row 1 as headers for the mapping step;
  - uploads read through the final populated row rather than silently truncating at row 221.
- Mobile project-state inspector now behaves as a modal sheet:
  - visible in-panel close button;
  - focus moves to the close button;
  - Escape and backdrop close it;
  - dialog semantics are exposed;
  - keyboard focus is trapped inside while open and restored to the toolbar trigger on close;
  - fixture mode now supports opening the sheet for deterministic visual checks.
- Rendered and inspected updated entry, proposal, solved, narrow solved, and mobile inspector states. Screenshots are in `.codex-artifacts/`.
- Previous continuation work also added authoritative class-board refresh after edits, comprehensive hard-rule violation reporting, approval-time violation recomputation, dynamic arbitrary review groups, truthful social-review warnings, and localized keyboard drag announcements.

## Completed in the real-session workflow audit

- Exercised a new isolated browser project from a representative Hebrew workbook through upload, automatic row-4 header detection, data interpretation, an exact multi-option Hebrew request, three real solver runs, comparisons, class review, manual movement, lock/unlock, approval, and Excel export.
- Verified the exact prompt `תחלק ותציג לי כמה אפשרויות ותפרט על השיבוצים` produces three solver-backed alternatives, not invented chat assignments. The UI compared friendship satisfaction, two-friend satisfaction, academic spread, class-size spread, mandatory-rule compliance, and moved students, then recommended a specific version with a measured reason.
- Fixed solved-project persistence: after reload, the inspector's Assignment card is now actionable and reopens the current class board with its authoritative saved version.
- Fixed an immediate-Undo race in the class board. Undo now waits for the original move's authoritative refresh to release its adjustment lock, acquires it, and performs the reversal. Browser verification showed three induced mandatory violations returning to zero and approval becoming available again.
- Verified manual class-board safety against the real backend:
  - a move from class 1 to class 2 produced exact class-size and differential-category violations;
  - approval disabled while violations existed;
  - Undo restored the original metrics;
  - lock removed move controls and incremented the locked count;
  - unlock restored move controls;
  - keyboard drag start/cancel rendered the overlay and live announcements without opening the student drawer.
- Verified approval/export produced a valid 24 KB workbook containing seven sheets: class assignment, student list, metrics, violations, friendship requests, configuration, and source data.
- Replaced silent incomplete imports with one focused mapping clarification:
  - only unresolved required fields are shown;
  - generated student IDs and an absent origin flag retain safe defaults;
  - names, school, source class, and academic level can no longer be silently marked as manual when no editor exists;
  - duplicate column selections are prevented;
  - import proceeds only when every necessary mapping is selected.
- Fixed upload evidence so generated `false` defaults are not reported as workbook columns. Missing friendship/support/origin fields are now explicitly listed as missing.
- Validation warnings are now rendered as data-quality warnings and are no longer mislabeled as unresolved friendship requests.
- Automatic workbook discovery now evaluates all sheets and the first 40 rows, preferring recognized school headers and otherwise detecting a string-heavy header followed by data. This supports unfamiliar headers behind title rows and cover/instruction sheets without changing the API shape.
- Browser artifacts for this audit are stored in `.codex-artifacts/`, including `e2e-exact-multi-option.png`, `e2e-reopened-class-board.png`, `e2e-class-board-undo-race-fixed.png`, `e2e-lock-unlock-verified.png`, `e2e-approved-export.xlsx`, and the ambiguous-mapping states.

## Completed in the infeasibility negotiation audit

- Exercised a clean, independently provable browser conflict with 72 students, six classes, and 11 inclusion students while the mandatory inclusion rule required exactly two per class (12 required).
- Verified the product explains the exact 11-versus-12 arithmetic, proposes only `2–2 → 1–2`, keeps the rule mandatory, labels the recommendation as trial-tested, and requires explicit approval.
- Approval of a solver-generated relaxation now automatically resumes the interrupted solver workflow. Ordinary chat rule edits still do not start surprise solver runs.
- The automatic rerun produced a current Version 1 with all 72 students assigned and zero mandatory violations; the pending approval disappeared and the approved decision remained visible in project memory.
- Replaced broad CP-SAT sufficient cores with narrower independently proven arithmetic conflicts when available. The conflict UI now identifies only the impossible inclusion rule instead of misleadingly listing all five capacity rules; interaction-only conflicts continue to use the solver's actual core.
- Corrected the singular conflict copy and the post-result top-bar state. The solver animation stops when the structured result arrives, and the top bar immediately reports the assignment as current even while paced AI commentary is finishing.
- Browser artifacts: `.codex-artifacts/e2e-infeasible-proposal.png` and `.codex-artifacts/e2e-infeasible-rerun-result.png`. The generated audit workbook is `.codex-artifacts/infeasible-one-rule.xlsx`.

## Completed in the grounded follow-up and privacy audit

- Exercised the real Hebrew question `למה תלמידה מדומה 01 שובצה בז׳1?` against a saved assignment.
- Verified the grounded answer reports only current assignment evidence: actual class, verified hard-rule blockers for direct moves, actual friendship-request outcome, and the explicit limitation that the solver did not retain a single causal reason.
- Fixed model variability when a current-placement question incorrectly tries version comparison first in a one-version project. If no grounded version/current-placement answer exists, the application now deterministically runs `explain_student_placement` for the single resolved student and uses that evidence instead of generic model prose.
- Fixed a counselor-facing privacy-token leak after reload. `/api/chat/history` now de-tokenizes user and assistant messages and pending proposals without mutating the anonymized authoritative memory.
- Direct chat and solver-follow-up response payloads are de-tokenized recursively at the API boundary.
- Live streaming now uses a stateful student-name sanitizer that safely handles `STUDENT_…` tokens split across arbitrary network chunks, so internal tokens cannot flash in the UI before the final response.
- Browser artifact: `.codex-artifacts/e2e-grounded-why-placement.png`.
- Verification: focused chat suite `47 passed in 141.38s`; additional grounded-fallback/privacy checks `3 passed` and `1 passed`; the real API/browser rerun showed `compare_student_versions` failing safely, `explain_student_placement` succeeding, and the restored name remaining visible after reload.

## Pointer drag audit status

- A real Playwright mouse drag moved student 1 from class 1 to class 2 through dnd-kit—not through the drawer or keyboard shortcut.
- The authoritative backend assignment changed to class 2 and the board immediately showed the resulting class-size and differential mandatory-rule violations.
- Artifact: `.codex-artifacts/e2e-pointer-drop.png`.
- The first combined Undo attempt waited for backend polling and a full screenshot, so the short-lived toast expired before the click. The audit script was corrected to click the visible `בטל` action immediately after pointer release, specifically exercising the production Undo race guard.
- The audit student was restored to class 1 with zero violations before stopping. The corrected combined pointer-drop/immediate-Undo script still needs one final run next session: `.codex-artifacts/e2e_pointer_drag.py`.

## Verification

- Full backend suite after the version/comparison and academic-balance changes: `168 passed in 339.82s`.
- Focused regression coverage for the latest patches passed, including:
  - conversational move-and-lock confirmation;
  - prevention of silent unlocks;
  - accurate manual version reasons and anonymized project memory;
  - stale-result approval rejection;
  - approved-only export;
  - manual export provenance;
  - XlsxWriter warnings treated as errors.
- `npm run lint` in `frontend`: no errors; one existing TanStack Table/React Compiler warning in `components/DataTable.tsx`.
- `npm run build` in `frontend`: passed with Next.js 16.2.10.
- Latest broad regression slice: `76 passed in 215.57s` across workbook upload/loading, dataset schema, metrics, optimize router, chat agent, approval, and manual adjustment behavior.
- New upload-boundary integration tests cover 230-student workbooks with headers on row 1 and row 4; focused workbook tests: `3 passed`.
- Latest frontend lint: no errors and the same pre-existing TanStack Table/React Compiler warning only.
- Latest frontend production build: passed with Next.js 16.2.10 after all chat, upload, proposal, and mobile-sheet changes.
- Complete backend suite after the real-session fixes: `181 passed in 372.35s`.
- Focused workbook/table-discovery, mapping, and loader suite after the final multi-sheet change: `15 passed in 3.37s`.
- Real browser checks covered upload, exact Hebrew chat intent, three solver runs, version reopening, manual violation reporting, immediate Undo, lock/unlock, keyboard drag cancellation, approval, and downloaded workbook inspection.
- Infeasibility negotiation browser check covered exact arithmetic diagnosis, narrowed conflict evidence, explicit approval, automatic rerun, animation termination, current-state top bar, and zero-violation recovery.
- Latest infeasibility/chat regression slices: `58 passed in 207.03s` and `33 passed in 69.50s`.
- `git diff --check`: no whitespace errors; only Windows LF/CRLF notices.
- Latest focused verification after the version/comparison pass:
  - `42 passed in 171.53s` across metrics, chat-agent, and optimize-router regressions;
  - `13 passed in 152.48s` across solver-backed simulations and version restore;
  - frontend production build passed again.
  - exact multi-option intent and seed-comparison regressions: `4 passed`.
  - comparison and dense class-review fixtures were screenshot-verified after the final fixes; the temporary frontend server was stopped afterward.
  - complete read-tool/chat-agent regression slice: `46 passed in 133.33s`.
  - frontend lint passed again with the same single existing TanStack warning; frontend production build passed.
  - final `git diff --check` reported no whitespace errors, only Windows LF/CRLF notices.

## Completed in the whole-assignment reasoning audit

- Added `analyze_assignment_quality`, a privacy-safe whole-assignment evidence tool containing every class profile, global metrics, hard-rule compliance, active objectives and weights, locks, solver status, and explicit metric semantics.
- Class-size questions now precompute the current evidence and a real tight-capacity counterfactual before the LLM answers. The facts and solver experiment are deterministic; the explanation, emphasis, and conversational next step remain model-generated.
- Added a focused LLM reasoning pass for assignment analysis. It separates measured state, allowed configuration, completed trial results, and unproven causality instead of falling back to a canned renderer or allowing long general-agent context to dilute the evidence.
- Live Hebrew verification on the 72-student assignment explained the 13-versus-11 gap correctly: the active hard range was 11–13 and equal size was not an objective; the exact competing objective that used the flexibility could not be proven from the snapshot.
- The real 12/12 trial was reported in conversation: sizes `[12,13,12,12,11,12] -> [12,12,12,12,12,12]`, academic spread `8 -> 8`, mutual friendship `58.3% -> 75%`, and two-friend placement `27.8% -> 37.5%`, with zero hard violations.
- Added `simulate_balance_priority`, which runs the real solver against a changed academic/source-school/category balance weight and returns the targeted before/after distribution spread plus friendship, academic, size, and violation trade-offs.
- Measured recommendations now have structured project memory. A follow-up such as “yes, use the exact change you tested” resolves to the exact rule id and bounds rather than asking the model to reconstruct them from chat prose.
- Live follow-up verification created the correct approval card for `11–13 -> 12–12`, preserved every other hard rule, stored the completed trial as evidence, and will re-run only after explicit confirmation.
- Structured recommendations are invalidated whenever solver inputs change, preventing a later “yes” from applying stale evidence.
- The same focused evidence-reasoning path now covers “why did she move?” version questions. A real browser move/lock/rerun/version-explanation/unlock audit passed; the answer states the measured version delta and the lack of a recorded single cause instead of attributing the move generically to optimization.
- Added localized activity labels for whole-assignment analysis and balance/friendship simulations.
- Pointer/touch audit completed during this continuation: real mouse and touch drag, per-column touch scrolling, and immediate Undo all passed; the portalled Undo action now remains clickable over the modal class board.
- Verification: `51 passed in 307.27s` across the complete agent and real-solver simulation suites; after the final version-reasoning change the full chat-agent suite passed again (`38 passed in 149.49s`); the changed frontend activity component passes ESLint; multiple live Hebrew API conversations were inspected end to end.

## Completed in the evidence reasoning and editable-data continuation (2026-08-31)

- Kept the production model on `gpt-4o-mini`; improved the evidence and action layer instead of upgrading model cost.
- Added ranked whole-assignment diagnostics for class size, academic concentration, source-school and previous-class clustering, support-category distributions, friendship outcomes, data-imposed friendship ceilings, attention students, locks, hard violations, and unproven solver optimality.
- Broad assignment analysis now runs the highest-priority relevant counterfactual automatically and gives the model measured before/after evidence.
- Added exhaustive safe direct moves from largest to smallest classes, including exact friendship and academic deltas.
- Added `simulate_student_move`: it measures a requested move, reports exact mandatory-rule violations, and searches every unlocked destination-class student for safe compensating swaps.
- Current-placement “why?” questions now use a focused GPT-4o-mini reasoning pass over the actual placement plus a measured alternative rather than a canned rule explanation.
- Added focused comparison for a requested class against every other class.
- Measured balance, friendship, and category-capacity recommendations are stored structurally so “yes, use what you tested” creates the exact approval card.
- Added an editable project-data overlay while preserving the original uploaded workbook:
  - `get_student_record` inspects privacy-safe current values;
  - `analyze_data_quality` reports exact validation issues and affected student tokens;
  - `propose_student_data_edit` creates an explicit before/after approval;
  - confirmed edits recompute validation and friendship resolution, invalidate the old active solve, survive persistence/re-mapping, and feed solver/export through `mapped_df`;
  - student ids cannot be edited;
  - origin/support categories cannot be changed unless the counselor explicitly states that category in the current message;
  - the roster visibly marks students and fields corrected in the project copy.
- Added deterministic handling for unambiguous academic/support corrections so GPT-4o mini cannot answer with prose instead of creating the required approval action.
- Fixed the conversational trial-to-action transition for GPT-4o-mini-selected simulations. Every successful capacity, balance, or friendship trial is now captured as an exact structured recommendation even when the model chose the tool. If the assistant explicitly asked whether to apply that tested change, the counselor's conversational `כן` is the approval: the rule is updated, the decision is recorded, and a full solver run is requested without repeating the 10-second experiment. A typed approval also confirms an already-visible proposal card, so chat and UI remain synchronized controls over one state.
- Live GPT-4o-mini verification on a fresh project passed: file analysis used `analyze_data_quality` and `get_dataset_columns`; an academic correction created a `data_action`, approval changed the project value, the original workbook stayed unchanged, and the previous solve was invalidated.
- Added `sample_data/agent_stress_test_students.xlsx`, a fully fictional 84-student conversational stress scenario. Its default six-class rules contain four independently impossible category counts, while friendship clusters compete with academic/source-school balance and two non-blocking data-quality warnings exercise project-copy edits. The workbook includes a `Test Guide` sheet, and its generator plus regression test prove both the intended initial infeasibility and a real feasible softened configuration.
- Fixed hallucinated rule-feasibility analysis exposed by the stress scenario. `analyze_rule_feasibility` now proves every active mandatory capacity rule independently from the actual roster count and class count, returns the exact arithmetic and smallest bound relaxation, and clearly limits its claim to independent feasibility rather than cross-rule interactions. Requests such as `תנתחי אילו כללים בלתי אפשריים בפני עצמם` deterministically prefetch this evidence plus authoritative active rules before a focused GPT-4o-mini explanation. Recent numeric requirements are included so the answer can identify rules the user requested but that never became active. Verified on the real 84-student session: four independent conflicts (7 differential, 17 Ethiopian-origin, 11 inclusion, 13 special-support); complete chat-agent suite: 48 passed.
- Added atomic multi-rule feasibility packages. The independent audit stores every exact minimal relaxation as one structured recommendation; `את כל החבילה` explicitly approves the whole set, validates all targets before any mutation, updates all rules in one input revision/history decision, and requests one full solver run. A missing/stale target aborts the package without partial edits. The 84-student regression proves all four bounds change together and the model is not called again.
- Assistant messages now render a safe Markdown subset instead of exposing literal formatting markers. Bold, ordered/unordered lists, short headings, paragraphs, and inline code render semantically; raw HTML, links, images, and arbitrary attributes are never interpreted. Frontend lint passes with only the existing TanStack warning and the production build passes.
- Verification in this continuation:
  - broad agent/simulation suites: 55 passed, one obsolete routing expectation identified and corrected; its focused regression now passes;
  - editable-data/workbook slice: 19 passed;
  - focused data-edit and analysis slices passed;
  - complete chat-agent suite after the trial-to-action fix: 47 passed;
  - frontend ESLint: no errors, the existing TanStack React Compiler warning only;
  - frontend production build passed.

## UI goal — conversational workspace milestone 1 (2026-08-31)

- Started the formal UI refinement goal using the existing future direction: Claude Artifacts-style coordinated workspace, ChatGPT-like conversational ease, Linear-level precision, and restrained Apple-like spacing/motion. The stack, backend, solver, and API contracts remain unchanged.
- Completed a rendered audit of the empty, dataset-ready, proposal, solved, comparison, infeasible, mobile, and six-class review fixtures. Correct Shibutzit fixture audits use `http://localhost:3000`; `127.0.0.1:3000` belongs to a different local app and must not be stopped.
- Made planning genuinely conversation-first. Before a workbook exists, the empty project no longer reserves a 360–390px inspector for configuration; the AI conversation uses the full canvas and the workbook action remains the clear next step.
- Once data exists, the inspector returns as a narrower coordinated project record. Its data, rules, versions, and assignment configuration now read as one authoritative artifact with internal sections instead of unrelated dashboard cards.
- Reduced the desktop inspector from 390px to 360px (328px on narrower desktops), giving the conversation and structured result artifacts more usable width without hiding project state.
- Strengthened approval trust: proposed changes now explicitly say that they have not been applied and will only enter the project after approval. Proposed mandatory-rule changes use a distinct warning treatment; confirmed/rejected states remain in history.
- Improved the six-class review board while preserving all-class comparison and per-class right-edge scrolling: wider columns, more legible category/balance statistics, larger school labels, more readable summary metrics, and a corrected responsive summary footer.
- Added a safety statement to workbook upload: before creating an assignment, the product will show what it understood and which mandatory rules are active.
- Preserved mobile inspector behavior as an accessible modal sheet with Escape handling, focus trapping/restoration, scrim dismissal, and a dedicated close control. The class review remains a deliberate horizontally navigable evidence surface on small screens.
- Rendered verification artifacts are under `.codex-artifacts/ui-goal-baseline`, `ui-goal-pass1`, `ui-goal-pass2`, `ui-goal-pass3`, and `ui-goal-mobile` (ignored by Git).
- Verification: frontend production build passes; ESLint has zero errors and only the pre-existing TanStack Table React Compiler warning; `git diff --check` reports only the repository's existing Windows line-ending warnings.
- The formal UI goal remains active. The next iteration should focus on real-session chat→artifact transitions, upload/mapping/error interaction states, version selection/restore affordances, and keyboard/touch audits with actual backend data.

## UI goal — first-run, history, and roster continuation (2026-08-31)

- Added deterministic, development-only previews for `?fixture=welcome`, `upload`, `upload-busy`, `upload-mapping`, and `upload-error`. These render the actual production components without clearing or modifying the live backend session.
- Audited and refined the complete workbook handoff:
  - loading communicates four truthful stages (read, identify, map, validate);
  - ambiguous mappings stack safely and responsively, including a four-field narrow-screen stress state;
  - tall mapping content scrolls instead of clipping;
  - upload errors now use a clear warning icon, border, and surface rather than looking like the normal dropzone;
  - the pre-solve safety statement remains visible beneath every upload state.
- Added deterministic populated project-overview data to the solved fixture, including category tallies, remembered decisions, three assignment versions, locks, movement counts, and metrics. This makes the real inspector/history UI screenshot-verifiable rather than dependent on a browser session id.
- Made version restoration explicitly two-step in the structured UI. Selecting `שחזור` now opens an inline confirmation explaining that the active assignment will be replaced while other versions remain available; only `אישור שחזור` performs the API call.
- Fixed chat→inspector continuity on mobile. Actions that open the rule list, a specific conflicting rule, or another inspector-backed evidence target now open the mobile sheet automatically. Desktop keeps focusing the already-visible inspector. Inspector mode changes also reset its scroll position to the top.
- Added a deterministic `?fixture=roster-review` preview using the actual roster workbench with 48 fictional students and project-edited markers.
- Refined roster review on narrow screens:
  - summary figures use a stable 3×2 grid;
  - search and category filters remain usable without wrapping unpredictably;
  - an explicit cue explains that horizontal scrolling reveals the editable manual fields;
  - the dialog uses more of the small viewport while retaining the real horizontally scrollable table.
- New rendered audit artifacts are under `.codex-artifacts/ui-goal-first-run`, `ui-goal-first-run-mobile`, `ui-goal-version`, and `ui-goal-roster` (Git-ignored).
- Verification after the final edits: frontend production build passes; ESLint has zero errors and only the pre-existing TanStack Table React Compiler warning; `git diff --check` reports only Windows line-ending warnings.
- The formal UI goal remains active. Next highest-value surfaces: real keyboard/touch interaction checks for restore, mapping, and destructive-rule confirmations; comparison/student-explanation continuity; and the final cross-surface consistency audit.

### UI goal — rules and student decisions continuation

- Added deterministic rendered states for the remaining decision surfaces:
  - `?fixture=constraint-browser`
  - `?fixture=constraint-detail`
  - `?fixture=student-detail`
  - `?fixture=student-move`
- Rule fixtures no longer depend on the live API, so browser/detail states are reliable in visual regression audits.
- Refined the rule register with an authoritative “used for the next assignment” description, hard/preference/inactive grouping, visible counts, improved row targets, and clearer source/detail hierarchy.
- Weakening a mandatory rule now requires an explicit inline confirmation explaining the consequence. Rule removal also uses a two-step confirmation and states that the current assignment will not change until another run.
- Reworked the student drawer into an evidence-first decision record:
  - clearer student identity, current class, source school, and academic context;
  - structured friendship metrics and specific warning state;
  - explicit manual-move draft status with before/after class sizes;
  - a safety note that rules and warnings are recalculated after the move;
  - an AI preflight action that asks what would happen to hard rules, friendship, and balance before the user commits;
  - clearer lock persistence language for future solver runs.
- Comparison cards now provide direct actions to open the new assignment or the version history, so measured trade-offs lead directly to the relevant structured evidence.
- When the agent used assignment-analysis, class, violation, or student-placement tools, its quiet evidence log now includes a direct “open evidence” action. This does not claim that the model proved more than the tools returned; it simply reconnects the explanation to the authoritative class board.
- Verified rendered desktop and 500px narrow layouts under `.codex-artifacts/ui-goal-decisions` (Git-ignored). The constraint detail sheet and student move proposal remain readable and actionable in Hebrew RTL.
- Verification: frontend production build passes; ESLint has zero errors and only the existing TanStack Table React Compiler warning; `git diff --check` reports only repository-wide Windows line-ending warnings.

### UI goal — cross-surface trust consistency

- Render-audited proposal approval, infeasibility, comparison, and version restore at both workspace and 500px mobile widths under `.codex-artifacts/ui-goal-consistency` (Git-ignored).
- Infeasible results now state explicitly that no rule was changed and that relaxing any mandatory rule still requires direct user approval. This aligns failure handling with the proposal and rule-detail safety model.
- The deterministic `version-restore` fixture now opens the actual mobile inspector sheet, making version history and the two-step restore confirmation visually verifiable rather than leaving the relevant UI off-screen.
- Confirmed the mobile sheet retains readable RTL hierarchy, explicit close/focus entry, a visible current version, and an unambiguous restore candidate with cancel/confirm actions.
- Comparison cards retain direct routes to the new assignment and version history, while mandatory-rule status remains visible next to the measured trade-offs.
- Verification after this pass: frontend production build passes; ESLint has zero errors and only the existing TanStack Table React Compiler warning; `git diff --check` reports only repository-wide Windows line-ending warnings.

### UI goal — finalization and export safety

- Added deterministic board fixtures for the three finalization states:
  - `?fixture=class-review-stale`
  - `?fixture=class-review-violations`
  - `?fixture=class-review-approved`
- Render-audited all three states at desktop and 500px widths under `.codex-artifacts/ui-goal-finalization` (Git-ignored).
- Promoted approval blockers into the primary board status:
  - stale versions show `לא מעודכן`;
  - hard-rule violations show `דורש תיקון`;
  - safe drafts remain `טיוטה פעילה`;
  - approved versions show `מאושר`.
- The approval/export button no longer remains deceptively green when blocked. It becomes a neutral `אישור חסום` control with a lock icon and programmatic `aria-describedby` links to every active blocking explanation; this remains understandable on touch devices where hover titles do not exist.
- Separated backend approval from browser file download. If approval succeeds but download fails, the version remains visibly approved and the message tells the user to retry the download; the UI no longer reports the whole operation as if approval failed.
- Added a structured `final_approval` timeline event and `?fixture=final-approved`, so the conversation records whether the final Excel was downloaded and the version history visibly marks the approved version.
- A repeated download of an already approved version no longer unnecessarily calls the approval endpoint again.
- Verification: frontend production build passes; ESLint has zero errors and only the existing TanStack Table React Compiler warning. Final approved conversation state was rendered at desktop and mobile widths.

### UI goal — accessibility and interaction behavior

- Audited the authoritative behavior of Radix workspace dialogs, the custom mobile inspector sheet, student drawer, conversation log, composer, class-board drag controls, and reduced-motion rules.
- Blocked approval is now `aria-disabled` rather than native-disabled. It remains in the keyboard order, performs no action, and announces the linked stale/violation/sync explanation. Loading and active export still use true native disabled behavior.
- Restored chat history no longer enters the conversation live region as if every old message were new. `historyReady` keeps the log quiet during asynchronous hydration, then enables polite announcements for subsequent activity.
- Streaming assistant messages override the parent live region while tokens arrive, preventing repeated partial announcements; the completed response returns to the normal polite log behavior.
- Touch/coarse-pointer users always see the checklist-row removal control. It no longer depends on hover discovery and receives a larger touch target.
- The solver pause control is hidden under `prefers-reduced-motion`, because global motion is already disabled and a visible “pause” action would falsely imply ongoing animation.
- Student-drawer and inspector-sheet backdrops are now non-focusable presentational click targets. The explicit close buttons remain the sole keyboard/screen-reader close controls, while Escape and focus restoration continue to work.
- The student drawer exposes `aria-busy` while an assignment adjustment is in flight.
- Existing class-board accessibility remains intact: descriptive card labels, keyboard DnD instructions and announcements, keyboard sensor, focusable horizontal-scroll region, and visible non-color warning/lock/category information.
- Verification: ESLint has zero errors except the existing TanStack Table React Compiler warning; the production build passes.

### UI goal — contrast and dense-data legibility

- Calculated WCAG contrast for the active premium token override rather than relying on visual inspection. The previous palette had several semantic-text failures:
  - primary blue on white: 4.16:1;
  - warning orange on white: 3.88:1;
  - critical red on white: 4.21:1;
  - tertiary text on the warm panel: 4.11:1.
- Darkened the same restrained palette without changing its character:
  - accent `#2f65df` (5.19:1 on white, 4.50:1 on the warm panel);
  - accent-strong `#1f52c7`;
  - tertiary ink `#5f6d80` (5.27:1 on white, 4.57:1 on the warm panel);
  - success `#0f765f`;
  - warning `#9a4f27`;
  - critical `#b93642`.
- Inactive rules remain clickable, so they are no longer faded to 50% opacity. They now use the accessible tertiary-text token and a quiet decorative dot while staying unmistakably inactive.
- Increased hard-violation detail text from 9/10px to 10/11px, improving legibility without materially increasing board height.
- Render-audited rules, proposal approval, mobile hard violations, and the final approved conversation under `.codex-artifacts/ui-goal-contrast` (Git-ignored). The palette remains calm and professional while small Hebrew metadata is materially clearer.
- Verification: frontend production build passes; ESLint has zero errors and only the existing TanStack Table React Compiler warning; `git diff --check` reports only repository-wide Windows line-ending warnings.

## Next high-impact audit

1. Test representative Hebrew prompts end-to-end:
   - `תחלק ותציג לי כמה אפשרויות ותפרט על השיבוצים`
   - individual “why is she here?” and “why did she move?” questions, including explicit older-version references;
   - move-and-lock and explicit-unlock requests;
   - infeasible mandatory-rule combinations;
   - “keep everything else the same” priority changes.
   - conversational data corrections for academic level, support flags, source school/current class, and custom fields;
   - data-quality analysis with invalid academic values, unresolved friendship names, duplicate names, and missing source columns.
2. Observe the new assignment-analysis discussion with additional real school files, especially cases where academic, source-school, and support-category balance disagree; the pointer/touch/Undo audit is complete.
3. The rendered full-screen board uses the available desktop width effectively for all six classes; retain the focused review mode for now. Reconsider a split view only after observing real users switching repeatedly between chat and the board.
4. Consider addressing the existing `DataTable.tsx` React Compiler warning separately; it is unrelated to this pass and is currently non-blocking.
5. Continue visual refinement through interaction states rather than a wholesale restyle: hover/focus/pressed/loading/error transitions, artifact-to-inspector continuity, and real-session mobile testing are higher value than changing the established palette.
6. Add an atomic approval action for a measured two-student swap. The simulation already finds and ranks safe swaps, but applying both movements still needs one transactional action/version.
7. Add a structured friendship-request editor that accepts resolved student tokens; raw friendship names should remain outside model context.

## Future UI redesign direction

Use one coherent reference model rather than mixing unrelated visual styles:

**Claude Artifacts' workspace model + ChatGPT's conversational ease + Linear's visual precision, adapted for careful school decision-making.**

This is a future refinement of the existing hybrid product, not a replacement of its architecture, solver, API contracts, or evidence-first behavior.

### Experience model

- Keep conversation as the primary entry point and decision surface.
- Treat the current assignment as a persistent artifact beside the conversation, similar to Claude Artifacts: substantial, directly inspectable, editable, versioned, and always tied to the same project state as chat.
- Borrow ChatGPT Canvas' transition from conversation into focused work: the assistant should open or focus the relevant artifact automatically when a result, comparison, rule, student, or warning becomes the subject of discussion.
- Borrow Linear's density discipline, typography, interaction states, and hierarchy without copying its developer-oriented complexity.
- Borrow Apple's restraint, spacing, motion quality, and confidence, but avoid marketing-page scale, decorative emptiness, or oversized typography inside the working product.
- Use Notion only as a reference for flexible structured blocks. Do not inherit its open-ended configurability or turn Shibutzit into an administrative database builder.

### Proposed desktop composition

- A calm project header containing only project identity, current version/status, history, and final approval/export.
- A flexible two-surface workspace:
  - conversation remains readable and comfortable rather than compressed into a narrow utility rail;
  - the assignment artifact opens beside it for rules, class review, comparisons, student details, and warnings;
  - either surface can temporarily expand when the user needs deep conversation or a full class-board review.
- One persistent composer with file attachment, clear send/stop behavior, and contextual prompts based on the artifact currently in focus.
- A compact evidence strip or artifact header that always exposes current version, mandatory-rule status, freshness, locks, and the most important measured outcome.
- Long tables and all six class columns remain outside chat messages. Chat contains concise interpretation and small actionable evidence cards only.

### Interaction principles

- Selecting a class, student, warning, metric, or version in the artifact makes it the active conversational context; the next question should naturally mean “about this.”
- When the assistant discusses a specific fact, visually focus or highlight the corresponding structured evidence without taking control away from the user.
- Every experiment is visibly labeled as a trial. Applying a tested change updates the authoritative rule, records the decision, launches the requested full solve, and creates a new version—never another identical trial.
- Manual UI changes and conversational changes must produce the same events, locks, validation, history, and explanations.
- Use progressive disclosure: executive summary first, focused detail on request, advanced solver terminology only behind an advanced view.
- Motion should communicate state transitions—upload understanding, rule proposal, solver progress, result arrival, comparison, and restore—not decorate static screens.
- The running animation must stop the moment authoritative results arrive, even if paced narrative text is still finishing.

### Visual system goals

- Quiet neutral surfaces, restrained school-appropriate color, and one purposeful accent rather than many competing colors.
- Strong typographic hierarchy with excellent Hebrew RTL behavior and readable metric typography.
- Fewer containers and borders; use spacing, surface elevation, and alignment to establish hierarchy.
- Consistent radius, shadow, icon, focus-ring, hover, pressed, disabled, loading, success, warning, and error behavior across every artifact.
- Dense data may be compact, but primary decisions and safety warnings must remain spacious and unmistakable.
- Preserve visible evidence for every AI claim; visual polish must never make the system feel like opaque AI magic.

### Suggested implementation sequence

1. Audit real desktop and mobile sessions and identify the five most common surface transitions: chat→rules, chat→result, chat→student, chat→comparison, and artifact→chat question.
2. Define shared design tokens and interaction states before restyling individual components.
3. Redesign the workspace shell and responsive surface behavior while keeping existing artifacts functional.
4. Refine the composer, message pacing, tool activity, approvals, and result-arrival choreography.
5. Unify rules, results, classes, comparisons, versions, and student details into one consistent artifact system.
6. Validate full Hebrew RTL flows with keyboard, touch, screen-reader, narrow desktop, and mobile use.
7. Run real counselor/teacher scenarios before removing established controls or changing information density.

### Guardrails

- Do not turn the product into a dashboard with chat attached.
- Do not hide active mandatory rules, violations, stale-result state, locks, measured trade-offs, or version provenance.
- Do not copy consumer-AI visual novelty that weakens professional trust.
- Do not add broad navigation, customization, or administrative modules unless real usage proves they are necessary.
- Do not begin the visual redesign until the current agent-action loop reliably distinguishes trials, approvals, full solver runs, and authoritative edits.

## Runtime state

- Do not start or stop unrelated services.
- At the end of this continuation, the user had Shibutzit running on port 3000 and the backend on port 8000. Do not stop either process unless the user asks; verify ownership before changing runtime state.

## UI goal — durable recovery and regression audit (2026-08-31)

- Replaced transient-only chat failure feedback with a durable timeline artifact. Safe read/analysis turns can be retried in place; mutation-adjacent turns direct the user to inspect authoritative project state first so a rule or edit is not applied twice.
- Added in-context retry states for the rules browser, rule detail, class-review loader, and roster loader. A failed fetch no longer leaves an endless skeleton or a misleading “not found” state.
- Roster save failures now preserve all edited values, show that changes remain unsaved, and provide an explicit retry action instead of relying on a toast.
- Added solver-request reconciliation:
  - the running animation stops immediately when the request returns or fails;
  - after a timeout, the client checks authoritative version history before offering another run;
  - if the solver actually finished, the saved version and measured metrics are recovered and shown without running again;
  - partial multi-option runs report how many versions were saved and avoid a blind retry;
  - Retry appears only after verifying that no new version was created.
- Proposal approval/rejection failures now remain attached to the exact proposal, explicitly state that no rule changed, and leave the same approval controls available for retry.
- Added deterministic fixtures for chat retry/review, solver verified-retry/partial-run review, proposal failure, rules/results load failure, and roster load/save failure.
- Render-audited the complete product loop at desktop and mobile widths: welcome, mapping, empty conversation, rules drawer, solved result, infeasibility, comparison, class review, roster, approval/export, and all new recovery states. Artifacts are under `.codex-artifacts/ui-goal-recovery` and `.codex-artifacts/ui-goal-regression` (Git-ignored).
- A 360px headless Edge screenshot pass appeared clipped, but the browser was clamping its layout viewport to roughly 500px and cropping the capture. The valid 500px responsive render is clean; no production CSS was changed based on that false signal.
- Verification at this milestone: frontend production build passes; ESLint has zero errors and zero warnings; all 203 backend tests pass; `git diff --check` reports no whitespace errors, only repository-wide Windows line-ending warnings.

## Worktree warning

The repository contains many intentional modified and untracked files from the ongoing redesign. Do not reset, revert, or overwrite unrelated work. Review diffs narrowly before editing.

## Latest continuation — stress default and complete feasibility review (2026-09-01)

- The bundled default workbook is now `sample_data/agent_stress_test_students.xlsx` (84 fictional students, sheet `תלמידות`, rows 5–88). It deliberately exposes four independently impossible category rules so the conversational relaxation workflow is testable immediately.
- Legacy regression fixtures that require the old 217-student feasible roster now load `רשימה כללית לאיזונית.xlsx` explicitly; they no longer depend on the product default.
- Multiple arithmetic conflicts are collected into one atomic feasibility package. The proposal contains every minimal rule correction, student totals, before/after ranges, and one explicit “approve all changes” action.
- Package confirmation validates every target before changing anything, applies all edits atomically, records one decision/revision, and requests a full solver run only if no known arithmetic conflict remains.
- A single approved correction no longer triggers another doomed run while other independently impossible mandatory rules remain; the assistant states that the remaining rules must be handled first.
- The proposal UI renders each bundled change as a separate evidence row while keeping one atomic approval button.
- Fixed the roster/manual-entry sticky header so student rows no longer show through it while scrolling.
- Verification: focused and broad backend regressions passed after correcting one deliberately impossible legacy test input (119 passed in the broad run before that corrected test was rerun successfully); the stress package suite passes; frontend lint has one pre-existing TanStack compiler warning and no errors; production build passes; `git diff --check` reports only repository line-ending warnings.

## Guided data correction (2026-09-01)

- Replaced the misleading “complete column mapping” warning for row-level problems with “details need review,” plain-language guidance, and a direct correction button.
- Validation warnings retain their affected student ids and field, so the button opens the roster filtered to exactly those students and highlights the exact invalid cells.
- Current school and academic level are now safely editable in the roster. Academic level is constrained to the three accepted values; school is a focused text field. Changes save into the audited project overlay and never modify the uploaded workbook.
- The correction guide counts unresolved students live and turns into a green completed state after the last correction.
- Browser-verified the warning card, targeted two-student correction view, actual saves, and completed state. Screenshots: `.codex-artifacts/guided-data-warning-action.png`, `guided-data-correction.png`, and `guided-data-correction-complete.png`.
- Verification: frontend production build passes; lint has no errors (one pre-existing TanStack warning); 14 focused workbook/stress/data-edit tests pass; source-workbook immutability is covered by regression test.
