# Domain Inventory

The external domain surface your weekly domain-surface monitor reads. Two tables, both parsed
by `.github/scripts/domain_surface_discover.py` (apexes) and
`.github/scripts/domain_surface_probe.py` (probe hosts). Replace the `example.com` rows with
your own; keep the headings and the first column as they are — the scripts key on both.
Override the file location with `DOMAIN_INVENTORY_PATH` or `--inventory`.

## External domain surface

Apex domains you own. The first column may list several comma-separated apexes on one row
(useful for parked / redirect-only domains).

| Domain | Purpose | Zone | Notes |
| --- | --- | --- | --- |
| `example.com` | product | your DNS repo | |
| `example.org` | marketing | registrar | |
| `example-parked.com`, `example-parked.net` | parked | your DNS repo | redirect to example.com |

### Probe hosts (self-run TLS / header checks)

Customer-visible hosts the probe checks every week. One host per row; the class column is
free text for your own grouping (ingest, app, docs, status, ...). Decommissioned names stay
out — a NXDOMAIN row is noise, not a finding. Run `domain_surface_discover.py` to find live
hosts under your apexes that are missing here.

| Host | Class | Apex | Note |
| --- | --- | --- | --- |
| `example.com` | apex | example.com | |
| `www.example.com` | marketing | example.com | |
| `app.example.com` | product | example.com | |
| `api.example.com` | product API | example.com | |
| `docs.example.com` | docs | example.com | |
| `status.example.com` | status page | example.com | third-party hosted |
