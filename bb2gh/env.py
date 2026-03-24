import os
import sys


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_required(name: str) -> str:
    value = env(name)
    if not value:
        print(f"ERRO: variável de ambiente {name} não definida.")
        sys.exit(1)
    return value
