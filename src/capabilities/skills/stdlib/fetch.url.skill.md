---
name: stdlib.fetch.url
description: HTTP GET fetch skill wrapping stdlib.http.fetch

primitives:
  - stdlib.http.fetch

inputs:
  url:
    type: string
    required: true
  timeout:
    type: number
    required: false
  headers:
    type: object
    required: false

outputs:
  ok: bool
  status_code: int
  body: string
  headers: object
  elapsed_ms: int
  error_type: string
  error_message: string

steps:
  - call: stdlib.http.fetch
    args:
      url: "{{ url }}"
      timeout: "{{ timeout }}"
      headers: "{{ headers }}"
    save_as: result

  - python: |
      # Passthrough — the primitive already returns the canonical schema.
      # No transformation needed.
      return result

metadata:
  tags: ["fetch", "http"]
  input_types:
    url: string
    timeout: number
    headers: object
  output_types:
    ok: bool
    status_code: int
    body: string
    headers: object
    elapsed_ms: int
    error_type: string
    error_message: string
  side_effects: ["network"]
  safety_level: "medium"
  cost_estimate:
    latency: 5
    resources: "low"
  determinism: "impure"
  prerequisites: []
---
