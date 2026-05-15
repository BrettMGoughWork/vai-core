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