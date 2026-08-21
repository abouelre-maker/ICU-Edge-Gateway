"""
GET /roots.pem — Lambda handler behind the public-facing roots-proxy ALB
(see ../main.tf). This is the ONLY public route into modules/ca's
otherwise fully internal step-ca deployment: it forwards exactly one
thing, step-ca's own well-known, unauthenticated-by-design root-cert
endpoint (GET /roots.pem), fetched over the private internal NLB
(modules/ca's step_ca_endpoint -- the SAME endpoint
modules/provisioning-api's reattest.py Lambda already fetches from to
load the CA root for client-cert verification).

No other step-ca path (ACME, admin, signing) is ever proxied. This
handler does not take a path parameter from the incoming request and does
not forward the caller's path anywhere -- it always fetches the literal
string "/roots.pem" from STEP_CA_ENDPOINT, regardless of what's in the
event. That is deliberate defense-in-depth: even if the ALB listener
rule's path/method restriction (../main.tf's aws_lb_listener_rule.
roots_pem) were ever loosened by mistake, this handler still has no code
path that could be made to reach anything other than /roots.pem.

Method check below is a second, independent enforcement of "GET only" --
the ALB listener rule already restricts this (see ../main.tf), this is
belt-and-suspenders, not the primary control.
"""

from __future__ import annotations

import os
import urllib.request

_STEP_CA_ENDPOINT = os.environ["STEP_CA_ENDPOINT"]


def _response(status_code: int, content_type: str, body: str) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"content-type": content_type},
        "body": body,
    }


def handler(event: dict, _context: object) -> dict:
    method = event.get("httpMethod")
    if method != "GET":
        return _response(405, "text/plain", "method not allowed")

    # Deliberately NOT reading event["path"] -- see module docstring.
    # step-ca's /roots.pem is public, non-secret data by step-ca's own
    # design (see modules/ca/outputs.tf's comment); no auth header is
    # added to this request, matching that.
    with urllib.request.urlopen(
        f"https://{_STEP_CA_ENDPOINT}/roots.pem", timeout=8
    ) as response:
        body = response.read().decode("utf-8")

    return _response(200, "application/x-pem-file", body)
