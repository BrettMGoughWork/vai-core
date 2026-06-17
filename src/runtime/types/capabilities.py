"""
Shared capability enums for vai-core.

These enums define the vocabulary for categorizing capabilities and their
side effects. They live in the runtime (S1) so that all strata can depend
on them without violating stratum import rules.
"""

from enum import Enum


class SkillCategory(str, Enum):
    GENERAL = "general"
    MATH = "math"
    TEXT = "text"

    IO = "io"
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    BROWSER = "browser"

    SYSTEM = "system"
    DANGEROUS = "dangerous"


class SideEffect(str, Enum):
    NONE = "none"  # pure, no external effects
    READ = "read"  # read-only IO (fs/db/http)
    WRITE = "write"  # mutating IO (fs/db)
    NETWORK = "network"  # outbound network
    BROWSER = "browser"  # headless browser actions
    SYSTEM = "system"  # subprocess/shell/OS
    DANGEROUS = "dangerous"  # anything that can break the box
