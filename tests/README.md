# Test coverage

`make test` is safe to run on watcher or a clean checkout. It does not load the
deployment `.env`, read real passwords, stop services or publish notifications.
Requires Python 3.10+, Git, Docker and Docker Compose v2. Use `sh scripts/test.sh`
if Make is not installed. Initial execution
may download pinned validator images. Containers have no network and no writable
production mounts; only a disposable tree of synthetic configs is used.

| Layer | Checks |
| --- | --- |
| Repository | Private/generated paths ignored; templates trackable; staged blobs and current files scanned for literal addresses, tailnet DNS and common credential formats |
| Generator | All eight templates, missing/invalid input fails before writes, quote/backslash escaping, no recursive substitution, symlink refusal, token file permissions and stable bind-mount inode, YAML-typed host labels remain strings |
| ntfy provisioning | Retry after failed user/ACL creation, second-account failures, retained passwords and file modes, missing-secret refusal and preflight before mutations; mocked CLI only |
| ntfy bridge | Critical/warning/resolved priorities, mixed groups, fallback severity, UTF-8 size limit, malformed/oversized HTTP input, retryable delivery failure, health/metrics |
| Prometheus | Real generated rules: pending/firing/recovery, active guest selection, excluded service, disk duration/read-only/pseudo-FS exclusions, missing telemetry and error counters |
| Alertmanager | Native config validation; critical, warning, unknown and absent severity routing, including the parallel alert-dump receiver |
| Configs | Compose, Prometheus, Alertmanager, Loki, both Alloy templates and nginx validated with native tools |

The configuration tests use RFC 5737 addresses, reserved example domains and fake
credentials defined in `fixtures.py`. They evaluate the actual `.example` rules,
not a separately maintained copy. Pinning validator images makes rule behaviour
repeatable; update them alongside runtime upgrades.

The fallback routing test caught a missing explicit catch-all child route: because
`alert-dump` always matches, the root receiver alone does not deliver unclassified
alerts to ntfy. Keep the final warning route when editing the routing tree.

## Opt-in live acceptance tests (not CI)

Run only from watcher after confirming that log injection/phone notifications are
wanted. These scripts use ignored local credentials and the live stack.

```sh
python3 scripts/verify-alerting.py check
python3 scripts/test-phone-notifications.py
python3 scripts/test-log-patterns.py
```

- `verify-alerting.py check`: checks access controls, then sends a warning test.
- `test-phone-notifications.py`: sends a test to each topic; each expires after
  45 seconds, with recovery messages at the next Alertmanager group interval.
- `test-log-patterns.py`: inserts synthetic streams and checks OOM/backup matching.
  It is a smoke test of matcher semantics; unlike the Prometheus tests, it does not
  automatically load the active Loki rule expressions, so keep it aligned when editing them.
- `loki-acceptance.yml`: optional temporary live rule for a journal-to-phone check;
  it must not remain in `loki/rules/fake` after a test.

The live scripts are not imported by unit test discovery. Do not automate service
failure injection or production restarts as part of a routine test command. Host
reboot recovery, actual retention expiry, and locked-phone/mobile-data delivery
remain separate operational acceptance tests.

Rules use Prometheus's [native rule unit testing](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/)
and Alertmanager's [amtool route tests](https://github.com/prometheus/alertmanager#amtool).
