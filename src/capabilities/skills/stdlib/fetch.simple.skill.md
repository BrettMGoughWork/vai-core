---
name: stdlib.fetch.simple
description: Stub HTTP GET fetch skill; declares net.httpget dependency

primitives:
  - net.httpget

inputs:
  url:
    type: string
    required: true

outputs:
  status: int
  body: string
  error: string

steps:
  - call: net.httpget
    args:
      url: "{{ url }}"
    save_as: raw

  - python: |
      # Stub implementation until Phase 3.10
      # If the primitive returns a structured result, pass it through.
      # Otherwise return a deterministic placeholder.
      if isinstance(raw, dict) and "status" in raw and "body" in raw:
          return {
              "status": raw.get("status", 0),
              "body": raw.get("body", ""),
              "error": raw.get("error", None),
          }
      return {
          "status": 0,
          "body": "",
          "error": "net.httpget not implemented",
      }

metadata:
  tags: ["fetch", "http"]
  input_types:
    url: string
  output_types:
    status: int
    body: string
    error: string
  side_effects: ["network"]
  safety_level: "medium"
  cost_estimate:
    latency: 5
    resources: "low"
  determinism: "impure"
  prerequisites: []
---
