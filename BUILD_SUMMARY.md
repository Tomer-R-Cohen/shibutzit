# Build Summary — Class Assignment App (שיבוץ תלמידות לכיתות ז')

## Run command

Two terminals from the repo root (see `README.md` for details):

```
# backend
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000

# frontend
cd frontend && npm install && npm run dev   # opens http://localhost:3000
```

The Streamlit prototype (`app.py`) was retired; the Next.js + FastAPI app is
the single UI. `src/` (all assignment logic) is unchanged.

## Excel column mapping (source: רשימה כללית לאיזונית.xlsx)

Header row is physical row 4, data rows 5–221, `Sheet1`, column A empty.

| Semantic field (app)         | Source column (Hebrew)      | Used for |
|---|---|---|
| `student_id`                 | מספר סידורי (col B)         | unique key everywhere; duplicate check |
| `last_name` / `first_name`   | שם משפחה / שם פרטי (C, D)   | display, name-based friendship matching |
| `current_school`             | ביה"ס נוכחי (E)             | source-school balance objective |
| `current_class`              | כיתה (F, 0–7, sometimes blank) | current-class balance objective |
| `ethiopian_origin`           | מוצא (G, 'א' marks Ethiopian) | hard/soft Ethiopian-origin range per class |
| `academic_level`             | הישגים לימודיים (H)         | academic balance objective, class avg score |

Blank spacer rows are filtered by dropping rows where the running-index
column (`מספר סידורי`) is `None`, per `src/excel_loader.py`'s
`index_column` filtering and `column_mapping.apply_mapping`'s
`student_id` synthesis fallback.

Fields **not present** in the source and wired as manual-entry /
importable-CSV fields (`src/column_mapping.py::OPTIONAL_MANUAL_FIELDS`,
the "הזנת נתונים ידנית" screen): `differential`, `inclusion`, `hamar` (ח"מ),
and `friend_requests_raw` (free-text, comma/semicolon/newline-separated
names, parsed by `src/friendship_graph.py`). Defaults are all False/empty;
edited via the name-aware bulk editor (auto-saved and persisted) or
bulk-replaceable via a CSV/Excel keyed by `student_id`.

## Unresolved data ambiguities

- **Differential / inclusion / ח"מ / friendship-request data does not
  exist in the source workbook at all.** The app supports entering it
  manually or importing a supplementary file, but it ships with zero
  real values for these fields until a user fills them in — there is no
  way to "recover" this information from the source file itself.
- **`סריקה.5.pdf` is an illegible handwritten scan** with no extractable
  text layer (confirmed via pdfplumber/pymupdf — empty text output).
  Rendered once to `sample_data/reference_scan.png` as a read-only
  reference image; a manual "target distribution" table lets a user type
  in numbers inspired by the scan, which then feeds an optional soft
  objective. No OCR/automatic
  parsing was attempted — the numbers in the scan (rough class-size
  totals ~33–36, a school × class grid) are too illegible to trust as
  authoritative.
- **Blank `כיתה` (current class) values**: some students have an empty
  current-class cell. These are kept as `NaN`/empty and simply form their
  own bucket for the current-class balance objective rather than being
  imputed or dropped.
- **Duplicate names vs duplicate records**: `src/validation.py`
  distinguishes duplicate `student_id` (hard error, blocks optimization)
  from duplicate (first, last) name pairs (warning only, since two
  different real students can share a name) — the app never silently
  merges or drops either.
- **Friendship name matching**: normalized-string matching only (nikud,
  whitespace, quote-mark variants). Typos beyond that, or names matching
  multiple students, are surfaced as unmatched/ambiguous in a diagnostics
  report rather than guessed.

## Objective function and constraint hierarchy

**Hard constraints** (each individually toggleable to soft in the rules
drawer, `src/optimizer.py::SolverConfig`): every student assigned exactly
once (always hard); class-size balance (max−min ≤ configurable diff,
default 1); ≤N differential per class (default 1); Ethiopian-origin per
class in [min,max] (default 3–4); inclusion per class in [min,max]
(default 2–2); ח"מ per class in [min,max] (default 1–2); locked-student
assignments; no out-of-range class indices; duplicate detection blocks
the workflow before optimization ever runs.

Before solving, `src/feasibility.py::analyze_feasibility` runs pure
arithmetic checks (e.g. total Ethiopian-origin students vs.
`min_per_class * num_classes`) independent of CP-SAT, and reports which
hard rules are mathematically impossible given the actual population —
shown on the data screen and the home-screen ribbon, with an explicit path
to demote any infeasible hard rule to soft in the rules drawer, so the app
never just returns "no solution" without explanation.

**Soft objective** (single weighted `Maximize` in CP-SAT, see
`src/optimizer.py::optimize` and the "Optimization logic" section of
README.md for the full scaling rationale): rewards co-placement of mutual
friend pairs (`weight_mutual`) and students reaching 2+ co-placed
requested friends (`weight_two_friends`); penalizes the max−min spread of
per-class counts for each academic level, each source school, each
current class, and each of the differential/Ethiopian/inclusion/ח"מ
categories, each with its own configurable weight
(`weight_academic_balance`, `weight_school_balance`,
`weight_current_class_balance`, `weight_category_balance`). All terms are
counts or spreads in the range `0..num_students`, so no weight needs
extreme tuning to be effective, and weights are directly comparable in
the UI sliders (0–10).

## Testing

`32/32` tests pass (`.venv\Scripts\python.exe -m pytest tests/ -v`): the
`src/` unit tests cover validation, friendships, feasibility, and the
optimizer — the optimizer tests use a 12-student/2-class synthetic dataset
exercising every hard rule (size balance, differential cap, Ethiopian
range, inclusion exact count, ח"מ range, locking, invalid-config errors,
and the friendship reward). The backend auto-load pipeline and on-disk
session persistence were verified end to end against a live server,
including data surviving a real backend restart. The frontend passes
`tsc`, `eslint`, and `next build`.

## Design notes / known gaps

- Manual reassignment moves a student between classes from the class board
  (click a student, pick a class) rather than drag-and-drop, per the spec's
  explicit allowance ("no drag-and-drop needed").
- Post-solve manual moves are not persisted across a backend restart — only
  the *inputs* (rules, locks, typed category data, custom mapping) are; the
  assignment itself is a one-click re-run.
- The "prefer mutual over one-sided" social rule is implemented via separate
  reward terms (mutual co-placement vs. the 2+-friends count) rather than a
  single combined equation; this matches the spec's itemized objective list
  but is worth noting as a design choice.
