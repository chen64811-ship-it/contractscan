# -*- coding: utf-8 -*-
"""
Parse Progress Store (in-memory, thread-safe)
Background threads write, frontend polls for updates.
"""
import threading

# {file_id: {"total": int, "done": int, "stage": str, "pct": int}}
_progress_store = {}
_store_lock = threading.Lock()


def set_progress(file_id, total, done, stage=""):
    """Set parsing progress for a file."""
    pct = int(done / total * 100) if total > 0 else 0
    with _store_lock:
        _progress_store[file_id] = {
            "total": total,
            "done": done,
            "stage": stage,
            "pct": pct
        }


def get_progress(file_id):
    """Get parsing progress for a file, returns dict or None."""
    with _store_lock:
        return dict(_progress_store.get(file_id, {})) or None


def del_progress(file_id):
    """Delete progress record for a file."""
    with _store_lock:
        _progress_store.pop(file_id, None)


def get_all_progress():
    """Get progress for all files (for batch polling)."""
    with _store_lock:
        return {fid: dict(p) for fid, p in _progress_store.items()}
