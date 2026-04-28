# Contributing to Rusty Compass

This guide covers the local development setup and how to keep your changes
green against the same checks GitHub Actions runs.

## Setup

From the repo root, set up the Python virtualenv used by everything below:

```bash
cd langchain_agent
python3.13 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install 'psycopg[binary]>=3.3.0' 'psycopg-pool>=3.3.0'
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pytest pytest-asyncio pytest-cov pytest-timeout pytest-xdist
```

## Running the CI checks locally

`make ci` runs the same two pytest invocations that
`.github/workflows/test.yml` runs in CI, using `.venv/bin/python`:

```bash
cd langchain_agent
make ci
```

If `make ci` fails locally, it will fail in CI too. Fix the failures before
pushing.

## Pre-push hook

A git pre-push hook runs `make ci` automatically before each `git push`. If
any test fails, the push is blocked.

The hook lives at `.git/hooks/pre-push` (per-clone, not tracked by git). The
canonical, tracked copy is at
`langchain_agent/scripts/git-hooks/pre-push`. After cloning the repo, install
it with:

```bash
make -C langchain_agent install-hooks
```

The hook skips itself for tag-only pushes (`git push --tags`).

## Bypassing the hook

For genuine emergencies (e.g., reverting a broken main, hotfix when CI infra
is down) you can bypass the hook with:

```bash
git push --no-verify
```

This should be rare. If `make ci` is failing, the right move is almost always
to fix the failures, not to bypass. If you find yourself reaching for
`--no-verify` regularly, the test suite or the hook needs fixing — please
file an issue rather than living with the bypass.
