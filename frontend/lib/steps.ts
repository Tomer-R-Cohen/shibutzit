export interface StepDef {
  slug: string;
  index: number;
  title: string;
  subtitle: string;
  // The flag whose truth marks this step "complete" in the top stepper.
  doneFlag?: keyof WizardFlags;
}

// The product is a single linear workflow with exactly three primary
// destinations: upload the roster → configure the rules → generate & review the
// assignment. Everything else (data preview, column mapping, validation,
// feasibility, violations, manual moves, versions, export) lives *inside* one of
// these three screens — never as its own nav item.
export const STEPS: StepDef[] = [
  { slug: "data", index: 1, title: "העלאת נתונים", subtitle: "טעינת קובץ, בדיקת הנתונים והתאמת עמודות", doneFlag: "mapped" },
  { slug: "configure", index: 2, title: "הגדרות שיבוץ", subtitle: "כללים, יעדים חברתיים ונעילות" },
  { slug: "assign", index: 3, title: "תוצאות", subtitle: "הפקת שיבוץ, בדיקה, תיקונים וייצוא", doneFlag: "optimized" },
];

export const NAV_STEPS: StepDef[] = STEPS;

export type WizardFlags = {
  loaded: boolean;
  mapped: boolean;
  validated: boolean;
  optimized: boolean;
};

const KEY = "shibutz_wizard_flags";

const EMPTY_FLAGS: WizardFlags = { loaded: false, mapped: false, validated: false, optimized: false };

export function getFlags(): WizardFlags {
  if (typeof window === "undefined") return EMPTY_FLAGS;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return EMPTY_FLAGS;
    return JSON.parse(raw);
  } catch {
    return EMPTY_FLAGS;
  }
}

export const FLAGS_CHANGED_EVENT = "shibutz-flags-changed";

// useSyncExternalStore compares snapshots with Object.is, so the snapshot has
// to keep a stable identity while the underlying localStorage string is
// unchanged — otherwise every render would look like a store update.
let cachedRaw: string | null = null;
let cachedFlags: WizardFlags = EMPTY_FLAGS;

export function getFlagsSnapshot(): WizardFlags {
  if (typeof window === "undefined") return EMPTY_FLAGS;
  const raw = window.localStorage.getItem(KEY);
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      cachedFlags = raw ? JSON.parse(raw) : EMPTY_FLAGS;
    } catch {
      cachedFlags = EMPTY_FLAGS;
    }
  }
  return cachedFlags;
}

export function getServerFlagsSnapshot(): WizardFlags {
  return EMPTY_FLAGS;
}

export function subscribeToFlags(onChange: () => void): () => void {
  window.addEventListener("focus", onChange);
  window.addEventListener("storage", onChange);
  window.addEventListener(FLAGS_CHANGED_EVENT, onChange);
  return () => {
    window.removeEventListener("focus", onChange);
    window.removeEventListener("storage", onChange);
    window.removeEventListener(FLAGS_CHANGED_EVENT, onChange);
  };
}

export function setFlag(flag: keyof WizardFlags, value: boolean) {
  const flags = getFlags();
  flags[flag] = value;
  window.localStorage.setItem(KEY, JSON.stringify(flags));
  // "storage" only fires in *other* tabs/windows, not this one, so listeners
  // mounted in this same tab would otherwise stay stale until the window
  // loses and regains focus. Dispatch an explicit event so same-tab
  // listeners can react immediately.
  window.dispatchEvent(new Event(FLAGS_CHANGED_EVENT));
}

export function resetFlags() {
  window.localStorage.removeItem(KEY);
  window.localStorage.removeItem(SUMMARY_KEY);
}

// Short one-line summaries shown for collapsed/completed accordion
// sections (e.g. "נטען בהצלחה: 214 שורות") so users don't need to
// re-expand a finished section just to confirm what happened.
const SUMMARY_KEY = "shibutz_section_summaries";

export function getSummaries(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(SUMMARY_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

export function setSummary(section: string, text: string) {
  const summaries = getSummaries();
  // Skip redundant writes: rewriting the same value would still dispatch the
  // change event, which can bounce back through listeners into a render loop.
  if (summaries[section] === text) return;
  summaries[section] = text;
  window.localStorage.setItem(SUMMARY_KEY, JSON.stringify(summaries));
  window.dispatchEvent(new Event(FLAGS_CHANGED_EVENT));
}
