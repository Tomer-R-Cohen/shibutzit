// Auto-prepares the default workbook so the app opens straight on the
// assignment screen with data already loaded, mapped and checked — no
// click-through of a "data" wizard for the common case.
//
// The pipeline is defensive: if a previous session already mapped the data
// (including a user's custom mapping done on the /steps/data override screen),
// we keep it and only re-run the read-only checks. We only rebuild from the
// default file when the backend has no usable state yet (fresh session or a
// backend restart that dropped the in-memory session).

import {
  MappingGuessResponse,
  applyMapping,
  getFeasibility,
  getMappingGuess,
  getValidation,
  loadWorkbook,
} from "@/lib/api";
import { getFlags, setFlag } from "@/lib/steps";

export interface DataReadiness {
  // true when the assignment screen can proceed to run/show results.
  ready: boolean;
  // true when the default guess left a required field unmapped, so the user
  // has to open the manual mapping override screen.
  needsMapping: boolean;
  studentCount: number | null;
  hasErrors: boolean;
  allFeasible: boolean;
}

// Default physical layout of the standard workbook (header row 4, data 5–221).
const DEFAULT_LOAD = { useDefault: true, headerRow: 4, firstDataRow: 5, lastDataRow: 221 };

// Required fields that must resolve to a column. `ethiopian_origin` is exempt
// because the source file encodes it in the origin column and the mapper may
// legitimately leave it unmapped — matching the /steps/data validation.
function unmappedRequired(guess: MappingGuessResponse): string[] {
  return guess.required_fields.filter(
    (f) => f !== "ethiopian_origin" && !guess.mapping[f] && !guess.manual_fields.includes(f)
  );
}

async function runChecks(): Promise<{ hasErrors: boolean; allFeasible: boolean; studentCount: number }> {
  const [validation, feasibility] = await Promise.all([getValidation(), getFeasibility()]);
  setFlag("validated", !validation.has_errors);
  return {
    hasErrors: validation.has_errors,
    allFeasible: feasibility.all_feasible,
    studentCount: feasibility.total_students,
  };
}

export async function ensureDataReady(): Promise<DataReadiness> {
  const flags = getFlags();

  // Fast path: a prior mapping exists. Trust it and only re-run checks. If the
  // backend lost the session, getValidation/getFeasibility throw and we rebuild.
  if (flags.loaded && flags.mapped) {
    try {
      const checks = await runChecks();
      return { ready: true, needsMapping: false, ...checks };
    } catch {
      /* backend has no mapped data — fall through to rebuild from default */
    }
  }

  // Rebuild from the default workbook. getMappingGuess needs a loaded workbook;
  // if it isn't loaded yet, load the default first and retry.
  let guess: MappingGuessResponse;
  try {
    guess = await getMappingGuess();
  } catch {
    await loadWorkbook(DEFAULT_LOAD);
    setFlag("loaded", true);
    guess = await getMappingGuess();
  }
  setFlag("loaded", true);

  if (unmappedRequired(guess).length > 0) {
    return { ready: false, needsMapping: true, studentCount: null, hasErrors: false, allFeasible: true };
  }

  // applyMapping preserves an existing manual-entry table (backend only builds
  // an empty one when none exists), so re-applying the guess is safe.
  const applied = await applyMapping(guess.mapping, guess.manual_fields);
  setFlag("mapped", true);

  const checks = await runChecks();
  return {
    ready: true,
    needsMapping: false,
    studentCount: applied.student_count ?? checks.studentCount,
    hasErrors: checks.hasErrors,
    allFeasible: checks.allFeasible,
  };
}
