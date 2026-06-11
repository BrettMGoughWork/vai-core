import inspect

# deadcode_ignore — I6 false positive: helper class, not a test
class ToolSchemaGenerator:
    """
    MVP: generate JSON schemas for all registered skills.
    """

    def __init__(self, registry):
        self.registry = registry

    def generate(self):
        """
        Returns a dict:
        {
            "echo": {
                "description": "...",
                "args": {
                    "text": {"type": "string"}
                }
            },
            "add": {
                "description": "...",
                "args": {
                    "a": {"type": "number"},
                    "b": {"type": "number"}
                }
            }
        }
        """
        schema = {}

        for name, func in self.registry._skills.items():
            sig = inspect.signature(func)
            args = {}

            for param in sig.parameters.values():
                annotation = param.annotation

                if annotation == str:
                    t = "string"
                elif annotation in (int, float):
                    t = "number"
                else:
                    t = "any"

                args[param.name] = {"type": t}

            schema[name] = {
                "description": func.__doc__.strip() if func.__doc__ else "",
                "args": args
            }

        return schema