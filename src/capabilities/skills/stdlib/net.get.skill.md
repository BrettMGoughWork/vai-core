---
name: stdlib.net.get
description: Perform an HTTP GET request and return status, body, and headers

primitives:
  - stdlib.net.get

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
  - call: stdlib.net.get
    args:
      url: "{{ url }}"
      timeout: "{{ timeout }}"
      headers: "{{ headers }}"

metadata:
  tags: ["network", "http", "get"]
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
