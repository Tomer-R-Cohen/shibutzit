# שיבוץ תלמידות לכיתות ז' — Class Assignment App

A local-first Streamlit application that assigns 7th-grade students into
balanced classes under hard and soft constraints, using Google OR-Tools
CP-SAT.

## Setup

```
pip install -r requirements.txt
streamlit run app.py
```

(This project uses the existing venv at `.venv`; on Windows:
`.venv\Scripts\python.exe -m streamlit run app.py`.)

Run tests:

```
.venv\Scripts\python.exe -m pytest tests/ -v
```

## Data expectations

The app defaults to loading `רשימה כללית לאיזונית.xlsx` (never modified —
all processing happens on in-memory copies). Its known physical layout:

- Sheet `Sheet1`, header row at physical row 4, data rows 5–221.
- Columns B–H: running index, last name (`שם משפחה`), first name
  (`שם פרטי`), current school (`ביה"ס נוכחי`), current class (`כיתה`,
  0–7, sometimes blank), origin (`מוצא`, `א` = Ethiopian-origin), academic
  achievement (`הישגים לימודיים`: מצטיינת / בינונית / חלשה).
- Some data rows are blank spacers; these are dropped based on the running
  index being empty.

The source file has **no columns** for differential-student status,
inclusion status, ח"מ status, or friendship requests. The column-mapping
screen (step 3) lets you mark any field as "not present / enter manually"
and then fill it in via an editable table (`st.data_editor`), or import a
supplementary CSV/Excel keyed by student id.

A different workbook can be uploaded instead, as long as you adjust the
header/data-row settings in step 1 and remap columns in step 3.

## Optimization logic

Binary CP-SAT variables `x[student, class]` indicate assignment. All
"hard" rules below are individually toggleable to "soft" in the settings
screen (step 6):

1. Every student assigned to exactly one class (always hard).
2. Class sizes balanced (max−min ≤ configurable diff, default 1).
3. At most N differential students per class (default 1).
4. Ethiopian-origin students per class within [min, max] (default 3–4).
5. Inclusion students per class within [min, max] (default exactly 2).
6. ח"מ students per class within [min, max] (default 1–2).
7. Manually locked students keep their class.
8. No assignment to a class index outside `0..num_classes-1`.
9. Duplicate student ids/names are detected and reported (step 4) before
   the optimizer runs — never silently deduplicated.

**Feasibility pre-check** (step 5, `src/feasibility.py`): before solving,
arithmetic totals are checked against each hard bound (e.g. total
Ethiopian-origin students vs. `min_per_class * num_classes`) and reported
with plain-language explanations, independent of the solver. Any hard rule
found infeasible can be demoted to soft directly in step 6.

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

Every term is expressed as a **count of students** or a **spread between 0
and num_students**, so all terms live on a comparable O(n) scale before
their configurable weight is applied — no term needs an extreme weight to
matter. Mutual-friend co-placement is rewarded more than one-sided
co-placement because only mutual pairs feed the `weight_mutual` term (the
`weight_two_friends` term additionally rewards any co-placed requested
friend, mutual or not, once a student reaches 2+).

Locking, class-size, and category-count constraints are added as hard
linear constraints only when their toggle is enabled; when disabled they
simply don't constrain the model (a fully-soft version of them is not
auto-added, per the "toggle to soft" semantics — used together with the
balance objective terms above and the feasibility pre-check to avoid dead
ends).

## Friendship model

Directed graph: `A -> B` means "A requested B". Mutual = both directions
present. Names are normalized (trim, collapse whitespace, unify nikud and
quote-mark variants, casefold) and matched by full-name lookup, preferring
a unique match. Ambiguous (multiple candidates) or unmatched names are
never auto-merged — they're surfaced in the validation report (step 4) and
the friendship-diagnostics tab (step 9) for manual resolution.

## Output views

1. **Class overview** — size, academic distribution/average, category
   counts, school/current-class distribution, mutual/two-friends %,
   violations, quality score.
2. **Student assignment table** — id, name, assigned class, all category
   flags, friendship-satisfaction fields, lock status, warnings.
3. **Global metrics** — totals, class-size range, satisfaction %s,
   satisfied/partial/unsatisfied request counts, violation counts, solver
   status/runtime/objective.
4. **Violations & exceptions report** — rule, class, expected vs actual,
   severity, hard/soft, suggested correction.
5. **Friendship diagnostics** — unmatched/ambiguous names, students with no
   friendship data.

## Excel export

`src/export_excel.py` builds a workbook with sheets: `שיבוץ לפי כיתות`,
`רשימת תלמידות`, `מדדים`, `חריגות`, `בקשות חברות`, `הגדרות`, `נתוני מקור`.
Hebrew/RTL is preserved, headers are frozen and auto-filtered, and
violation/warning cells get conditional highlighting. The `הגדרות` sheet
records the exact `SolverConfig` (including the random seed) used, for
reproducibility. **The original input workbook is never written to** —
only in-memory DataFrames are exported to a new bytes buffer.

## Limitations

- **`סריקה.5.pdf` is not machine-readable.** It's a single-page
  hand-written scan with no extractable text layer; OCR/structured parsing
  was judged unreliable given the illegibility of the handwriting. It is
  rendered once to `sample_data/reference_scan.png` and shown as a
  reference image in the sidebar. Any "target distribution" implied by the
  scan must be typed in manually (step 5) — it is never parsed
  automatically, and is treated as a soft objective only if you fill it
  in.
- The source workbook has blank `כיתה` (current class) values for some
  students; these are preserved as empty/`NaN` and simply form their own
  bucket in current-class balance objectives.
- Differential / inclusion / ח"מ / friendship-request data do not exist in
  the source workbook and must be entered manually or imported via a
  supplementary file — the app does not infer or guess these.
- Friendship name matching is normalized-string based; it will not resolve
  names with typos beyond nikud/whitespace/quote normalization — such
  cases are reported as unmatched for manual handling, not guessed.
- The synthetic dataset in `sample_data/synthetic_students.xlsx` uses
  clearly fake placeholder names and is for tests/demos only.

## Project layout

```
app.py                     Streamlit UI, wires the full workflow
src/
  excel_loader.py           workbook loading (no hardcoded column letters)
  column_mapping.py         semantic field mapping + manual-entry support
  validation.py             duplicate/data-quality checks
  friendship_graph.py       name normalization + directed friendship graph
  feasibility.py            pre-solve arithmetic feasibility checks
  optimizer.py               CP-SAT model, hard/soft constraints, objective
  metrics.py                 per-class/per-student/global metric tables
  manual_adjustments.py     lock/reassign after solving
  export_excel.py           multi-sheet Excel export
tests/                      pytest unit tests (26 tests, synthetic data)
sample_data/
  generate_synthetic.py      generator script
  synthetic_students.xlsx    ~28 synthetic students, all category combos
  reference_scan.png         rendered page 1 of the illegible scan
```
