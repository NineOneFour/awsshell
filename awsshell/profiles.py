import configparser
from pathlib import Path

_AWS_CONFIG = Path.home() / ".aws" / "config"

# Mutable shell state
state = {
    "profile": "default",
    "region": None,
}

DANGER_PATTERN = {"prod", "production", "live"}


def is_danger(profile: str) -> bool:
    return any(d in profile.lower() for d in DANGER_PATTERN)


def list_profiles() -> list[dict]:
    """Return all profiles from ~/.aws/config."""
    config = configparser.ConfigParser()
    config.read(_AWS_CONFIG)

    profiles = []
    for section in config.sections():
        if section == "default":
            name = "default"
        elif section.startswith("profile "):
            name = section[len("profile "):]
        else:
            continue
        region = config.get(section, "region", fallback=None)
        profiles.append({"name": name, "region": region})

    # Always include default even if absent from config
    names = [p["name"] for p in profiles]
    if "default" not in names:
        profiles.insert(0, {"name": "default", "region": None})

    return profiles


def set_profile(name: str) -> bool:
    """Switch active profile. Returns False if profile doesn't exist."""
    available = {p["name"] for p in list_profiles()}
    if name not in available:
        return False
    state["profile"] = name
    return True


def current_profile() -> str:
    return state["profile"]


def set_region(name: str | None) -> None:
    state["region"] = name


def current_region() -> str | None:
    return state["region"]
