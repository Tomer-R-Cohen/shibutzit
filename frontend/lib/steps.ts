// Readiness flags for the single-page app (see app/page.tsx and
// lib/bootstrap.ts). Used internally to short-circuit re-running the full
// load/map/validate sequence when a prior session already did it -- not
// tied to any navigation UI (there isn't any; the app is one screen).

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

export function setFlag(flag: keyof WizardFlags, value: boolean) {
  const flags = getFlags();
  flags[flag] = value;
  window.localStorage.setItem(KEY, JSON.stringify(flags));
}

export function resetFlags() {
  window.localStorage.removeItem(KEY);
}
