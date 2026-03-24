from __future__ import annotations

from pathlib import Path

from rich.console import Console

console = Console(record=True)


def save_console_log(path: str | Path) -> Path:
	target = Path(path)
	target.parent.mkdir(parents=True, exist_ok=True)
	# Save plain text log (without ANSI/style codes) for easier sharing/search.
	target.write_text(console.export_text(clear=False), encoding="utf-8")
	return target