---
name: stdlib.json.parse
description: Parse a JSON string into a structured object

primitives:
  - stdlib.echo

inputs:
  text:
    type: string
    required: true

outputs:
  result:
    type: any
  error:
    type: string

steps:
  - call: stdlib.echo
    args:
      value: "{{ text }}"
    save_as: raw

  - python: |
      import json
      try:
          parsed = json.loads(raw["value"])
          return {"result": parsed, "error": None}
      except Exception as e:
          return {"result": None, "error": str(e)}

metadata:
  tags: ["parse", "json"]
  input_types:
    text: string
  output_types:
    result: any
    error: string
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 2
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
