# Dashboard design notes

How the dashboard in `app/` is put together and why. The implementation is in `app/utils.py`, with one file per page in `app/views/`. For what each page shows, see the table in the README.

## Data

The sidebar on every page says the data is synthetic, that the table layout follows published hospital-database designs, and that every number and proportion is chosen rather than measured; it links to `docs/CITATIONS.md`.

On a phone-width screen (375 px) the sidebar starts collapsed and no page scrolls sideways.

The dashboard reads only the CSVs in `app/data/`, never a live database. That is what lets it run unchanged on Streamlit Community Cloud, which cannot reach a local database. `app/requirements.txt` lists just what the dashboard needs (`streamlit`, `pandas`, `plotly`) at exact versions, because Streamlit Cloud installs from the requirements file next to the app's entry point.

## Layout

- **KPI stat-tile cards** lead every page and sit in the same position on each one. On Admissions & Census the row is reserved above the filters (a placeholder container) and filled in once the filters are applied.
- **13px minimum font** for chart axes, legends, captions and widget labels. Long chart labels are wrapped onto at most two lines (`wrap_label()`) instead of being shrunk.
- **Every zoomable chart has a hint** under it: "drag to zoom, double-click to reset" (`plot()`).
- **Every chart has a collapsed "View as table"** with the numbers behind it, built from the figure itself so the two cannot disagree (histograms show summary statistics instead of bins). This is also the answer to the contrast warning below.

## Colour

- Colours are assigned by category identity, not by position in a chart, so filtering never repaints a surviving series. Evaluative "status" colours (payment status, discharge disposition, test-result severity) are kept separate from plain categorical identity and from ordinal severity scales (the patient-condition ramp).
- The colours were checked with the data-visualization skill's palette validator (light mode, chart surface `#fcfcfb`), one set per chart, in the order `app/utils.py` defines them. The validator is not part of this repository; [palette_check.txt](palette_check.txt) holds its output (run 2026-11-17). The eight categorical sets (admission type, admission status, gender, payer type, bill line-item type, payment status, staff type, shift type) pass the lightness, chroma, colour-blindness and normal-vision checks. The shift chart uses slots 4, 1 and 7 (yellow, blue, violet), whose closest pair is ΔE 16.3 under normal vision (the validator's hard-fail floor is 15). Slots 4, 2 and 8 (yellow, orange, red) fail the same check: orange and red are ΔE 7.1 apart.
- Two charts colour their bars with status tokens (discharge disposition, test result). The validator checks categorical palettes, so those two sets are outside its scope and report FAIL when run as one: the yellow warning token is lighter than its band, the neutral grey is below its chroma floor, and Inconclusive and Pending share that grey. On the disposition chart the green Home and red Deceased tokens are ΔE 4.1 apart under simulated deutan colour blindness. Every bar on both charts has its category name on the axis and its count, so colour is never the only identifier.
- Three slots (aqua, yellow, magenta) are below 3:1 contrast against the chart surface. The validator treats that as acceptable only with visible labels or a table view, so every chart has a table view.
- The ordinal patient-condition ramp passes the ordinal checks (monotone lightness, a single hue, a visible gap between steps). Run as a categorical palette it would fail, which is expected for a ramp.
- Not checked: dark mode, because the dashboard is light only.

## Known fragility

The styling relies on Streamlit's internal `data-testid` names, which could change in a Streamlit upgrade. The "13px minimum" is implemented as exactly 13px on some selectors, so it also lowers text that was larger by default; it is a consistent size, not a strict floor.
