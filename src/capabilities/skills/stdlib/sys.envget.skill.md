---
name: stdlib.sys.envget
description: Get the value of an environment variable, with optional default

primitives:
  - stdlib.sys.envget

inputs:
  key:
    type: string
    required: true
  default:
    type: string
    required: false

outputs:
  key:
    type: string
  value:
    type: string
  found:
    type: boolean

steps:
  - call: stdlib.sys.envget
    args:
      key: "{{ key }}"
      default: "{{ default }}"

metadata:
  tags: ["system", "environment"]
  input_types:
    key: string
    default: string
  output_types:
    key: string
    value: string
    found: boolean
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: []
---
