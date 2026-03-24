from bb2gh.console import console
from rich.console import Console
from rich.text import Text

_active_status = None
_active_label = ""
_status_console = Console()


def _truncate_label(label: str, max_len: int = 72) -> str:
    if len(label) <= max_len:
        return label
    return label[: max_len - 3] + "..."


def _stop_active_status():
    global _active_status
    if _active_status is not None:
        _active_status.stop()
        _active_status = None


def log_copy_start(label: str):
    global _active_status, _active_label
    _active_label = _truncate_label(label)
    _stop_active_status()
    # Keep spinner in terminal, but avoid recording animation frames in exported logs.
    _active_status = _status_console.status(_active_label, spinner="dots")
    _active_status.start()


def log_copy_done(label: str):
    global _active_label
    final_label = _truncate_label(label) if label else _active_label
    _stop_active_status()
    line = Text()
    line.append(final_label, style="green")
    console.print(line)
    _active_label = ""


def log_copy_fail(label: str):
    global _active_label
    final_label = _truncate_label(label) if label else _active_label
    _stop_active_status()
    line = Text()
    line.append("FAILED", style="bold red")
    line.append(final_label, style="red")
    console.print(line)
    _active_label = ""
