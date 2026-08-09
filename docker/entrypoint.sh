#!/bin/sh
# ICU Edge Gateway — container entrypoint.
#
# Phase 5 Section B: runs the device-identity enrollment handshake BEFORE
# uvicorn starts. bootstrap_cli.py is itself a no-op (exit 0 immediately)
# when PROVISIONING_ENABLED is unset/false, so this script's behavior for
# every existing (pre-Section-B) deployment is unchanged -- it just adds
# one fast, always-false check before falling through to the same uvicorn
# command that used to be this image's only CMD.
#
# set -e: if enrollment is enabled and fails, this script exits non-zero
# and uvicorn never starts -- an edge appliance that required enrollment
# and didn't get it must not silently come up and serve traffic anyway.
set -e

python -m infrastructure.provisioning.bootstrap_cli

exec python -m uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --no-access-log \
    --timeout-keep-alive 30
