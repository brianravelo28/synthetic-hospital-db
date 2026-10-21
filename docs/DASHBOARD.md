# Dashboard design notes

How the dashboard in `app/` is put together and why. The implementation is in `app/utils.py`, with one file per page in `app/views/`. For what each page shows, see the table in the README.

## Data

The dashboard reads only the CSVs in `app/data/`, never a live database. That is what lets it run unchanged on Streamlit Community Cloud, which cannot reach a local database. `app/requirements.txt` lists just what the dashboard needs (`streamlit`, `pandas`, `plotly`) at exact versions, because Streamlit Cloud installs from the requirements file next to the app's entry point.

## Layout

- **KPI stat-tile cards** lead every page and sit in the same position on each one. On Admissions & Census the row is reserved above the filters (a placeholder container) and filled in once the filters are applied.
- **13px minimum font** for chart axes, legends, captions and widget labels. Long chart labels are wrapped onto at most two lines (`wrap_label()`) instead of being shrunk.
- **Every zoomable chart has a hint** under it: "drag to zoom, double-click to reset" (`plot()`).
- **Every chart has a collapsed "View as table"** with the numbers behind it, built from the figure itself so the two cannot disagree (histograms show summary statistics instead of bins). This is also the answer to the contrast warning below.

## Colour

- Colours are assigned by category identity, not by position in a chart, so filtering never repaints a surviving series. Evaluative "status" colours (payment status, discharge disposition, test-result severity) are kept separate from plain categorical identity and from ordinal severity scales (the patient-condition ramp).
- The palette slots were checked with the data-visualization skill's validator (light mode, chart surface `#fcfcfb`) for every multi-series chart, using the colours in each chart's own order. One real problem was found and fixed: the shift chart used orange and red (slots 2 and 8), only ΔE 7 apart under normal vision (the hard-fail floor is 15). It now uses slots 4, 1 and 7 (yellow, blue, violet), whose closest pair is ΔE 16.3. Every other set passes.
- Three slots (aqua, yellow, magenta) are below 3:1 contrast against the chart surface. The validator treats that as acceptable only with visible labels or a table view, so every chart has a table view.
- The ordinal patient-condition ramp passes the ordinal checks (monotone lightness, a single hue, a visible gap between steps). Run as a categorical palette it would fail, which is expected for a ramp.
- Not checked: dark mode, because the dashboard is light only.

## Known fragility

The styling relies on Streamlit's internal `data-testid` names, which could change in a Streamlit upgrade. The "13px minimum" is implemented as exactly 13px on some selectors, so it also lowers text that was larger by default; it is a consistent size, not a strict floor.
