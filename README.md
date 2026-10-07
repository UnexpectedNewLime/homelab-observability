# Homelab observability

Prometheus, Grafana, Alertmanager, Loki/Alloy and private ntfy notifications.
The stack runs in `/opt/observability` on the monitoring host. The Proxmox host
runs native Alloy and node exporter services.

## Repository contract

- Commit source, tests, generic configuration and unfilled `.example` templates.
- Keep real addresses, private DNS names, guest IDs and credentials in local `.env`
  or generated, ignored files. `.env.example` deliberately has no defaults.
- Never commit token files, ntfy databases, Tailscale state, backups or Docker data.
- Generated configuration is not the source of truth. Edit its `.example` template.
- Loopback/unspecified addresses and RFC documentation addresses in tests are safe.
  Docker service names and generic logical labels such as `pve` are not private DNS.

`make check-safety` checks working-tree candidates and staged blobs, including files
accidentally forced into Git. Its findings contain paths/line numbers, not secret
values. It detects common secret formats and deployment addresses, but cannot prove
that arbitrary text contains no secret. Review `git diff --cached` before pushing.
Adding an ignore rule does not untrack a file or remove it from Git history.

## Configure

1. Copy `.env.example` to `.env`, restrict it with `chmod 600 .env`, and fill every
   field locally. Use an IPv4 address for each `*_IP`, a hostname (no scheme) for
   `NEXTCLOUD_URL`, an HTTPS origin for `NTFY_BASE_URL`, the actual Nextcloud journal
   path and active guest IDs.
2. Set `NTFY_CREDENTIALS_DIR` to an absolute directory on watcher. The provisioning
   and acceptance scripts default to `~/.config/homelab-alerting`; export the variable
   explicitly when invoking them if you use a different directory. They do not load `.env`.
3. Generate the ignored configs before starting any services:

   ```sh
   docker compose run --rm --no-deps config-generator
   ```

   The generator needs the repository paths writable by UID/GID 1000. The bridge
   also uses UID 1000; PVE exporter receives supplementary GID 1000 to read its
   generated 0640 token config. If deploying as another user, deliberately adjust
   these IDs and credential permissions together. Existing file inodes are retained
   so Docker bind mounts continue to see regenerated files.
4. Validate with `make test`. This uses fake inputs, not your credentials. For live
   configuration validation/reloads, see [the runbook template](LOGGING-ALERTING-RUNBOOK.md.example).
5. On a new deployment, start `docker compose up -d ntfy ntfy-tailscale`, enrol
   `ntfy-tailscale` in your tailnet, confirm its HTTPS name matches `NTFY_BASE_URL`,
   and run `python3 scripts/provision-ntfy-users.py` once. It refuses to overwrite
   existing credentials. Then start the full stack with `docker compose up -d`.
   Existing deployments skip enrolment/provisioning. The bridge deliberately refuses
   to mount a missing credential file. Never run provisioning merely to test.
6. Deploy generated `proxmox/config.alloy` and the supplied systemd files separately
   to the Proxmox host; generation alone does not change that host. Grant Alloy
   journal access, validate the configuration, and enable/reload the services.

Grafana manages user passwords in its database on `grafana-data`. Keep your login
in your password manager and change it through Grafana's account settings. There
is no Grafana password in `.env`, the container environment or a host `.secret`
file, and normal password changes do not require a container restart.

Normal startup disables initial admin creation. If the data volume is missing or
empty, Grafana will not silently recreate a default-password admin. Restore the
database or explicitly bootstrap an administrator using a temporary configuration
with `GF_SECURITY_DISABLE_INITIAL_ADMIN_CREATION=false` and a strong bootstrap
password, then remove those temporary inputs and return to the normal Compose
configuration. Do this before exposing a fresh Grafana instance. For a lost
password on an existing database, use Grafana's CLI reset command with
`--password-from-stdin`; it updates the database without requiring a saved copy.

## Grafana dashboards

The six version-controlled dashboard definitions and import instructions are in
[grafana/dashboards](grafana/dashboards/README.md). They use selectable Prometheus
and Loki datasources and discover hosts/guests from metric labels. Live exports
and restore copies remain in ignored `backups/` directories.

## Tests

```sh
make test-unit      # Python standard library and Git only
make check-safety   # No production credentials required
make test          # Also needs Docker + Compose; validators use pinned images
sh scripts/test.sh # Equivalent full suite when Make is not installed (e.g. watcher)
```

GitHub Actions runs the same checks for pushes and pull requests. See
[tests/README.md](tests/README.md) for coverage and the explicitly opt-in live tests.

The ignored `LOGGING-ALERTING-RUNBOOK.md` may contain local deployment details.
The tracked `.md.example` remains sanitised and is not automatically rendered.
Keep private deployment notes and backups on the host, not in commits.
