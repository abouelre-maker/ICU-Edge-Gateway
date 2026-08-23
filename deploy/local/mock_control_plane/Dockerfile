# Mock control plane — local dev only, NOT the production control plane.
# See app.py's module docstring and infra/terraform/DESIGN.md.
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY generate_certs.py app.py ./

EXPOSE 8443 8080

# generate_certs.py writes /tmp/ca.{key,crt} and /tmp/server.{key,crt}
# BEFORE uvicorn (and therefore app.py's module-level _load_ca()) starts --
# see both files' docstrings for why this ordering and the shared-CA
# design matter for CA-pinning to work end-to-end against this mock.
CMD ["sh", "-c", "python generate_certs.py && exec uvicorn app:app --host 0.0.0.0 --port 8443 --ssl-certfile=/tmp/server.crt --ssl-keyfile=/tmp/server.key"]
