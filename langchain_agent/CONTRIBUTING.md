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

## Lucille (Java validator) — local clone

The Lucille project is required for: (a) the Java config validator that
runs in `lucille_validator.py`, and (b) building the production Docker
image. It's a sibling project, gitignored here because it's too large to
vendor. Clone it as a sibling at the SHA pinned in `.lucille-version`:

```bash
# from the rusty-compass repo root
git clone https://github.com/kmwtechnology/lucille.git lucille
cd lucille
git checkout "$(cat ../.lucille-version)"
mvn -DskipTests -pl lucille-core -am package
```

The validator code looks for `lucille-core/target/classes` under the path
in the `LUCILLE_PROJECT_DIR` env var (default: `../lucille` relative to
`langchain_agent/`). If those artifacts aren't present, the validator
gracefully degrades and emits a `Validation skipped` note — you'll see
this in tests as `outcome=validator_unavailable`.

To upgrade the production validator, edit `.lucille-version` with a newer
SHA from `kmwtechnology/lucille` and open a PR. The deploy workflow will
clone at that SHA and rebuild the image.

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
