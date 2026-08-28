# שיבוץ תלמידות לכיתות ז' — Class Assignment App

A local-first application that assigns 7th-grade students into balanced
classes under hard and soft constraints, using Google OR-Tools CP-SAT.

The core logic lives in `src/` and is exposed through a single UI:

- **Next.js frontend + FastAPI backend** — an RTL Hebrew conversational
  workspace for teachers and principals. A new session starts with a choice:
  plan the rules and required columns with the assistant, or upload a roster
  and proceed to validation, solving, inspection, manual adjustment, and export.

> An earlier Streamlit prototype (`app.py`) was retired in favor of this
> UI. `src/` is unchanged and remains the single source of truth for all
> assignment logic.

## Setup

Two terminals, both from the repo root.

```
# Terminal 1 — backend (installs deps into the existing .venv the first time):
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000

# Terminal 2 — frontend:
cd frontend
npm install
npm run dev
```

Then open http://localhost:3000. The frontend talks to the backend at
`http://localhost:8000` by default (override via `frontend/.env.local`,
`NEXT_PUBLIC_API_BASE`). Each browser gets its own `X-Session-Id` (stored in
`localStorage`); the backend keeps one session per id.

Config is via environment variables — see `.env.example` (backend: LLM
provider, CORS) and `frontend/.env.example` (API base URL) for the full
list and defaults.

## How the app is organized

The UI is one working screen plus two supporting surfaces:

1. **שיבוץ כיתות (home)** — on open it silently loads the default workbook,
   applies the auto-guessed column mapping, and runs the data/feasibility
   checks, then shows a readiness ribbon and the primary **הפקת שיבוץ**
   button. Results (class board, per-student table, health summary,
   violations) appear inline; students can be moved between classes, and the
   whole thing exports to Excel.
