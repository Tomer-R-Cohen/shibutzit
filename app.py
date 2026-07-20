"""Streamlit app: assign 7th-grade students into balanced classes.

Run with: streamlit run app.py
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from src.column_mapping import (
    FIELD_CURRENT_CLASS,
    FIELD_DIFFERENTIAL,
    FIELD_ETHIOPIAN_ORIGIN,
    FIELD_FRIEND_REQUESTS,
    FIELD_HAMAR,
    FIELD_INCLUSION,
    FIELD_LABELS_HE,
    FIELD_STUDENT_ID,
    OPTIONAL_MANUAL_FIELDS,
    REQUIRED_FIELDS,
    ColumnMapping,
    apply_mapping,
    build_empty_manual_frame,
    guess_mapping,
)
from src.excel_loader import DEFAULT_WORKBOOK_PATH, ExcelLoadError, list_sheets, load_workbook
from src.export_excel import export_to_excel
from src.feasibility import analyze_feasibility
from src.friendship_graph import resolve_requests, unmatched_report
from src.manual_adjustments import AdjustmentState, ManualAdjustmentError, apply_editor_dataframe
from src.metrics import class_overview_table, compute_global_metrics, student_assignment_table, violations_report
from src.optimizer import OptimizationError, SolverConfig, optimize
from src.validation import validate_students

st.set_page_config(page_title="שיבוץ תלמידות לכיתות ז'", layout="wide")

st.markdown(
    """
    <style>
    html, body, [class*="css"] { direction: rtl; text-align: right; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title('שיבוץ תלמידות לכיתות ז – מערכת שיבוץ מאוזן')

STEPS = [
    "1. טעינת קובץ",
    "2. תצוגה מקדימה",
    "3. מיפוי עמודות",
    "4. אימות נתונים",
    "5. סה\"כ קטגוריות והיתכנות",
    "6. הגדרות ואילוצים",
    "7. נעילת תלמידות",
    "8. הרצת האופטימיזציה",
    "9. תוצאות השיבוץ",
    "10. עריכה ידנית",
    "11. ייצוא לאקסל",
]

if "step" not in st.session_state:
    st.session_state.step = STEPS[0]

with st.sidebar:
    st.header("ניווט")
    st.session_state.step = st.radio("שלב", STEPS, index=STEPS.index(st.session_state.step))

    ref_path = os.path.join("sample_data", "reference_scan.png")
    if os.path.exists(ref_path):
        with st.expander('תמונת התייחסות (סריקה.5.pdf) - לא נסרקה אוטומטית'):
            st.image(ref_path, caption="סריקה ידנית - לצפייה בלבד, לא ניתן לפרש אוטומטית")
            st.caption(
                "הקובץ המקורי הוא סריקה כתב-יד ללא טקסט הניתן לחילוץ. "
                "הוא מוצג כאן כהפניה בלבד; ניתן להזין ידנית התפלגות יעד בשלב ההגדרות."
            )

step = st.session_state.step

# ---------------------------------------------------------------- Step 1 ---
if step == STEPS[0]:
    st.subheader("טעינת קובץ אקסל")
    st.write(f"ברירת מחדל: `{DEFAULT_WORKBOOK_PATH}` (קובץ המקור לא ישתנה בשום שלב).")
    use_default = st.checkbox("להשתמש בקובץ ברירת המחדל", value=True)
    uploaded = None
    if not use_default:
        uploaded = st.file_uploader("העלאת קובץ אקסל אחר", type=["xlsx"])

    header_row = st.number_input("שורת כותרות (1-מבוסס)", min_value=1, value=4)
    first_data_row = st.number_input("שורת נתונים ראשונה", min_value=1, value=5)
    last_data_row = st.number_input("שורת נתונים אחרונה (0 = עד הסוף)", min_value=0, value=221)

    if st.button("טען קובץ"):
        try:
            path = DEFAULT_WORKBOOK_PATH
            if uploaded is not None:
                tmp_path = os.path.join("sample_data", "_uploaded_tmp.xlsx")
                with open(tmp_path, "wb") as f:
                    f.write(uploaded.getbuffer())
                path = tmp_path
            wb = load_workbook(
                path,
                header_row_1indexed=int(header_row),
                first_data_row_1indexed=int(first_data_row),
                last_data_row_1indexed=int(last_data_row) if last_data_row else None,
            )
            st.session_state.loaded_wb = wb
            st.success(f"נטען בהצלחה: {len(wb.raw_df)} שורות, גיליון '{wb.active_sheet}'.")
            for n in wb.notes:
                st.info(n)
        except ExcelLoadError as e:
            st.error(str(e))

# ---------------------------------------------------------------- Step 2 ---
elif step == STEPS[1]:
    st.subheader("תצוגה מקדימה")
    if "loaded_wb" not in st.session_state:
        st.warning("יש לטעון קובץ תחילה (שלב 1).")
    else:
        wb = st.session_state.loaded_wb
        st.write(f"גיליונות בקובץ: {wb.sheet_names}")
        st.dataframe(wb.raw_df.head(30), use_container_width=True)
        st.write(f"סה\"כ שורות שנטענו: {len(wb.raw_df)}")
        st.write(f"עמודות: {list(wb.raw_df.columns)}")

# ---------------------------------------------------------------- Step 3 ---
elif step == STEPS[2]:
    st.subheader("מיפוי עמודות")
    if "loaded_wb" not in st.session_state:
        st.warning("יש לטעון קובץ תחילה (שלב 1).")
    else:
        wb = st.session_state.loaded_wb
        columns = list(wb.raw_df.columns)
        if "col_mapping" not in st.session_state:
            st.session_state.col_mapping = guess_mapping(columns, wb.raw_df)
        cm: ColumnMapping = st.session_state.col_mapping

        st.markdown("**שדות חובה**")
        for f in REQUIRED_FIELDS:
            options = ["-- הזנה ידנית / לא קיים --"] + columns
            current = cm.get(f)
            idx = options.index(current) if current in options else 0
            choice = st.selectbox(FIELD_LABELS_HE.get(f, f), options, index=idx, key=f"map_{f}")
            if choice == options[0]:
                cm.mark_manual(f)
            else:
                cm.set(f, choice)
                cm.manual_fields.discard(f)

        st.markdown("**שדות אופציונליים (לא קיימים במקור - ניתן למפות או להזין ידנית)**")
        for f in OPTIONAL_MANUAL_FIELDS:
            options = ["-- הזנה ידנית / לא קיים --"] + columns
            current = cm.get(f)
            idx = options.index(current) if current in options else 0
            choice = st.selectbox(FIELD_LABELS_HE.get(f, f), options, index=idx, key=f"map_opt_{f}")
            if choice == options[0]:
                cm.mark_manual(f)
            else:
                cm.set(f, choice)
                cm.manual_fields.discard(f)

        problems = cm.validate()
        if problems:
            for p in problems:
                st.error(p)
        else:
            st.success("המיפוי תקין.")

        if st.button("המשך לבניית טבלת תלמידות"):
            try:
                mapped = apply_mapping(wb.raw_df, cm)
                st.session_state.mapped_df = mapped
                manual_needed = [f for f in OPTIONAL_MANUAL_FIELDS if f in cm.manual_fields]
                if "manual_entry_df" not in st.session_state:
                    st.session_state.manual_entry_df = build_empty_manual_frame(mapped[FIELD_STUDENT_ID].tolist())
                st.success(f"נבנתה טבלה עם {len(mapped)} תלמידות. שדות שדורשים הזנה ידנית: {manual_needed}")
            except Exception as e:
                st.error(str(e))

        if "manual_entry_df" in st.session_state:
            st.markdown("**הזנה/עריכה ידנית של שדות חסרים** (ניתן גם לייבא CSV/Excel משלים)")
            uploaded_manual = st.file_uploader("ייבוא טבלה משלימה (CSV/Excel, לפי מזהה תלמידה)", type=["csv", "xlsx"], key="manual_upl")
            if uploaded_manual is not None:
                try:
                    if uploaded_manual.name.endswith(".csv"):
                        imported = pd.read_csv(uploaded_manual)
                    else:
                        imported = pd.read_excel(uploaded_manual)
                    st.session_state.manual_entry_df = imported
                    st.success("טבלת ההזנה הידנית עודכנה מהקובץ שיובא.")
                except Exception as e:
                    st.error(f"שגיאה בייבוא: {e}")

            edited = st.data_editor(
                st.session_state.manual_entry_df,
                use_container_width=True,
                num_rows="fixed",
                key="manual_editor",
            )
            st.session_state.manual_entry_df = edited

            if st.button("החל שדות ידניים על טבלת התלמידות"):
                mapped = apply_mapping(wb.raw_df, cm, manual_df=st.session_state.manual_entry_df)
                st.session_state.mapped_df = mapped
                st.success("הוחלו הנתונים הידניים.")

# ---------------------------------------------------------------- Step 4 ---
elif step == STEPS[3]:
    st.subheader("אימות נתונים")
    if "mapped_df" not in st.session_state:
        st.warning("יש להשלים את מיפוי העמודות תחילה (שלב 3).")
    else:
        df = st.session_state.mapped_df
        report = validate_students(df)
        st.session_state.validation_report = report
        if report.has_errors():
            st.error(f"נמצאו {len(report.errors)} שגיאות חוסמות.")
        else:
            st.success("אין שגיאות חוסמות.")
        if report.issues:
            st.dataframe(report.to_dataframe(), use_container_width=True)
        else:
            st.info("לא נמצאו בעיות.")

        st.markdown("**זיהוי וניתוח בקשות חברות**")
        result = resolve_requests(df)
        st.session_state.friendship_result = result
        st.write(f"בקשות שהותאמו: {sum(len(v) for v in result.matched.values())}")
        st.write(f"שמות לא מותאמים: {len(result.unmatched)}, דו-משמעיים: {len(result.ambiguous)}")
        unmatched_df = unmatched_report(result)
        st.session_state.unmatched_df = unmatched_df
        if not unmatched_df.empty:
            st.dataframe(unmatched_df, use_container_width=True)

# ---------------------------------------------------------------- Step 5 ---
elif step == STEPS[4]:
    st.subheader('סה"כ קטגוריות והיתכנות')
    if "mapped_df" not in st.session_state:
        st.warning("יש להשלים שלבים קודמים תחילה.")
    else:
        df = st.session_state.mapped_df
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("סה\"כ תלמידות", len(df))
        c2.metric("מוצא אתיופי", int(df[FIELD_ETHIOPIAN_ORIGIN].sum()))
        c3.metric("דיפרנציאליות", int(df[FIELD_DIFFERENTIAL].sum()))
        c4.metric("שילוב", int(df[FIELD_INCLUSION].sum()))
        st.write(f'סה"כ ח"מ: {int(df[FIELD_HAMAR].sum())}')

        st.markdown('**התפלגות "כיתה נוכחית"**')
        st.bar_chart(df[FIELD_CURRENT_CLASS].value_counts())

        st.markdown("**טבלת יעד אופציונלית (מבוסס על הסריקה הידנית, מוזן ידנית)**")
        if "target_distribution_df" not in st.session_state:
            num_classes_guess = st.session_state.get("solver_config", SolverConfig()).num_classes
            st.session_state.target_distribution_df = pd.DataFrame(
                {"כיתה": list(range(1, num_classes_guess + 1)), "גודל יעד": [0] * num_classes_guess}
            )
        st.session_state.target_distribution_df = st.data_editor(
            st.session_state.target_distribution_df, use_container_width=True, key="target_editor"
        )

        cfg = st.session_state.get("solver_config", SolverConfig())
        report = analyze_feasibility(df, cfg)
        st.session_state.feasibility_report = report
        st.dataframe(report.to_dataframe(), use_container_width=True)
        if not report.all_feasible():
            st.warning(
                "חלק מהאילוצים הקשים אינם ישימים לפי הנתונים הקיימים. "
                "ניתן להפוך אילוצים אלה לרכים בשלב ההגדרות (שלב 6)."
            )

# ---------------------------------------------------------------- Step 6 ---
elif step == STEPS[5]:
    st.subheader("הגדרות ואילוצים")
    cfg: SolverConfig = st.session_state.get("solver_config", SolverConfig())

    cfg.num_classes = st.number_input("מספר כיתות", min_value=1, value=cfg.num_classes, key="cfg_num_classes")
    st.markdown("**גודל כיתה**")
    cfg.class_size_hard = st.checkbox("אילוץ קשה: איזון גודל כיתות", value=cfg.class_size_hard, key="cfg_class_size_hard")
    cfg.max_class_size_diff = st.number_input("פער מרבי מותר בגודל כיתה", min_value=0, value=cfg.max_class_size_diff, key="cfg_max_class_size_diff")

    st.markdown("**דיפרנציאליות**")
    cfg.differential_hard = st.checkbox("אילוץ קשה: דיפרנציאליות", value=cfg.differential_hard, key="cfg_differential_hard")
    cfg.max_differential_per_class = st.number_input("מקסימום דיפרנציאליות לכיתה", min_value=0, value=cfg.max_differential_per_class, key="cfg_max_differential_per_class")

    st.markdown("**מוצא אתיופי**")
    cfg.ethiopian_hard = st.checkbox("אילוץ קשה: מוצא אתיופי", value=cfg.ethiopian_hard, key="cfg_ethiopian_hard")
    cfg.min_ethiopian_per_class = st.number_input("מינימום מוצא אתיופי לכיתה", min_value=0, value=cfg.min_ethiopian_per_class, key="cfg_min_ethiopian_per_class")
    cfg.max_ethiopian_per_class = st.number_input("מקסימום מוצא אתיופי לכיתה", min_value=0, value=cfg.max_ethiopian_per_class, key="cfg_max_ethiopian_per_class")

    st.markdown("**שילוב**")
    cfg.inclusion_hard = st.checkbox("אילוץ קשה: שילוב", value=cfg.inclusion_hard, key="cfg_inclusion_hard")
    cfg.min_inclusion_per_class = st.number_input("מינימום שילוב לכיתה", min_value=0, value=cfg.min_inclusion_per_class, key="cfg_min_inclusion_per_class")
    cfg.max_inclusion_per_class = st.number_input("מקסימום שילוב לכיתה", min_value=0, value=cfg.max_inclusion_per_class, key="cfg_max_inclusion_per_class")

    st.markdown('**ח"מ**')
    cfg.hamar_hard = st.checkbox('אילוץ קשה: ח"מ', value=cfg.hamar_hard, key="cfg_hamar_hard")
    cfg.min_hamar_per_class = st.number_input('מינימום ח"מ לכיתה', min_value=0, value=cfg.min_hamar_per_class, key="cfg_min_hamar_per_class")
    cfg.max_hamar_per_class = st.number_input('מקסימום ח"מ לכיתה', min_value=0, value=cfg.max_hamar_per_class, key="cfg_max_hamar_per_class")

    st.markdown("**מטרות חברתיות**")
    cfg.mutual_target_pct = st.slider("יעד % חברות הדדית", 0, 100, int(cfg.mutual_target_pct), key="cfg_mutual_target_pct")
    cfg.two_friends_target_pct = st.slider("יעד % 2+ חברות מבוקשות", 0, 100, int(cfg.two_friends_target_pct), key="cfg_two_friends_target_pct")
    cfg.denominator_all_students = st.checkbox("מכנה: כלל התלמידות (אחרת - רק מי שהגישו בקשות)", value=cfg.denominator_all_students, key="cfg_denominator_all_students")

    st.markdown("**משקלים**")
    cfg.weight_mutual = st.slider("משקל חברות הדדית", 0.0, 10.0, cfg.weight_mutual, key="cfg_weight_mutual")
    cfg.weight_two_friends = st.slider("משקל 2+ חברות", 0.0, 10.0, cfg.weight_two_friends, key="cfg_weight_two_friends")
    cfg.weight_academic_balance = st.slider("משקל איזון לימודי", 0.0, 10.0, cfg.weight_academic_balance, key="cfg_weight_academic_balance")
    cfg.weight_school_balance = st.slider("משקל איזון ביה\"ס מקור", 0.0, 10.0, cfg.weight_school_balance, key="cfg_weight_school_balance")
    cfg.weight_current_class_balance = st.slider("משקל איזון כיתה נוכחית", 0.0, 10.0, cfg.weight_current_class_balance, key="cfg_weight_current_class_balance")
    cfg.weight_category_balance = st.slider("משקל איזון קטגוריות", 0.0, 10.0, cfg.weight_category_balance, key="cfg_weight_category_balance")

    st.markdown("**הגדרות פותר**")
    cfg.time_limit_seconds = st.number_input("מגבלת זמן (שניות)", min_value=1.0, value=cfg.time_limit_seconds, key="cfg_time_limit_seconds")
    cfg.random_seed = st.number_input("Random seed", min_value=0, value=cfg.random_seed, key="cfg_random_seed")

    st.session_state.solver_config = cfg
    st.success("ההגדרות נשמרו.")

# ---------------------------------------------------------------- Step 7 ---
elif step == STEPS[6]:
    st.subheader("נעילת שיבוצים ידנית (לפני הרצה)")
    if "mapped_df" not in st.session_state:
        st.warning("יש להשלים שלבים קודמים תחילה.")
    else:
        df = st.session_state.mapped_df
        cfg = st.session_state.get("solver_config", SolverConfig())
        if "pre_lock_df" not in st.session_state:
            st.session_state.pre_lock_df = pd.DataFrame(
                {
                    FIELD_STUDENT_ID: df[FIELD_STUDENT_ID],
                    "נעל לכיתה (0=לא נעול)": [0] * len(df),
                }
            )
        edited = st.data_editor(st.session_state.pre_lock_df, use_container_width=True, key="lock_editor")
        st.session_state.pre_lock_df = edited
        locked = {}
        for _, row in edited.iterrows():
            v = row["נעל לכיתה (0=לא נעול)"]
            if v and int(v) >= 1:
                locked[row[FIELD_STUDENT_ID]] = int(v) - 1
        st.session_state.locked_assignment = locked
        st.info(f"תלמידות נעולות: {len(locked)}")

# ---------------------------------------------------------------- Step 8 ---
elif step == STEPS[7]:
    st.subheader("הרצת האופטימיזציה")
    if "mapped_df" not in st.session_state:
        st.warning("יש להשלים שלבים קודמים תחילה.")
    else:
        df = st.session_state.mapped_df
        cfg = st.session_state.get("solver_config", SolverConfig())
        report = st.session_state.get("validation_report")
        if report is not None and report.has_errors():
            st.error("קיימות שגיאות אימות חוסמות (שלב 4). יש לתקן לפני ההרצה.")
        else:
            friendship_result = st.session_state.get("friendship_result")
            matched = friendship_result.matched if friendship_result else {}
            locked = st.session_state.get("locked_assignment", {})

            # INVARIANT: opt_result / adjustment_state must only ever be
            # written from this explicitly-clicked button (step 8) or the
            # explicitly-clicked re-optimize button on step 10. No other
            # code path may overwrite a computed result as a side effect of
            # navigation/reruns.
            if st.button("הרץ אופטימיזציה", key="btn_run_optimization"):
                try:
                    with st.spinner("מריץ פותר CP-SAT..."):
                        result = optimize(df, cfg, locked=locked, friendship_matched=matched)
                    st.session_state.opt_result = result
                    st.session_state.adjustment_state = AdjustmentState(
                        assignment=dict(result.assignment), locked=set(locked.keys())
                    )
                    if result.is_feasible:
                        st.success(f"נמצא פתרון. סטטוס: {result.status_name}, זמן: {result.wall_time_seconds:.2f}s")
                    else:
                        st.error(f"לא נמצא פתרון. סטטוס: {result.status_name}")
                        for n in result.infeasibility_notes:
                            st.warning(n)
                except OptimizationError as e:
                    st.error(str(e))

# ---------------------------------------------------------------- Step 9 ---
elif step == STEPS[8]:
    st.subheader("תוצאות השיבוץ")
    if "opt_result" not in st.session_state or not st.session_state.opt_result.is_feasible:
        st.warning("יש להריץ אופטימיזציה מוצלחת תחילה (שלב 8).")
    else:
        df = st.session_state.mapped_df
        cfg = st.session_state.solver_config
        friendship_result = st.session_state.get("friendship_result")
        matched = friendship_result.matched if friendship_result else {}
        state: AdjustmentState = st.session_state.adjustment_state

        tabs = st.tabs(["תצוגת כיתות", "רשימת תלמידות", "מדדים גלובליים", "חריגות", "אבחון חברויות"])
        with tabs[0]:
            st.dataframe(class_overview_table(df, state.assignment, matched, cfg), use_container_width=True)
        with tabs[1]:
            st.dataframe(student_assignment_table(df, state.assignment, matched, state.locked_assignment()), use_container_width=True)
        with tabs[2]:
            gm = compute_global_metrics(
                df, state.assignment, matched, cfg,
                st.session_state.opt_result.status_name,
                st.session_state.opt_result.wall_time_seconds,
                st.session_state.opt_result.objective_value,
            )
            st.json(gm.__dict__)
        with tabs[3]:
            st.dataframe(violations_report(df, state.assignment, cfg), use_container_width=True)
        with tabs[4]:
            unmatched_df = st.session_state.get("unmatched_df", pd.DataFrame())
            st.write("שמות לא מותאמים / דו-משמעיים:")
            st.dataframe(unmatched_df, use_container_width=True)
            no_data = [sid for sid in df[FIELD_STUDENT_ID] if sid not in matched or not matched.get(sid)]
            st.write(f"תלמידות ללא נתוני בקשות חברות: {len(no_data)}")

# --------------------------------------------------------------- Step 10 ---
elif step == STEPS[9]:
    st.subheader("עריכה ידנית של השיבוץ")
    if "adjustment_state" not in st.session_state:
        st.warning("יש להריץ אופטימיזציה תחילה (שלב 8).")
    else:
        df = st.session_state.mapped_df
        cfg = st.session_state.solver_config
        state: AdjustmentState = st.session_state.adjustment_state
        friendship_result = st.session_state.get("friendship_result")
        matched = friendship_result.matched if friendship_result else {}

        edit_df = pd.DataFrame(
            {
                FIELD_STUDENT_ID: list(state.assignment.keys()),
                "כיתה משובצת (1-מבוסס)": [state.assignment[s] + 1 for s in state.assignment.keys()],
                "נעולה": [s in state.locked for s in state.assignment.keys()],
            }
        )
        edited = st.data_editor(edit_df, use_container_width=True, key="reassign_editor")

        if st.button("החל שינויים ועדכן מדדים", key="btn_apply_manual_edits"):
            try:
                apply_editor_dataframe(state, edited, "כיתה משובצת (1-מבוסס)")
                state.locked = set(edited[edited["נעולה"] == True][FIELD_STUDENT_ID].tolist())
                st.session_state.adjustment_state = state
                st.success("השינויים הוחלו.")
            except ManualAdjustmentError as e:
                st.error(str(e))

        st.markdown("**מדדים לאחר עריכה**")
        gm = compute_global_metrics(df, state.assignment, matched, cfg)
        st.json(gm.__dict__)

        if st.button("נעל את כל השיבוצים הנוכחיים ובצע אופטימיזציה מחדש ליתר", key="btn_relock_reoptimize"):
            state.lock_all_current()
            try:
                with st.spinner("מריץ אופטימיזציה מחדש..."):
                    result = optimize(df, cfg, locked=state.locked_assignment(), friendship_matched=matched)
                st.session_state.opt_result = result
                state.assignment = dict(result.assignment)
                st.session_state.adjustment_state = state
                st.success("האופטימיזציה מחדש הושלמה.")
            except OptimizationError as e:
                st.error(str(e))

# --------------------------------------------------------------- Step 11 ---
elif step == STEPS[10]:
    st.subheader("ייצוא לאקסל")
    if "adjustment_state" not in st.session_state:
        st.warning("אין שיבוץ להצגה - יש להריץ אופטימיזציה תחילה.")
    else:
        df = st.session_state.mapped_df
        cfg = st.session_state.solver_config
        state: AdjustmentState = st.session_state.adjustment_state
        friendship_result = st.session_state.get("friendship_result")
        matched = friendship_result.matched if friendship_result else {}
        unmatched_df = st.session_state.get("unmatched_df", pd.DataFrame())
        opt_result = st.session_state.get("opt_result")
        wb = st.session_state.get("loaded_wb")

        if st.button("צור קובץ אקסל לייצוא"):
            data = export_to_excel(
                df,
                state.assignment,
                matched,
                cfg,
                unmatched_df,
                solver_status=opt_result.status_name if opt_result else "",
                solver_wall_time=opt_result.wall_time_seconds if opt_result else 0.0,
                objective_value=opt_result.objective_value if opt_result else None,
                locked=state.locked_assignment(),
                raw_source_df=wb.raw_df if wb else None,
            )
            st.download_button(
                "הורד קובץ שיבוץ.xlsx",
                data=data,
                file_name="שיבוץ_תלמידות.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
