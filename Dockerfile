# =============================================================================
# ICU Edge-to-FHIR Interoperability Gateway
# Multi-stage Dockerfile — Edge-Optimized, IEC 62304 Compliant
# Target: Alpine 3.19 · Non-root · Final image < 150 MB
# =============================================================================

# ─── Stage 1: Dependency Builder ─────────────────────────────────────────────
FROM python:3.11-alpine3.19 AS builder

LABEL stage="builder"

# Build-time system dependencies
# gcc/g++/gfortran: required to compile scipy if musllinux wheel is unavailable
# openblas-dev: BLAS/LAPACK backend for numpy/scipy linear algebra
# musl-dev/libffi-dev: C extensions and FFI for Python packages
#
# Phase 5 Section B (cryptography==50.0.0, requirements.txt): pyca publishes
# prebuilt musllinux_1_2 wheels for cryptography on the architectures this
# image targets, matching Alpine 3.19's musl 1.2.x -- so `pip install` below
# is expected to fetch a wheel, NOT compile from source, and no Rust
# toolchain is added here. This is a build-time assumption, not silently
# guaranteed: if a future cryptography version or a less common target
# architecture lacks a matching musllinux wheel, this RUN step will fail
# loudly at `docker build` time (pip falls back to an sdist build, which
# needs `cargo`/`rustc` not installed in this stage) rather than silently
# producing a broken image -- add `cargo`/`rustc` here if that happens.
RUN apk add --no-cache \
        gcc \
        g++ \
        gfortran \
        musl-dev \
        libffi-dev \
        openblas-dev \
        lapack-dev

WORKDIR /build

# Install all production packages to an isolated prefix directory.
# This prefix is copied to the runtime stage — no build tools follow.
COPY requirements.txt .
RUN pip install \
        --no-cache-dir \
        --no-warn-script-location \
        --prefix=/install \
        -r requirements.txt


# ─── Stage 2: Runtime Image ───────────────────────────────────────────────────
FROM python:3.11-alpine3.19 AS runtime

# OCI image annotations (IEC 62304 §8.1.2 SOUP traceability)
# NOTE: samd.* labels above are the existing regulatory label surface and
# are NOT touched by Phase 5 Section B -- the two provisioning.* labels
# below are new/additive only.
LABEL org.opencontainers.image.title="ICU Edge-to-FHIR Interoperability Gateway" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.vendor="Housam Abouelreish" \
      org.opencontainers.image.description="SaMD: HL7 v2.x → NEWS2 → FHIR R4" \
      org.opencontainers.image.licenses="Proprietary-IEC62304-ClassB" \
      samd.iec62304.class="B" \
      samd.iso14971.risk="Medium" \
      samd.regulatory.fda="CDS-Non-Device" \
      samd.regulatory.canada="Class-II" \
      icu-edge-gateway.provisioning.component="device-enrollment" \
      icu-edge-gateway.provisioning.phase="5-section-b"

# Minimal runtime system libraries
# libstdc++: required by scipy/numpy shared objects compiled with g++
# openblas: BLAS backend — shared library used by scipy at runtime
RUN apk add --no-cache \
        libstdc++ \
        openblas

# Non-root user (IEC 62304 security requirement — least-privilege principle)
# Clinical edge servers must not run application processes as root.
RUN addgroup -g 1001 -S gateway \
 && adduser  -u 1001 -S -G gateway -s /sbin/nologin -H gateway

# Copy installed Python packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source code only
# Tests, docs, regulatory/, and dev config are excluded via .dockerignore
WORKDIR /app
COPY --chown=gateway:gateway src/ ./src/

# Phase 5 Section B: entrypoint runs the enrollment handshake before
# uvicorn starts (docker/entrypoint.sh -> bootstrap_cli.py). chmod is done
# here, still as root, because USER switches below and gateway does not
# own this file otherwise.
COPY --chown=gateway:gateway docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# CERT_STORE_PATH's default (config.get_cert_store_path()) -- created here
# as an empty, correctly-owned mount POINT only. The actual persistent
# storage is expected to be a mounted volume over this path (Kubernetes
# Secret/PVC -- see deploy/k3s/edge-appliance.yaml); this directory itself
# is NOT where any private key is baked into the image, since nothing is
# written into it at build time.
RUN mkdir -p /var/lib/icu-edge-gateway/pki \
 && chown gateway:gateway /var/lib/icu-edge-gateway/pki

# Switch to non-root user before any CMD/ENTRYPOINT
USER gateway

# Runtime environment variables
ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    # Disable pip version checks — container packages are pinned
    PIP_DISABLE_PIP_VERSION_CHECK=1

EXPOSE 8000

# Kubernetes liveness / readiness probe
# 15-second start period: allows scipy/numpy to initialize on first import
HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=15s \
    --retries=3 \
    CMD python -c \
        "import urllib.request, sys; \
         r = urllib.request.urlopen('http://localhost:8000/health', timeout=5); \
         sys.exit(0 if r.status == 200 else 1)"

# Phase 5 Section B: ENTRYPOINT runs the (opt-in, no-op-unless-
# PROVISIONING_ENABLED=true) enrollment handshake, then execs the same
# uvicorn invocation this image used as its sole CMD before this change --
# so an existing deployment that never sets PROVISIONING_ENABLED sees
# identical runtime behavior, just via entrypoint.sh instead of directly.
# Single-worker uvicorn — appropriate for edge (single ICU node) deployment.
# Scale horizontally with Kubernetes pods, not multiple workers per container.
ENTRYPOINT ["/app/entrypoint.sh"]