2. **כללי שיבוץ (rules drawer)** — opened from the home screen. Class count,
   size balance, social targets, and the demographic ranges (differential /
   Ethiopian-origin / inclusion / ח"מ), each toggleable **חובה** (hard) or
   **מועדף** (soft). Weight tuning, run time limit, the reproducibility seed,
   and pre-locking live behind an "advanced" disclosure. **Changes auto-save**
   — there is no save button.
3. **נתונים ומקור (data screen)** — the override/advanced path, normally
   untouched. Load a different workbook, remap columns, run the checks, and —
   most importantly — **bulk-enter the manual category data** (see below).

### Persistence

The user-provided inputs — tuned rules, pre-locks, the manually typed
category data, and any custom column mapping — are persisted to disk per
session (`backend/.sessions/`, git-ignored). They survive a browser refresh,
a backend restart, and a machine reboot, so nobody has to retype category
data for ~200 students. Derived state (the loaded workbook, mapped table,
reports, and the solved assignment) is *not* persisted — it is rebuilt
cheaply by re-loading the source file and re-running the solver with one
click.

## Data expectations

The app defaults to loading `רשימה כללית לאיזונית.xlsx` (never modified — all
processing happens on in-memory copies). Its known physical layout:

- Sheet `Sheet1`, header row at physical row 4, data rows 5–221.
- Columns B–H: running index, last name (`שם משפחה`), first name
  (`שם פרטי`), current school (`ביה"ס נוכחי`), current class (`כיתה`, 0–7,
  sometimes blank), origin (`מוצא`, `א` = Ethiopian-origin), academic
  achievement (`הישגים לימודיים`: מצטיינת / בינונית / חלשה).
- Some data rows are blank spacers; these are dropped based on the running
  index being empty.

The source file has **no columns** for differential-student status,
inclusion status, ח"מ status, or friendship requests. These are entered on
the **"הזנת נתונים ידנית"** screen — a name-aware bulk editor (search by name
or id, per-student category toggles and a friends-requests field) that
auto-saves and persists — or imported from a supplementary CSV/Excel keyed by
student id. **Until this data is entered, the demographic hard-constraints
cannot be met and the solve is reported infeasible** (with a one-click path to
soften them).

A different workbook can be uploaded instead, as long as you adjust the
header/data-row settings and remap columns on the data screen.

## Optimization logic

Binary CP-SAT variables `x[student, class]` indicate assignment. All "hard"
rules below are individually toggleable to "soft" in the rules drawer:

1. Every student assigned to exactly one class (always hard).
2. Class sizes balanced (max−min ≤ configurable diff, default 1).
3. At most N differential students per class (default 1).
4. Ethiopian-origin students per class within [min, max] (default 3–4).
5. Inclusion students per class within [min, max] (default exactly 2).
6. ח"מ students per class within [min, max] (default 1–2).
7. Manually locked students keep their class.
8. No assignment to a class index outside `0..num_classes-1`.
9. Duplicate student ids/names are detected and reported before the optimizer
   runs — never silently deduplicated.

**Feasibility pre-check** (`src/feasibility.py`): before solving, arithmetic
totals are checked against each hard bound (e.g. total Ethiopian-origin
students vs. `min_per_class * num_classes`) and reported in plain language,
independent of the solver. Any hard rule found infeasible can be demoted to
soft directly in the rules drawer.

**Objective** (soft terms, all added to one CP-SAT `Maximize`):

```
maximize:
    + weight_mutual        * (# students with >=1 co-placed mutual friend)
    + weight_two_friends   * (# students with >=2 co-placed requested friends)
    - weight_academic_balance      * sum of per-level (max-min) class-count spread
    - weight_school_balance        * sum of per-school (max-min) spread
    - weight_current_class_balance * sum of per-current-class (max-min) spread
    - weight_category_balance      * sum of per-category (differential/ethiopian/
                                      inclusion/hamar) (max-min) spread
```

Every term is a **count of students** or a **spread between 0 and
num_students**, so all terms live on a comparable O(n) scale before their
configurable weight is applied — no term needs an extreme weight to matter.

## Friendship model

Directed graph: `A -> B` means "A requested B". Mutual = both directions
present. Names are normalized (trim, collapse whitespace, unify nikud and
quote-mark variants, casefold) and matched by full-name lookup, preferring a
unique match. Ambiguous or unmatched names are never auto-merged — they are
surfaced in the checks/diagnostics reports for manual resolution.

## Excel export

`src/export_excel.py` builds a workbook with sheets: `שיבוץ לפי כיתות`,
`רשימת תלמידות`, `מדדים`, `חריגות`, `בקשות חברות`, `הגדרות`, `נתוני מקור`.
Hebrew/RTL is preserved, headers are frozen and auto-filtered, and
violation/warning cells get conditional highlighting. The `הגדרות` sheet
records the exact `SolverConfig` (including the random seed) used, for
reproducibility. **The original input workbook is never written to.**

## Tests

```
.venv\Scripts\python.exe -m pytest tests/ -v
```

## Limitations

- **`סריקה.5.pdf` is not machine-readable.** It's a single-page hand-written
  scan with no extractable text layer; it is rendered once to
  `sample_data/reference_scan.png` as a reference image only. Any "target
  distribution" implied by the scan must be typed in manually — it is never
  parsed automatically.
- Differential / inclusion / ח"מ / friendship-request data do not exist in
  the source workbook and must be entered manually or imported — the app does
  not infer or guess these.
- Friendship name matching is normalized-string based; typos beyond
  nikud/whitespace/quote normalization are reported as unmatched for manual
  handling, not guessed.
- Sessions are per-browser, single-machine, no auth, no shared database.
- The synthetic dataset in `sample_data/synthetic_students.xlsx` uses clearly
  fake placeholder names and is for tests/demos only.

## Project layout

```
backend/                   FastAPI wrapper over src/
  main.py                   app + CORS + session/health routes
  session_store.py          per-session state + on-disk persistence of inputs
  schemas.py                Pydantic request/response models
  routers/{workbook,validation,config,optimize,export}.py
                            thin wrappers around src/ (no logic changes)
frontend/                  Next.js RTL one-screen UI
  app/steps/{assign,configure,data}/page.tsx
  components/               ClassBoard, RulesPanel/RulesDrawer,
                            ManualEntryEditor, DataTable, StudentDrawer, ...
  lib/{api.ts,bootstrap.ts,steps.ts}
                            typed fetch client, auto-load pipeline, nav model
src/
  excel_loader.py           workbook loading (no hardcoded column letters)
  column_mapping.py         semantic field mapping + manual-entry support
  validation.py             duplicate/data-quality checks
  friendship_graph.py       name normalization + directed friendship graph
  feasibility.py            pre-solve arithmetic feasibility checks
  optimizer.py              CP-SAT model, hard/soft constraints, objective
  metrics.py                per-class/per-student/global metric tables
  manual_adjustments.py     lock/reassign after solving
  export_excel.py           multi-sheet Excel export
tests/                     pytest unit tests (synthetic data)
sample_data/
  generate_synthetic.py     generator script
  synthetic_students.xlsx   synthetic students, all category combos
  reference_scan.png        rendered page 1 of the illegible scan
```
