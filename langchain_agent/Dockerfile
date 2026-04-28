# syntax=docker/dockerfile:1.6
#
# Build context: REPO ROOT (so we can COPY both langchain_agent/ and lucille/).
# Build with:   docker build -f langchain_agent/Dockerfile .
#
# Three stages:
#   1. frontend-builder — Vite/React UI bundle
#   2. lucille-builder  — Maven build of lucille-core for the in-process Java validator
#   3. runtime          — Python app + JRE 17 + Lucille artifacts

# ---------------------------------------------------------------------------
# Stage 1: Build React frontend
# ---------------------------------------------------------------------------
FROM node:20-slim AS frontend-builder

WORKDIR /app/web

COPY langchain_agent/web/package.json langchain_agent/web/package-lock.json* ./
RUN npm ci

COPY langchain_agent/web/ ./
# Empty VITE_API_URL → production builds use relative URLs (same-domain requests).
RUN VITE_API_URL="" npm run build


# ---------------------------------------------------------------------------
# Stage 2: Build Lucille validator artifacts
# ---------------------------------------------------------------------------
# We build only lucille-core (with -am to include reactor parents). Plugins
# are not required for HOCON config validation — `Runner -validate` walks the
# pipeline graph using core classes only. Any optional plugin classes the
# validator references at runtime are caught upstream and classified as
# MISSING_PLUGIN by the parser, which is non-blocking.
FROM maven:3.9-eclipse-temurin-17 AS lucille-builder

WORKDIR /build

# Copy Lucille source. `target/` is excluded via .dockerignore so we don't
# carry stale build artifacts from the developer's host.
COPY lucille/ ./lucille/

WORKDIR /build/lucille

# `-pl lucille-core -am` builds lucille-core and only the reactor modules it
# depends on (lucille-bom, lucille-parent). Skipping tests keeps the image
# build path tight; tests run separately in the test job upstream.
RUN --mount=type=cache,target=/root/.m2/repository \
    mvn -B -ntp -DskipTests -pl lucille-core -am package


# ---------------------------------------------------------------------------
# Stage 3: Python application runtime
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# JRE for the Lucille validator subprocess; libpq5 for psycopg.
# Lucille is compiled with Java 17 (see lucille-builder stage), but Debian
# Trixie (python:3.13-slim's base) only ships openjdk-21 — Java 21 runs
# Java 17 bytecode without issue, so we use 21 here. JRE rather than JDK
# keeps the image smaller (we only run, not compile, Java at runtime).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 curl openjdk-21-jre-headless && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY langchain_agent/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application source
COPY langchain_agent/*.py ./
COPY langchain_agent/api/ ./api/
# Component catalog — 88-entry JSON used by config_builder for deterministic
# spec lookup. Without this, spec resolution falls back to the vector store
# for every component (slower, less complete metadata).
COPY langchain_agent/data/ ./data/

# Frontend bundle from stage 1
COPY --from=frontend-builder /app/web/dist ./web/dist

# Lucille validator artifacts from stage 2
COPY --from=lucille-builder /build/lucille/lucille-core/target/classes /app/lucille/lucille-core/target/classes
COPY --from=lucille-builder /build/lucille/lucille-core/target/lib /app/lucille/lucille-core/target/lib

ENV PYTHONPATH=/app
ENV LUCILLE_PROJECT_DIR=/app/lucille
ENV PORT=8080

EXPOSE ${PORT}

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
