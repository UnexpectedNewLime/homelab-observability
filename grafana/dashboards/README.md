# Homelab dashboards

Six editable dashboards for the existing Prometheus and Loki stack:

| File | Purpose |
| --- | --- |
| `hl-overview-v2.json` | Current health, resource trends, filesystem utilisation and navigation |
| `hl-hosts.json` | Host/service filters, CPU, memory, disk/network I/O, pressure and package updates |
| `hl-proxmox.json` | Guest states/resources, Proxmox storage and configured backup-job coverage |
| `hl-services.json` | HTTP/ICMP status, health timelines, recorded availability, latency and TLS expiry |
| `hl-storage.json` | Filesystem/dataset capacity, ZFS health, SMART status, temperatures and sectors |
| `hl-logs.json` | Journal search, monitoring pipeline health and notification delivery counters |

## Import and update

1. In Grafana, choose **Dashboards → New → Import dashboard** and upload a JSON file from this directory.
2. Select the existing Prometheus datasource and, for the logs dashboard, the existing Loki datasource when prompted. The `__inputs` definitions resolve datasource placeholders during import.
3. Import into a folder named **Homelab Operations**. Keep the supplied dashboard UID so the navigation links continue to work. When updating an existing dashboard, review the import's overwrite confirmation.
4. Repeat for the remaining files. Start with **HomeLab — Overview**.

These are importable definitions, not automatic file provisioning. Import uses the existing Grafana database and keeps the dashboards editable. Do not mount these files directly as provisioned dashboards: datasource inputs must first be resolved. See [Grafana's import instructions](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/import-dashboards/).

Use `grafana/dashboards/` as the reviewed source for future changes. Export an edited dashboard for sharing, preserve its stable UID and datasource inputs, clear instance-specific IDs/current selections, and commit the resulting JSON. Keep live API exports and restore copies in the ignored `backups/` directory.

The replaced legacy HomeLab dashboard was backed up locally before removal. Its backup is deliberately not committed. To restore it, extract the `dashboard` object from its saved API response and use Grafana's import screen.

## Data requirements and interpretation

- Prometheus jobs: `node`, `pve`, `blackbox_http`, `blackbox_icmp`, `prometheus` and `observability-self`; node metrics use the `service` label.
- Proxmox panels join guest/storage information by `id` and `instance`; guest names are discovered from exported labels.
- Storage panels require the existing ZFS and SMART metrics. Missing drive attributes remain unavailable.
- Loki panels use journal jobs matching `loki.source.journal.+` and the `host` and `level` labels. Log hosts are discovered dynamically through a Loki query variable; deployment hostnames are not embedded in the JSON.
- Missing resource telemetry is not converted to 0% usage. Some container node-exporter CPU/device counters reflect shared host resources; Proxmox guest panels provide the API's guest view.
- Recorded availability is the fraction of successful recorded probes in the selected time range. Inspect the timeline and scrape health for missing samples and exporter failures.
- Filesystem and ZFS dataset capacity is shown separately. Datasets may share free space or have quotas; their values must not be summed into physical zpool capacity.
- Backup-job coverage means inclusion in a configured Proxmox backup job, not evidence of a successful or recent backup.
- TLS expiry applies to HTTPS endpoints. Plain HTTP endpoints show neutral **No TLS data**.

## Validation

All 66 panel target queries were checked against the live Prometheus/Loki backends. All six boards were inspected in Chrome through Playwright, including individual host, guest and endpoint selections and a filtered journal search. The filesystem queries were rechecked after excluding virtual filesystems. Run the repository's `make test` or `sh scripts/test.sh` before committing changes; live exports, screenshots and query results remain outside Git.
