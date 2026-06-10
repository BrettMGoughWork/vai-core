---
name: fetch.hardened
description: Perform an HTTP GET request using the hardened fetch strategy with retries and rotating user-agents

primitives:
  - stdlib.http.hardened

inputs:
  url:
    type: string
    required: true
  timeout:
    type: number
    required: false
    default: 30
  headers:
    type: object
    required: false
    default: {}

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
  - call: stdlib.http.hardened
    args:
      url: "{{ url }}"
      timeout: "{{ timeout }}"
      headers: "{{ headers }}"

metadata:
  tags: ["fetch", "http", "hardened"]
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
    resources: "medium"
  determinism: "impure"
  prerequisites: []
---
