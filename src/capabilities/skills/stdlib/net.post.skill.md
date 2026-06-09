---
name: stdlib.net.post
description: Perform an HTTP POST request with optional JSON or form body

primitives:
  - stdlib.net.post

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
  json:
    type: object
    required: false
  data:
    type: string
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
  - call: stdlib.net.post
    args:
      url: "{{ url }}"
      timeout: "{{ timeout }}"
      headers: "{{ headers }}"
      json: "{{ json }}"
      data: "{{ data }}"

metadata:
  tags: ["network", "http", "post"]
  input_types:
    url: string
    timeout: number
    headers: object
    json: object
    data: string
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
