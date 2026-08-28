# SPEC — שיבוץ תלמידות לכיתות ז' (Class Assignment App)

Roadmap in five stages. Stages 1–4 are built and working end to end;
stage 5 is in progress. (Verified 2026-08-25: 125 backend tests pass,
frontend TypeScript is clean, and ESLint reports no errors.)

---

## Stage 1 — Core assignment engine ✅ done

The solver itself, independent of any UI.

- `src/` — Excel loading (no hardcoded column letters), column mapping,
  duplicate/data-quality validation, friendship graph (directed,
  normalized-name matching), pre-solve feasibility analysis, CP-SAT
  optimizer (hard + soft constraints, weighted objective), metrics,
  manual post-solve adjustments, multi-sheet Excel export.
- 32/32 unit tests passing, synthetic 12-student dataset exercising every
  hard rule.

## Stage 2 — Web app (backend + frontend) ✅ done

Replaced the retired Streamlit prototype with a dedicated app, `src/`
unchanged as the logic source of truth.

- **Backend** (FastAPI): session-per-browser model (`X-Session-Id`),
  on-disk persistence of inputs (rules, locks, manual category data,
  column mapping) in `backend/.sessions/`, routers for
  workbook/validation/config/optimize/export.
- **Frontend** (Next.js, RTL Hebrew): three-screen flow — שיבוץ כיתות
  (home: auto-load → validate → solve → edit → export), כללי שיבוץ
  (rules drawer), נתונים ומקור (workbook override, column remap, bulk
  manual data entry).
- Auto-load pipeline on open; class board with click-to-reassign;
  readiness ribbon surfacing feasibility problems with a one-click
  hard→soft demotion path.

## Stage 3 — Conversational constraint backend ✅ done

An LLM-backed chat surface for describing constraints in natural
language, sitting behind an explicit human-confirmation gate — the model
never writes to `sess.constraints` directly.

- `backend/llm/` — swappable OpenAI-compatible provider (`LLM_API_KEY` /
  `LLM_BASE_URL` / `LLM_MODEL`, Kimi by default), tool-calling schemas,
  system-prompt builder.
- `backend/routers/chat.py` — name-mention resolution/redaction before
  any LLM call (ambiguous/unmatched names short-circuit locally, never
  reach the model), single pending-proposal-per-turn flow
  (`/api/chat/message` → `/api/chat/confirm` / `/api/chat/reject`), plus
  a direct CRUD surface (`/api/constraints`) for the same constraint list.

## Stage 4 — Conversational workspace frontend ✅ done

The three-screen wizard from Stage 2 was retired and replaced by a single
conversational workspace (`frontend/app/page.tsx` +
`frontend/components/workspace/`): a dominant chat/timeline pane
(`Conversation.tsx`) backed live by `/api/chat/*`, plus a contextual
inspector pane that opens whatever the conversation references
(constraint detail, constraint list, roster, results). State orchestration
is centralized in `lib/workspace.ts` (`useWorkspace` hook) rather than
scattered booleans in `page.tsx`.

- Chat panel fully wired: message send, proposal cards with Hebrew
  rationale + hard/soft label, confirm/reject → `/api/chat/{message,
  confirm,reject}`; chat history rehydrated from `/api/chat/history` on
  mount so it survives a refresh.
- Constraint list/detail views read through `/api/constraints`, shared
  with the chat-proposal path — one source of truth, as planned.
- Solve trigger, infeasibility narration, and the relaxation-proposal
  flow (soften one conflicting hard rule) run through the same
  timeline/proposal UI as chat-originated changes.
- Dev-only `?fixture=<name>` escape hatch renders hand-written fixture
  state instead of calling the real backend, for screenshotting
  LLM-gated states without an API key (`lib/fixtures.ts`,
  `FixturePreview.tsx`) — never active in production builds.
- The full roster editor and class-board workbenches are wired into the
  workspace as full-screen dialogs. The result board supports moving and
  locking students, category filtering, student detail, and export.

## Stage 5 — Correctness hardening & client handoff 🟨 in progress

- ✅ Server-owned input/solve revisions now determine whether a result is
  current; the browser timeline is narrative only.
- ✅ Manual adjustments are explicitly distinguished from solver output.
- ✅ Roster edits invalidate validation/friendship caches, retain extra
  school-specific columns, and rebuild those inputs before every solve.
- ✅ Agent follow-up actions are structured API data rather than parsed
  from Markdown formatting.
- ✅ Session writes use atomic file replacement.
- Add frontend component/end-to-end coverage for the principal user flows.
- Model missing manual category values as unknown rather than false.
- Add a detailed solver audit artifact with objective contributions and
  optimality information.
- Fill in the placeholder support-contact section of `CLIENT_SPEC.md`.
- Decide and document a real answer for the illegible `סריקה.5.pdf`
  target distribution (currently: manual entry only, no OCR attempted).
- Review multi-user/no-auth limitation — confirm single-machine,
  session-per-browser is acceptable for actual deployment, or scope a
  shared-backend/auth story if not.
- Final pass on end-to-end testing with the real (non-synthetic) source
  workbook, and a documented rollback/support plan for the school.

---

## Verification (2026-08-13)

Ran the full test/build suite from a clean environment to confirm the
above stages actually work, not just compile:

- **Backend**: `.venv` was missing `openai` and had a `httpx`/`starlette`
  mismatch (`starlette` needs `httpx2` for its `TestClient`, which wasn't
  installed) — both fixed by `pip install -r requirements.txt`. After
  that, `pytest tests/ -v` passed. Current verification on 2026-08-25:
  **125/125 passed** (validation, friendships,
  feasibility, optimizer, tokenization, mention resolution, tool schemas,
  chat router, narration, optimize router).
- **Frontend**: `node_modules` was missing `@radix-ui/react-dialog` and
  `use-stick-to-bottom` despite being declared in `package.json` — fixed
  by `npm install`. After that: `tsc --noEmit` clean, `eslint .` clean
  (one pre-existing non-blocking warning about `useReactTable` memoization
  in `DataTable.tsx`), `next build` clean.
- No new tests were needed — coverage across `src/`, `backend/`, and
  `backend/llm/` was already thorough; the only failures found were
  environment/dependency drift, not missing coverage or broken logic.
