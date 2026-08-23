"""
Multi-Vendor HL7 v2.x Monitor Simulator — Local Development Only.

Sends MLLP-framed ORU^R01 messages to the gateway's MLLP listener
(infrastructure/streaming/mllp_listener.py), cycling through several
MSH-3 (Sending Application) values -- including one deliberately NOT in
hl7v2_adapter.py's _VENDOR_SUBSTRINGS table, to exercise the GENERIC
vendor fallback path (ISO 14971 HAZARD-PROTO-001) end-to-end against a
real MLLP socket, not just the adapter's own unit tests.

Standalone stdlib script (asyncio + socket only) -- no dependencies to
install, matching the mock control plane's "local dev only, keep it
simple" scope.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import time

_START_BLOCK = b"\x0b"
_END_BLOCK = b"\x1c"
_CARRIAGE_RETURN = b"\x0d"

_GATEWAY_HOST = os.getenv("GATEWAY_MLLP_HOST", "gateway")
_GATEWAY_PORT = int(os.getenv("GATEWAY_MLLP_PORT", "2575"))
_INTERVAL_SECONDS = float(os.getenv("SIMULATOR_INTERVAL_SECONDS", "5"))


def _oru_message(sending_application: str, patient_id: str, msg_id: str) -> str:
    """
    A minimal but complete ORU^R01 -- same segment shape as the fixture
    used throughout tests/integration/test_mllp_listener.py and
    test_api_ingest.py (FULL_ORU), just parameterized by vendor/patient.
    """
    ts = time.strftime("%Y%m%d%H%M%S")
    return (
        f"MSH|^~\\&|{sending_application}|ICU_UNIT|EHR|HOSPITAL|{ts}"
        f"||ORU^R01|{msg_id}|P|2.5.1\r"
        f"PID|1||{patient_id}^^^HOSP^MR||SIMULATED^PATIENT||19800101|M\r"
        f"OBR|1||ORDER-{msg_id}|||||{ts}\r"
        f"OBX|1|NM|8867-4^Heart rate^LN||{72 + (hash(msg_id) % 20)}|/min|60-100||||F|||{ts}\r"
        f"OBX|2|NM|59408-5^SpO2^LN||{95 + (hash(msg_id) % 5)}|%|95-100||||F|||{ts}\r"
        f"OBX|3|NM|9279-1^Respiratory rate^LN||16|/min|12-20||||F|||{ts}\r"
        f"OBX|4|NM|8480-6^Systolic BP^LN||120|mmHg|90-140||||F|||{ts}\r"
        f"OBX|5|NM|8310-5^Temperature^LN||37.0|Cel|36.1-38.0||||F|||{ts}\r"
        f"OBX|6|NM|57834-7^Supplemental O2^LN||0||||||F|||{ts}\r"
    )


# (sending_application, patient_id) pairs. "ACME_MULTIPARAM" is
# deliberately absent from hl7v2_adapter.py's _VENDOR_SUBSTRINGS table --
# it exercises MonitorVendor.GENERIC's LOINC-fallback path specifically,
# per this section's requirement.
_MONITOR_PROFILES = [
    ("PHILIPS_INTELLIVUE", "PT-SIM-PHILIPS-001"),
    ("GE_CARESCAPE", "PT-SIM-GE-001"),
    ("DRAEGER_INFINITY", "PT-SIM-DRAEGER-001"),
    ("MINDRAY_BENEVIEW", "PT-SIM-MINDRAY-001"),
    ("ACME_MULTIPARAM_MONITOR", "PT-SIM-GENERIC-001"),  # unrecognized -> GENERIC
]


async def _send_one(sending_application: str, patient_id: str, msg_id: str) -> None:
    message = _oru_message(sending_application, patient_id, msg_id)
    frame = _START_BLOCK + message.encode("utf-8") + _END_BLOCK + _CARRIAGE_RETURN

    reader, writer = await asyncio.open_connection(_GATEWAY_HOST, _GATEWAY_PORT)
    try:
        writer.write(frame)
        await writer.drain()
        ack_frame = await reader.readuntil(_END_BLOCK + _CARRIAGE_RETURN)
        print(
            f"[simulator] {sending_application} msg={msg_id} -> "
            f"{ack_frame.strip(_START_BLOCK + _END_BLOCK + _CARRIAGE_RETURN)[:40]!r}"
        )
    finally:
        writer.close()
        await writer.wait_closed()


async def main() -> None:
    print(
        f"[simulator] targeting {_GATEWAY_HOST}:{_GATEWAY_PORT}, "
        f"cycling {len(_MONITOR_PROFILES)} vendor profiles every "
        f"{_INTERVAL_SECONDS}s (GENERIC-fallback profile included)"
    )
    counter = itertools.count(1)
    while True:
        for sending_application, patient_id in _MONITOR_PROFILES:
            msg_id = f"SIM{next(counter):06d}"
            try:
                await _send_one(sending_application, patient_id, msg_id)
            except OSError as exc:
                # Gateway not up yet (compose startup ordering) -- retry
                # on the next cycle rather than crashing the container.
                print(f"[simulator] connection failed, will retry: {exc}")
            await asyncio.sleep(_INTERVAL_SECONDS / len(_MONITOR_PROFILES))


if __name__ == "__main__":
    asyncio.run(main())
