---
name: stdlib.net.dns
description: Resolve a hostname to IP addresses using DNS lookup

primitives:
  - stdlib.net.dns

inputs:
  hostname:
    type: string
    required: true

outputs:
  hostname:
    type: string
  addresses:
    type: array
  elapsed_ms:
    type: number

steps:
  - call: stdlib.net.dns
    args:
      hostname: "{{ hostname }}"

metadata:
  tags: ["network", "dns", "lookup"]
  input_types:
    hostname: string
  output_types:
    hostname: string
    addresses: array
    elapsed_ms: number
  side_effects: ["network"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: []
---
