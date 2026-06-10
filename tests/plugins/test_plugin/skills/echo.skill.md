---
name: "plugin.test-plugin.echo"
description: "Echo text through the uppercase primitive, returning upper-cased output."
primitives:
  - plugin.test-plugin.uppercase
inputs:
  type: object
  properties:
    text:
      type: string
  required:
    - text
steps:
  - call: plugin.test-plugin.uppercase
    with:
      text: "{{text}}"
    as: result
  - return: "{{result}}"
---
# Echo Skill

An echo skill that transforms text to uppercase using the test plugin's
uppercase primitive.
