from typing import Callable, Dict, Optional
from . import builtin

class SkillRegistry:
    """
    MVP: in-process registry of pure Python skills.
    """

    def __init__(self):
        self._skills: Dict[str, Callable] = {}

    def load(self) -> None:
        """
        Register built-in skills.
        Later: dynamic discovery, plugins, etc.
        """
        self.register("echo", builtin.echo)
        self.register("add", builtin.add)

    def register(self, name: str, func: Callable) -> None:
        self._skills[name] = func

    def get(self, name: str) -> Optional[Callable]:
        return self._skills.get(name)
