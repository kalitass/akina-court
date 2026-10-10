# Stored replay needing regeneration

`runs/DISP-002.json` predates the verified-notice and profile-window changes in this branch. Its recorded `no_action` verdict and policy certificate are intact, but the saved notice falsely describes a voucher transfer and account review. Its profile fact text also labels lifetime totals as 90-day counts.

The source case `data/cases/DISP-002.json` has been reimported from the organisers-shared synthetic sample with an explicit unknown history window. The stored run has **not** been edited or regenerated. The API returns HTTP 410 for this archived run, and the public site links to the sample facts instead of replaying it. A fresh in-memory run is accessible after it completes.

Before deploying the DISP-002 replay, run this case again with the configured model in an environment with the required credentials. Run `python scripts/validate_sample_run.py path/to/new-DISP-002.json`, then manually inspect the new ruling, certificate, notices, and receipt. Only then replace the stored run and remove its temporary HTTP 410 block. The 49-case benchmark has not been rerun for this change; its results remain historical.
