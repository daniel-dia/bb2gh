import os


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_required(name: str) -> str:
    value = env(name)
    if not value:
        raise ValueError(f"ERROR: environment variable {name} is not set.")
    return value
