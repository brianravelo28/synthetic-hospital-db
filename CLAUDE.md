# Notes for working on this repository

- **Use current stable versions, and verify them.** Do not write a package or Python version from memory:
  check with `pip index versions <package>` (and the Actions marketplace for GitHub Actions) before pinning.
  Dependencies are pinned exactly in `requirements.txt` and `app/requirements.txt`; after a bump, run the tests
  and render every dashboard page before committing.
- **Never run the integration tests, notebook 02 or `src/run_pipeline.py` against the database behind the
  dashboard.** They regenerate every table. Use a scratch database (`HOSPITAL_DB_URL`) and pin the reference date
  with `HOSPITAL_AS_OF` so runs are reproducible.
- **The shipped data in `app/data/` is generated, not hand-edited.** Regenerate it with the pipeline, then
  re-run the tests and re-execute the notebooks.
- **Keep working notes out of the repo.** `DATA_QUIRKS.md` and `docs/WALKTHROUGH.md` are personal files and stay untracked.
