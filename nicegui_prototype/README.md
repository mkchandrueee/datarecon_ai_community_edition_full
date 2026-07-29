# NiceGUI Dashboard Prototype

An unwired evaluation of [NiceGUI](https://nicegui.io) as a possible
replacement for Streamlit in Community Edition, requested to see how the
Reconciliation Dashboard (Module 19) would look and behave under a
different UI framework before committing to rewriting all ~12 pages.

## What this proves

`dashboard_app.py` imports and calls the **exact same** application
services as `app.py` (Streamlit) — `DashboardService`, `ProjectService`,
and the same `SQLiteValidationRunRepository` / `SQLiteProjectRepository`
reading the same `data/datarecon_meta.db`. No domain or application code
was duplicated or modified for this prototype. That confirms the clean
architecture split (`domain/` and `application/` are framework-agnostic;
only `presentation/` is Streamlit-specific) holds up — a full migration
would only mean rewriting the view layer, not the business logic.

## Running it

This is **not** part of the main app (`app.py`) or its dependency set —
install NiceGUI separately so a normal Community Edition install stays
untouched:

```bash
pip install -e ".[nicegui-prototype]"
python nicegui_prototype/dashboard_app.py
```

Then open <http://localhost:8600>. It reads your existing
`data/datarecon_meta.db`, so run a few validations from the main
Streamlit app first if you want real data to look at — otherwise it
shows an empty state.

## What it includes

- The same 5 stat widgets, Pass Rate Trend, Runs by Module (table +
  chart), and Runtime Trend as `dashboard_view.py`.
- A **Project selector** (the feature that prompted this prototype) that
  reactively refilters every widget/chart via `DashboardService`'s
  `project_id` parameter — the same backend capability the Streamlit
  Dashboard now also uses.

## What's different from Streamlit

- No rerun-the-whole-script model: NiceGUI uses `@ui.refreshable` + an
  `on_change` handler to update just the dashboard body in place.
- Charts are ECharts specs (`ui.echart`) instead of `st.line_chart` /
  `st.bar_chart` — more verbose to build, but more customizable (axis
  formatting, tooltips, legends).
- Layout is built with explicit `ui.row()` / `ui.column()` flex
  containers instead of `st.columns()`.

## Not done here (out of scope for a one-page prototype)

- No sidebar/multi-page routing, no other 11 module pages, no auth/session
  handling per browser tab, no styling pass to match a target design.
  Those are exactly the open questions a full migration decision should
  weigh against Streamlit's simplicity and the amount of already-working
  view code it would replace.
