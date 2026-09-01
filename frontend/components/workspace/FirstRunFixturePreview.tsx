"use client";

import type { MappingGuessResponse } from "@/lib/api";
import DatasetOnboarding, { DatasetOnboardingPreview } from "./DatasetOnboarding";
import TopBar from "./TopBar";
import Welcome from "./Welcome";

export const FIRST_RUN_FIXTURES = new Set([
  "welcome",
  "upload",
  "upload-busy",
  "upload-mapping",
  "upload-error",
]);

const MAPPING_GUESS: MappingGuessResponse = {
  columns: ["שם פרטי", "שם משפחה", "בית ספר", "רמה", "סטטוס 2", "בקשות חברות"],
  required_fields: ["first_name", "last_name", "current_school", "academic_level", "inclusion", "hamar"],
  optional_fields: ["friend_requests_raw"],
  labels: {
    first_name: "שם פרטי",
    last_name: "שם משפחה",
    current_school: "בית ספר נוכחי",
    academic_level: "רמה לימודית",
    inclusion: "שילוב",
    hamar: "חינוך מיוחד",
  },
  mapping: {
    first_name: "שם פרטי",
    last_name: "שם משפחה",
    current_school: null,
    academic_level: null,
    inclusion: null,
    hamar: null,
    friend_requests_raw: "בקשות חברות",
  },
  manual_fields: [],
  problems: [],
};

const PREVIEWS: Record<string, DatasetOnboardingPreview> = {
  upload: { phase: "needsFile" },
  "upload-busy": {
    phase: "needsFile",
    busy: true,
    loadStage: "mapping",
    selectedFileName: "תלמידות שכבה ז.xlsx",
  },
  "upload-mapping": { phase: "mapping", mappingGuess: MAPPING_GUESS },
  "upload-error": { phase: "error" },
};

export default function FirstRunFixturePreview({ name }: { name: string }) {
  if (name === "welcome") {
    return (
      <div className="ws-shell">
        <TopBar runState="none" onRunSolve={() => {}} canSolve={false} showRunStatus={false} />
        <Welcome onPlan={() => {}} onUpload={() => {}} />
      </div>
    );
  }

  return (
    <div className="ws-shell">
      <TopBar runState="none" onRunSolve={() => {}} canSolve={false} onStartOver={() => {}} showRunStatus={false} />
      <DatasetOnboarding
        onReady={() => {}}
        onWarning={() => {}}
        onBack={() => {}}
        preview={PREVIEWS[name] ?? PREVIEWS.upload}
      />
    </div>
  );
}
