---
name: fetch.simple
description: Perform an HTTP GET request using the simple fetch strategy

primitives:
  - stdlib.http.simple

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
  status_code:
    type: number
  body:
    type: string
  headers:
    type: object
  elapsed_ms:
    type: number

steps:
  - call: stdlib.http.simple
    args:
      url: "{{ url }}"
      timeout: "{{ timeout }}"
      headers: "{{ headers }}"

metadata:
  tags: ["fetch", "http", "simple"]
  input_types:
    url: string
    timeout: number
    headers: object
  output_types:
    status_code: number
    body: string
    headers: object
    elapsed_ms: number
  side_effects: ["network"]
  safety_level: "medium"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: []
---
