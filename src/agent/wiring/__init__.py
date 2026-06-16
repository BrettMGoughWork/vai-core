"""
Stratum 5 — Composition Wiring
===============================

S5 is the sole composition root for the application.  This package
provides adapters and factories that wire stratum protocols
into concrete instances.

All stratum-to-stratum wiring lives here so that no stratum
imports another stratum's implementation details at runtime
— only protocol interfaces cross stratum boundaries.
"""
