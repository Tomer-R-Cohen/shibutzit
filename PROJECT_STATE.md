# שיבוצית — current state (for redesign brief)

## What this is

A local-first tool that assigns ~217 real 7th-grade students into balanced classes under hard and soft constraints (class size, demographic quotas, friendship co-placement, academic/school balance), using Google OR-Tools CP-SAT as the actual solver. Hebrew, RTL. The product bet: instead of a settings-form UI for configuring rules, a counselor should be able to describe rules in plain Hebrew to a chat agent, which translates them into formal constraints, gets confirmed, and feeds the same deterministic solver.

## Stack

- **Backend**: Python, FastAPI, session-based (`X-Session-Id` header, in-memory + on-disk pickle persistence, no auth, no DB, single process).
- **Solver**: `src/optimizer.py`, CP-SAT, pinned to 1 worker for reproducibility (fixed seed → identical output).
- **LLM layer**: `backend/llm/` — OpenAI-compatible client (`provider.py`, defaults to Kimi K2 via Moonshot, swappable), 7 typed tool schemas (`tools.py`), system prompt + context builders (`prompts.py`), per-session opaque student-id tokenization so raw names never reach the LLM (`tokenization.py`), infeasibility narration (`narration.py`).
- **Frontend**: Next.js 16 (Turbopack), React 19, Tailwind v4. Single route (`/`), no other pages.

## Data model (backend)

Every rule — the 10 built-ins (class size, differential/ethiopian-origin/inclusion/ח"מ capacity ranges, friendship weight, 4 balance objectives) and any chat-added exception (pairwise separate/together, "at least one of a group", ad hoc groups, custom capacity/balance) — is one `Constraint` object (`src/constraints.py`): `{id, type, hard, args, label_hebrew, source, active}`. Seeded once per session on first workbook mapping, then persisted and directly editable (PATCH hard/active, DELETE) via `/api/constraints`, both by chat and by direct UI action. This unification (built-ins and exceptions as the same representation) was a deliberate, deep refactor — chat can modify anything, not just additions.

Chat flow: raw message → local name-mention resolution (`src/chat/mentions.py`, no LLM, exact-match against the roster, ambiguous names short-circuit locally without ever calling the model) → redact resolved names to opaque tokens → LLM call with one of the 7 typed tools → **proposal shown for explicit confirm/reject before anything is applied** (never auto-applied) → confirmed constraint lands in the same list real solves use.

## Frontend structure (current)

One page (`app/page.tsx`), stacked vertically, no navigation:

1. **DataZone** (`components/DataZone.tsx`) — file upload/column-mapping/manual category entry. Collapses to a one-line summary card once loaded; expands to a dense spreadsheet-style table (217 rows, checkboxes, free-text friend-request field per row).
2. **RunSettingsPanel** — a thin strip with 3 number inputs (class count, solver time limit, random seed).
3. **ChatPanel** + **ConstraintList**, side by side (chat wider) — the chat composer, and a settings-table-style list of all 10+ rules with hard/soft toggles, active toggles, remove buttons.
4. **ResultsZone** — a dense drag-and-drop kanban board (one column per class, one card per student), violations list, manual re-optimize/export actions. Only appears meaningfully once a solve has run.

Design tokens: `--cw-*` CSS custom properties in `app/globals.css`, light-only, muted navy/sky palette, dot-based status indicators (not pills, not colored badges), Rubik font, no gradients/glow per house style.

## What's been tried for the "conversational agent" feel, and my honest read on why it still isn't landing

Two passes so far:
- Pass 1 built the chat/constraint-list mechanism itself (confirm-before-apply, etc.) but visually it was just a chat box parked next to a settings table — no sense of an agent doing anything.
- Pass 2 added surface-level "liveness": an assistant avatar, an animated typing/thinking indicator while waiting on a reply, entrance + highlight animation on newly-confirmed constraint rows, rebalanced the layout so chat is visually dominant.

**That second pass was polish on an unchanged structure, not a rethink.** The actual information architecture is still four separate, heavy, traditionally-styled "app modes" stacked on one page — a spreadsheet, a settings-table, a kanban board, and a chat box that's one contributor among several, not the spine of the experience. Nothing about the *shape* of the page changed. A chat bubble that pulses when you send it doesn't make a settings table beside it feel like a conversation.

If "speaking to an expert and seeing the actions" is the actual goal, the open question worth deciding before touching code again: should the conversation become the *primary* surface — with the roster, the current rule set, and results appearing as artifacts rendered *inside* the conversation thread (like inline generative-UI cards), rather than as permanent side panels that happen to animate — or is the goal something else entirely (e.g. a completely different layout metaphor, not chat-centric at all)? That's the fork I don't think I can resolve by iterating on the current structure again.

## Known constraints for any redesign

- Backend API surface (`frontend/lib/api.ts` types) is reasonably stable and shouldn't need to change for a frontend redesign — `/api/constraints`, `/api/chat/*`, `/api/run-config`, `/api/results/*`, `/api/optimize`, `/api/export.xlsx`, plus the data/mapping endpoints from the original wizard.
- Real dataset: `רשימה כללית לאיזונית.xlsx`, 217 students, categories are differential / ethiopian-origin / inclusion / ח"מ, plus friendship requests (free text names), current school, current class, academic level (3 levels).
- RTL Hebrew throughout, no English fallback needed.
- The solve itself must stay fully deterministic and auditable — the LLM proposes, a human confirms, CP-SAT decides. Whatever the new UI looks like, that boundary shouldn't move.
- No `LLM_API_KEY` is configured in this dev environment — chat proposal generation can't be tested live here, only the confirm/reject/apply mechanics around it.

## File map

```
backend/
  main.py, session_store.py, solver_inputs.py, schemas.py, legacy_rules.py(removed)
  routers/{workbook,validation,config,optimize,export,chat}.py
  llm/{provider,tools,prompts,tokenization,narration}.py
src/
  optimizer.py, constraints.py, feasibility.py, metrics.py, export_excel.py
  column_mapping.py, friendship_graph.py, manual_adjustments.py, excel_loader.py
  chat/mentions.py
frontend/
  app/page.tsx, app/globals.css, app/layout.tsx
  components/{DataZone,ChatPanel,ConstraintList,RunSettingsPanel,ResultsZone}.tsx
  components/{ClassWall,StudentDrawer,DataTable,Skeletons,Icon,FormField}.tsx
  components/ui/primitives.tsx
  lib/{api,bootstrap,steps}.ts
tests/  (76 passing — backend/solver only, no frontend tests)
```
