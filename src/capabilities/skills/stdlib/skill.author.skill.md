---
name: stdlib.skill.author
description: >
  Author a new capability skill from raw .skill.md text content.
  The skill is parsed, validated against structural and semantic
  safety checks, sandbox-tested with mock primitives, and placed
  into quarantine for human governance approval.  Use this when
  you need to create a reusable capability at runtime.

primitives:
  - stdlib.skill.author

inputs:
  skill_text:
    type: string
    required: true
    description: Full text content of a .skill.md manifest file
  plugin_name:
    type: string
    required: false
    description: Origin label for this skill (default "agent")
  quarantine:
    type: boolean
    required: false
    description: Whether to quarantine (default true, always recommend true)

outputs:
  name:
    type: string
    description: The canonical name of the created skill
  description:
    type: string
    description: The human-readable description of the created skill
  status:
    type: string
    description: Either "quarantined" (awaiting approval) or "registered" (active)

steps:
  - call: stdlib.skill.author
    args:
      skill_text: "{{ skill_text }}"
      plugin_name: "{{ plugin_name }}"
      quarantine: true

metadata:
  tags: ["skill", "author", "create", "meta"]
  input_types:
    skill_text: string
    plugin_name: string
    quarantine: boolean
  output_types:
    name: string
    description: string
    status: string
  side_effects: ["registry_mutation", "quarantine"]
  safety_level: "high"
  cost_estimate:
    latency: 5
    resources: "medium"
  determinism: "non-deterministic"
  prerequisites: []
---
