# 7th-Grade Class Assignment App — Client Specification

## 1. What the app does

A local application that assigns 7th-grade students into balanced classes
according to hard ("required") and soft ("preferred") rules, using an
optimization engine (Google OR-Tools CP-SAT). The user (teacher/principal)
opens a single screen, clicks "Generate Assignment," and gets a class
breakdown that can be manually edited and exported to Excel.

## 2. Architecture

| Component | Technology | Role |
|---|---|---|
| Frontend | Next.js (RTL, Hebrew UI) | Conversational workspace with roster and results workbenches |
| Backend | FastAPI (Python) | Data processing, optimization, export |
| Solver | Google OR-Tools CP-SAT | The assignment engine itself |
| Storage | Local files (`backend/.sessions/`) | Per-session state persistence |

There is no shared database, no authentication, no cloud server —
everything runs locally on a single machine. Each browser gets a unique
session id (`X-Session-Id`) stored in the browser (localStorage).

## 3. Running locally

Two terminal windows, from the project root.

```
# Terminal 1 — Backend
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm install
npm run dev
```

Then open in a browser: `http://localhost:3000`

## 4. Environment Variables

### Backend — `.env` file at the project root

A template exists at `.env.example`. Copy it to `.env` and fill in:

| Variable | Required? | Description | Default |
|---|---|---|---|
| `LLM_API_KEY` | No (chat only) | API key for the LLM provider (OpenAI-compatible). Only needed to enable the chat / rule-suggestion feature. The rest of the app works without it. | — |
| `LLM_BASE_URL` | No | OpenAI-compatible base URL | `https://api.moonshot.ai/v1` |
| `LLM_MODEL` | No | Model id | `kimi-k2.6` |

If `LLM_API_KEY` is not set, chat calls will fail with a clear error
(`LLMNotConfiguredError`) — the rest of the system (loading, validation,
solving, export) works normally.

### Frontend — `frontend/.env.local` (already present)

| Variable | Required? | Description | Default |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE` | No | Backend URL | `http://localhost:8000` |

## 5. Input required from the client

### Source file
An Excel file named `רשימה כללית לאיזונית.xlsx` at the project root (the
file itself is **not** part of the codebase — must be supplied separately;
not stored in git).

Expected layout:
- Sheet `Sheet1`, header row at row 4, data rows 5–221.
- Columns B–H: running index, last name, first name, current school,
  current class (0–7, sometimes blank), origin (`א` = Ethiopian-origin),
  academic achievement (high/average/low).

### Data not present in the source file (must be entered manually or imported via a separate CSV/Excel)
- Differential-student status
- Inclusion status
- Special-needs ("ח"מ") status
- Friendship requests (a free-text list of names per student)

Until this data is entered, the demographic hard constraints cannot be
satisfied and the assignment will be reported as infeasible (with a
one-click option to relax them to soft constraints).

## 6. Assignment rules (editable on the "Rules" screen)

| Rule | Default | Can be made soft? |
|---|---|---|
| Every student assigned to exactly one class | — | No (always hard) |
| Class size balance | max diff of 1 | Yes |
| Max differential students per class | 1 | Yes |
| Ethiopian-origin students per class | 3–4 | Yes |
| Inclusion students per class | exactly 2 | Yes |
| Special-needs ("ח"מ") students per class | 1–2 | Yes |
| Manual lock (keep student in class) | — | — |
| Class index within valid range | — | No |

The (soft) objective function maximizes mutual/requested friendships
placed together, and balances achievement level, source school, current
class, and demographic categories — each with a tunable weight.

## 7. Output

Excel export (`src/export_excel.py`) with sheets: "Assignment by Class,"
"Student List," "Metrics," "Violations," "Friendship Requests,"
"Settings" (including the random seed for reproducibility), and "Source
Data." The original input workbook is never modified.

## 8. Known limitations

- `סריקה.5.pdf` is not machine-readable (a hand-written scan with no text
  layer) — used as a reference image only; any target distribution
  implied by it must be entered manually.
- No support for multiple simultaneous users on the same data (session
  per browser, no shared database, no auth).
- The sample file `sample_data/synthetic_students.xlsx` contains fake
  data for testing only.

## 9. Tests

```
.venv\Scripts\python.exe -m pytest tests/ -v
```

## 10. Contact / support

_(To be filled in: technical contact, support channel, SLA if applicable.)_
