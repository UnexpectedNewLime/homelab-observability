.PHONY: test test-unit test-config check-safety

# No live credentials, restarts, log injection or phone notifications.
test: test-unit test-config check-safety

test-unit:
	python3 -B -m unittest discover -s tests -p 'test_*.py' -v
	python3 -B -m unittest discover -s ntfy-bridge -p 'test_*.py' -v

test-config:
	python3 -B tests/run-config-tests.py

check-safety:
	python3 -B scripts/check-repo-safety.py
