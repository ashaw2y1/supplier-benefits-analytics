# Supplier Benefits & Procurement Reconciliation Analytics

An analytics application that compares negotiated item-level bonus and credit-note terms with purchasing receipts and recorded supplier credits, helping users inspect realized benefits, pending gaps and supplier-level performance.

## Analytical workflow

Negotiated supplier terms → purchasing receipts → expected benefits → realized benefits → pending reconciliation gaps → supplier performance.

This read-only Flask application offers an overview dashboard, monthly realized-benefit trends, type mix, supplier ranking, bonus tracking, credit-note/rebate tracking, effective-dated agreements and benefits records. Three in-memory XLSX reports retain selected filters and table search.

## Synthetic boundary

All records were generated independently as fictional scenarios. The window is 1 January 2025–31 December 2026; realized actuals stop at the fixed 23 September 2026 as-of date. Suppliers are explicitly labeled Fictional Demo Supplier. Locations, manufacturers, item and document identifiers are fictional. No login, visitor writes, uploads, original documents or external data connections exist in this runtime.

Pending values are calculated reconciliation gaps, not verified cash savings, recovered revenue or a complete financial ledger reconciliation.

## Architecture and rules

Anonymous browser → Flask read-only routes → hash-verified immutable synthetic SQLite → request-local Pandas calculations → escaped HTML and bounded in-memory XLSX.

- Expected bonus/CN = eligible paid value × negotiated fractional rate, rounded per paid line.
- Pending = expected − realized. Negative values remain signed and indicate over-target records.
- Bonus attribution uses supplier, item and one effective agreement. Dates are start-inclusive/end-exclusive. Explicit synthetic pack sizes convert BOX to EACH.
- Realized bonus uses the supplier/item/agreement weighted base-unit paid cost through the fixed as-of date. This fixed demo costing basis makes filtered/monthly totals additive; it is not a claim of accounting valuation policy. No paid cost means unvalued quantity, not an invented price.
- CN details are allocated once using receipt date, header supplier and detail item. Both purchasing and finance confirmation are required for CN and other NOI to be realized.
- Unmatched actuals remain visible with no expected target. IDs drive joins; supplier names are display labels.
- Total Benefits is realized bonus + realized CN + realized other NOI. All dashboard totals, supplier summaries and monthly series use the same event calculations.
- Targets shown separately are fictional full-window planning budgets, not contract entitlements. Search narrows table/export rows; date/supplier/item filters control KPIs.

## Local setup

Test runtime: Python 3.12.14. Use a separate environment:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
gunicorn --bind 127.0.0.1:5005 --workers 2 --timeout 30 app:app
```

Open http://127.0.0.1:5005. The included synthetic fixture is already prepared; no seeding, accounts, migrations or credentials are needed. Runtime reads it with SQLite read-only/immutable mode and verifies SHA-256. Do not modify the fixture while serving requests.

For a future WSGI host, use `gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 30 app:app` behind HTTPS. `PORT` is a process binding setting only. The app has no environment-selected data backend or configurable visitor paths. No Flask session is used and no signing secret is required. Worker sizing and actual host capacity need verification before deployment. `/health` exposes minimal status. Debug/reloader and destructive initialization are absent.

## Technical stack

Python, Flask/Jinja, Pandas, SQLite, openpyxl and Gunicorn. Pinned dependencies are listed in requirements.txt. Bootstrap styling is served locally under its included MIT license, with small local CSS/JavaScript enhancements and native SVG analytics visuals. There are no browser CDNs or external service calls.

Exports use safe-column allowlists, maximum 5,000 rows / 5 MB, and formula-prefixed text neutralization. Empty selections produce a valid header-only workbook. This candidate requires a separate release audit before public deployment.
