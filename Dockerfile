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
LABEL org.opencontainers.image.title="ICU Edge-to-FHIR Interoperability Gateway" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.vendor="Housam Abouelreish" \
      org.opencontainers.image.description="SaMD: HL7 v2.x → NEWS2 → FHIR R4" \
      org.opencontainers.image.licenses="Proprietary-IEC62304-ClassB" \
      samd.iec62304.class="B" \
      samd.iso14971.risk="Medium" \
      samd.regulatory.fda="CDS-Non-Device" \
      samd.regulatory.canada="Class-II"

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

# Single-worker uvicorn — appropriate for edge (single ICU node) deployment.
# Scale horizontally with Kubernetes pods, not multiple workers per container.
CMD ["python", "-m", "uvicorn", "main:app", \
     "--host",               "0.0.0.0", \
     "--port",               "8000", \
     "--workers",            "1", \
     "--no-access-log", \
     "--timeout-keep-alive", "30"]