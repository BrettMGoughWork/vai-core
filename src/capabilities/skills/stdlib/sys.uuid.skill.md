---
name: stdlib.sys.uuid
description: Generate a UUID (v4 by default, v1/v3/v5 supported)

primitives:
  - stdlib.sys.uuid

inputs:
  version:
    type: number
    required: false
    default: 4
  format:
    type: string
    required: false
    default: "standard"
  namespace:
    type: string
    required: false
    default: ""
  name:
    type: string
    required: false
    default: ""

outputs:
  uuid:
    type: string
  version:
    type: number
  format:
    type: string

steps:
  - call: stdlib.sys.uuid
    args:
      version: "{{ version }}"
      format: "{{ format }}"
      namespace: "{{ namespace }}"
      name: "{{ name }}"

metadata:
  tags: ["system", "uuid"]
  input_types:
    version: number
    format: string
    namespace: string
    name: string
  output_types:
    uuid: string
    version: number
    format: string
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: []
---
