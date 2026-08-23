#!/usr/bin/env python3
"""
scripts/mllp_smoke_100.py — 100-message MLLP smoke test, evidence-producing.

Sends 100 real MLLP-framed HL7 v2.x ORU^R01 messages over a real TCP socket
to the gateway's MLLP listener, while holding ONE persistent WebSocket
connection to WS /api/v1/live/vitals open for the whole run — the same shape
a real dashboard client uses.

Counts, and writes as raw evidence:
  * MLLP ACKs received, and how many were MSA|AA (application accept)
  * WebSocket delta frames received
  * Bundles carrying a NEWS2 Observation
  * Drops (messages sent for which no delta arrived before the drain deadline)

This exists because the 100/100 MLLP smoke figure was previously measured but
its artifact was not retained. Output is written to
docs/demo/evidence/mllp_smoke_100.txt so the claim has a citable source.

Run against a gateway started with MLLP_ENABLED=1 on venv311.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import websockets  # noqa: E402
from demo_inject import _oru_message, _send_mllp  # noqa: E402

_MESSAGE_COUNT = 100


async def _collect(ws, seen: dict, stop: asyncio.Event) -> None:
    """Drain WS frames into `seen` until stopped."""
    try:
        while not stop.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            delta = json.loads(raw)
            pid = delta.get("patient_id")
            if pid is not None and pid not in seen:
                seen[pid] = delta
    except websockets.exceptions.ConnectionClosed:
        pass


def _has_news2_observation(bundle: dict) -> bool:
    for entry in (bundle or {}).get("entry", []) or []:
        res = entry.get("resource", {}) or {}
        if res.get("resourceType") != "Observation":
            continue
        for note in res.get("note", []) or []:
            if str(note.get("text", "")).startswith("NEWS2 score calculated"):
                return True
    return False


def _news2_note_text(bundle: dict) -> str | None:
    for entry in (bundle or {}).get("entry", []) or []:
        res = entry.get("resource", {}) or {}
        if res.get("resourceType") != "Observation":
            continue
        for note in res.get("note", []) or []:
            text = str(note.get("text", ""))
            if text.startswith("NEWS2 score calculated"):
                return text
    return None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--mllp-port", type=int, default=2575)
    ap.add_argument("--http-port", type=int, default=8000)
    ap.add_argument("--count", type=int, default=_MESSAGE_COUNT)
    ap.add_argument("--drain-s", type=float, default=15.0)
    ap.add_argument("--out", default="docs/demo/evidence/mllp_smoke_100.txt")
    args = ap.parse_args()

    ws_url = f"ws://{args.host}:{args.http_port}/api/v1/live/vitals"
    run_tag = f"SMOKE{int(time.time())}"
    lines: list[str] = []

    def emit(s: str = "") -> None:
        print(s)
        lines.append(s)

    seen: dict[str, dict] = {}
    stop = asyncio.Event()
    acks: list[tuple[str, str]] = []
    latencies: list[float] = []

    async with websockets.connect(ws_url, open_timeout=20) as ws:
        collector = asyncio.create_task(_collect(ws, seen, stop))
        await asyncio.sleep(0.5)  # let the collector attach

        t_start = time.monotonic()
        for i in range(1, args.count + 1):
            pid = f"PT-{run_tag}-{i:03d}"
            msg_id = f"{run_tag}{i:03d}"
            now = time.time()
            ts0 = time.strftime("%Y%m%d%H%M%S", time.gmtime(now))
            ts1 = time.strftime("%Y%m%d%H%M%S", time.gmtime(now + 1))
            t0 = time.monotonic()
            ack = await _send_mllp(args.host, args.mllp_port, _oru_message(pid, msg_id, ts0, ts1))
            latencies.append((time.monotonic() - t0) * 1000.0)
            acks.append((pid, ack))
        t_send_elapsed = time.monotonic() - t_start

        # Drain: wait for outstanding deltas.
        drain_deadline = time.monotonic() + args.drain_s
        while time.monotonic() < drain_deadline and len(seen) < args.count:
            await asyncio.sleep(0.25)
        stop.set()
        await collector

    sent = len(acks)
    ack_count = sum(1 for _, a in acks if a)
    aa_count = sum(1 for _, a in acks if "MSA|AA" in a)
    expected_pids = {pid for pid, _ in acks}
    matched = {p: d for p, d in seen.items() if p in expected_pids}
    frame_count = len(seen)
    bundles_with_news2 = sum(1 for d in matched.values() if _has_news2_observation(d.get("bundle") or {}))
    drops = sent - len(matched)

    note_texts = {
        _news2_note_text(d.get("bundle") or {})
        for d in matched.values()
    } - {None}

    latencies_sorted = sorted(latencies)

    def pct(p: float) -> float:
        if not latencies_sorted:
            return float("nan")
        k = max(0, min(len(latencies_sorted) - 1, int(round((p / 100.0) * len(latencies_sorted) - 1))))
        return latencies_sorted[k]

    emit("=" * 74)
    emit("MLLP 100-MESSAGE SMOKE TEST — RAW EVIDENCE")
    emit("=" * 74)
    emit(f"UTC timestamp        : {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    emit(f"Run tag              : {run_tag}")
    emit(f"Gateway MLLP         : {args.host}:{args.mllp_port}")
    emit(f"Gateway WS           : {ws_url}")
    emit(f"Interpreter          : {sys.version.split()[0]} ({sys.executable})")
    emit("")
    emit(f"Messages sent        : {sent}")
    emit(f"MLLP ACKs received   : {ack_count} / {sent}")
    emit(f"ACKs with MSA|AA     : {aa_count} / {sent}")
    emit(f"WS delta frames      : {frame_count}")
    emit(f"  matching this run  : {len(matched)} / {sent}")
    emit(f"Bundles w/ NEWS2 Obs : {bundles_with_news2} / {len(matched)}")
    emit(f"Drops (no delta)     : {drops}")
    emit("")
    emit(f"Send loop elapsed    : {t_send_elapsed:.2f}s")
    emit(f"MLLP send->ACK  p50  : {pct(50):.1f} ms")
    emit(f"MLLP send->ACK  p95  : {pct(95):.1f} ms")
    emit(f"MLLP send->ACK  max  : {max(latencies):.1f} ms" if latencies else "")
    emit("")
    emit("NEWS2 Observation.note[].text as actually emitted (distinct values):")
    for t in sorted(note_texts):
        emit(f"  {t!r}")
    emit("")
    emit("Citation check — '880.3780' present in any emitted note: "
         f"{any('880.3780' in t for t in note_texts)}")
    emit("")
    emit("-" * 74)
    emit("PER-MESSAGE ACK DETAIL (first 5 and last 5)")
    emit("-" * 74)
    for pid, ack in acks[:5] + acks[-5:]:
        emit(f"{pid}  ACK={ack.splitlines()[1] if len(ack.splitlines()) > 1 else ack!r}")
    emit("=" * 74)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[written] {out}")

    return 0 if (aa_count == sent and drops == 0 and bundles_with_news2 == len(matched)) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
