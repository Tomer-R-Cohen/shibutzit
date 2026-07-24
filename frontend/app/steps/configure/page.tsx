"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/primitives";
import { Icon } from "@/components/Icon";
import RulesPanel from "@/components/RulesPanel";
import { ensureDataReady } from "@/lib/bootstrap";
import { FeasibilityResponse, getFeasibility } from "@/lib/api";

// Step 2 of the workflow. All assignment parameters live on this one page
// (RulesPanel), with feasibility checked inline against the current data — no
// separate validation/feasibility screen.
type Feas =
  | { state: "loading" }
  | { state: "needsData" }
  | { state: "error" }
  | { state: "ok"; data: FeasibilityResponse };

export default function ConfigureStep() {
  const [feas, setFeas] = useState<Feas>({ state: "loading" });

  const check = useCallback(async () => {
    try {
      const rd = await ensureDataReady();
      if (rd.needsMapping) {
        setFeas({ state: "needsData" });
        return;
      }
      const data = await getFeasibility();
      setFeas({ state: "ok", data });
    } catch {
      setFeas({ state: "error" });
    }
  }, []);

  useEffect(() => {
    void (async () => {
      await check();
    })();
  }, [check]);

  const infeasible =
    feas.state === "ok" ? feas.data.findings.filter((f) => f["אפשרי"] === "לא") : [];

  return (
    <div className="cw flex flex-col" style={{ gap: 12 }}>
      <div className="dp-head">
        <div className="dp-title">
          <h1>הגדרות שיבוץ</h1>
        </div>
        <div className="dp-spacer" />
        <Link href="/steps/assign">
          <Button>המשך לתוצאות ←</Button>
        </Link>
      </div>

      {/* inline feasibility — is what's configured achievable with this data? */}
      {feas.state === "needsData" ? (
        <div className="cfg-feas warn">
          <Icon name="warning" size={16} />
          <div>
            יש לטעון נתונים לפני קביעת ההגדרות.{" "}
            <Link href="/steps/data">למסך העלאת הנתונים</Link>
          </div>
        </div>
      ) : feas.state === "ok" ? (
        feas.data.all_feasible ? (
          <div className="cfg-feas ok">
            <Icon name="check" size={16} />
            ההגדרות ניתנות למימוש עם {feas.data.total_students} התלמידות הנוכחיות.
          </div>
        ) : (
          <div className="cfg-feas crit">
            <Icon name="warning" size={16} />
            <div>
              <div className="ttl">לא ניתן לקיים חלק מכללי החובה עם ההגדרות הנוכחיות</div>
              <ul>
                {infeasible.map((f, i) => (
                  <li key={i}>
                    <b>{String(f["חוק"])}:</b> {String(f["הסבר"])}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )
      ) : null}

      <RulesPanel onConfigSaved={check} />
    </div>
  );
}
