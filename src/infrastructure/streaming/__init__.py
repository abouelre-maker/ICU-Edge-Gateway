"""
infrastructure.streaming — Phase 5 Section A: Real-Time Streaming Layer.

Net-new transports that sit in front of the existing, already-tested domain
pipeline (HL7v2Adapter -> VitalsOrchestrator -> BundleAssembler). Nothing in
this package changes DSP, NEWS2, or FHIR assembly behavior.
"""

from __future__ import annotations
