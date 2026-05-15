from enum import Enum


class SideEffect(str, Enum):
    NONE = "none" # pure, no external effects
    READ = "read" # read‑only IO (fs/db/http)
    WRITE = "write" # mutating IO (fs/db)
    NETWORK = "network" # outbound network
    BROWSER = "browser" # headless browser actions
    SYSTEM = "system" # subprocess/shell/OS
    DANGEROUS = "dangerous" # anything that can break the box
