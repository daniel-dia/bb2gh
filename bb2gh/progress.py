from bb2gh.console import console

_active_status = None
_active_label = ""


def _truncate_label(label: str, max_len: int = 72) -> str:
    if len(label) <= max_len:
        return label
    return label[: max_len - 1] + "…"


def _stop_active_status():
    global _active_status
    if _active_status is not None:
        _active_status.stop()
        _active_status = None


def log_copy_start(label: str):
    global _active_status, _active_label
    _active_label = _truncate_label(label)
    _stop_active_status()
    _active_status = console.status(_active_label, spinner="dots")
    _active_status.start()


def log_copy_done(label: str):
    global _active_label
    final_label = _truncate_label(label) if label else _active_label
    _stop_active_status()
    console.print(f"✅ {final_label}")
    _active_label = ""


def log_copy_fail(label: str):
    global _active_label
    final_label = _truncate_label(label) if label else _active_label
    _stop_active_status()
    console.print(f"❌ {final_label}")
    _active_label = ""
