# Plugin Authoring Guide (Phase 3.14.4)

A **vai-core plugin** bundles custom primitives and skills into a single
distributable directory that is loaded at startup by the filesystem
plugin loader.

## Anatomy of a Plugin

```
plugins/
└── my-plugin/                 # plugin root (directory name does not matter)
    ├── plugin.yml             # manifest — required
    ├── primitives/            # Python files with PrimitiveBase subclasses
    │   └── my_primitive.py
    └── skills/                # .skill.md files
        └── my_skill.skill.md
```

## plugin.yml Reference

The manifest is a YAML file with the following fields:

| Field          | Required | Type   | Description                                      |
|----------------|----------|--------|--------------------------------------------------|
| `name`         | **yes**  | string | Unique identifier (e.g. `"my-plugin"`)           |
| `version`      | **yes**  | string | Semantic version (e.g. `"1.0.0"`)               |
| `description`  | **yes**  | string | Human-readable purpose of this plugin            |
| `author`       | no       | string | Attribution (optional)                           |
| `dependencies` | no       | object | `{plugin_name: version_constraint}` mapping      |
| `primitives`   | no       | list   | Python files under `primitives/` to load         |
| `skills`       | no       | list   | Skill files under `skills/` to load              |

Example:

```yaml
name: "my-plugin"
version: "1.0.0"
description: "Provides custom text transformation capabilities"
author: "Your Name"
dependencies:
  some-other-plugin: ">=1.0.0"
primitives:
  - uppercase
  - lowercase
skills:
  - echo.skill.md
  - transform.skill.md
```

## Naming Convention

Your primitives and skills should use namespaced names to avoid
collision with stdlib:

- **Primitives**: `plugin.<plugin-name>.<primitive-name>`  
  Example: `plugin.my-plugin.uppercase`

- **Skills**: `plugin.<plugin-name>.<skill-name>`  
  Example: `plugin.my-plugin.echo`

This convention is **not enforced** but is strongly recommended.

## Writing a Primitive

Create a Python file in `primitives/` with a class that extends
`PrimitiveBase`:

```python
from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType

class MyUppercasePrimitive(PrimitiveBase):
    name = "plugin.my-plugin.uppercase"
    description = "Convert text to uppercase"
    primitive_type = PrimitiveType.PYTHON

    def validate_args(self, args: dict) -> None:
        if "text" not in args:
            raise ValueError("args must contain 'text'")
        if not isinstance(args["text"], str):
            raise ValueError("'text' must be a string")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        return PrimitiveResult(
            status="success",
            data={"value": args["text"].upper()},
        )
```

The class **must**:
- End with `Primitive` in its name
- Define `name`, `description`, and `primitive_type` class attributes
- Implement `validate_args` and `execute`

## Writing a Skill

Create a `.skill.md` file in `skills/` with YAML frontmatter:

```markdown
---
name: "plugin.my-plugin.echo"
description: "Echo text through the uppercase primitive."
primitives:
  - plugin.my-plugin.uppercase
inputs:
  type: object
  properties:
    text:
      type: string
  required:
    - text
steps:
  - call: plugin.my-plugin.uppercase
    with:
      text: "{{text}}"
    as: result
  - return: "{{result}}"
---
# Echo Skill

Echoes text, transformed to uppercase.
```

The YAML frontmatter is delimited by `---` lines.  After the closing
`---` you may include markdown documentation (currently unused by the
engine).

## Loading

Plugins are loaded by placing them in the `plugins/` directory at the
project root.  The plugin loader scans this directory at startup and
registers all primitives and skills into the capability registries.

## Collision Rules

- A plugin **cannot** have the same name as a stdlib primitive or skill.
- Cross-plugin name collisions generate a warning (the first-registered
  wins).
- Plugin primitives/skills with the same name as an already-loaded
  plugin's primitive/skill will fail to load.

## Unloading and Reloading

```python
from src.capabilities.registry.plugin_loader import PluginLoader

loader = PluginLoader(prim_registry, skill_registry)
loader.load_all("plugins/")          # load everything
loader.unload_plugin("my-plugin")    # deregister
loader.reload_plugin("my-plugin")    # unload + reload
```
