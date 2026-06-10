---
name: stdlib.net.ping
description: Check TCP reachability of a host and port

primitives:
  - stdlib.net.ping

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
    default: 5

outputs:
  reachable:
    type: boolean
  host:
    type: string
  port:
    type: number
  elapsed_ms:
    type: number

steps:
  - call: stdlib.net.ping
    args:
      host: "{{ host }}"
      port: "{{ port }}"
      timeout: "{{ timeout }}"

metadata:
  tags: ["network", "ping", "tcp"]
  input_types:
    host: string
    port: number
    timeout: number
  output_types:
    reachable: boolean
    host: string
    port: number
    elapsed_ms: number
  side_effects: ["network"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: []
---
