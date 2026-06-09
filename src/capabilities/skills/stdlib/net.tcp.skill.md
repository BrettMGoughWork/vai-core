---
name: stdlib.net.tcp
description: Check whether a TCP port on a host is open

primitives:
  - stdlib.net.tcp

inputs:
  host:
    type: string
    required: true
  port:
    type: number
    required: true
  timeout:
    type: number
    required: false

outputs:
  host:
    type: string
  port:
    type: number
  open:
    type: boolean
  elapsed_ms:
    type: number

steps:
  - call: stdlib.net.tcp
    args:
      host: "{{ host }}"
      port: "{{ port }}"
      timeout: "{{ timeout }}"

metadata:
  tags: ["network", "tcp", "port"]
  input_types:
    host: string
    port: number
    timeout: number
  output_types:
    host: string
    port: number
    open: boolean
    elapsed_ms: number
  side_effects: ["network"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: []
---
