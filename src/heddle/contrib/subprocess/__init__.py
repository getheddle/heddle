"""Subprocess integration — wrap CLI tools as Heddle processing backends.

No external dependencies required (uses stdlib ``subprocess`` and ``tempfile``).

Example worker config::

    processing_backend: "heddle.contrib.subprocess.SubprocessBackend"
    backend_config:
      command: ["node", "worker.js"]
      io_mode: "json_stdio"
"""

from heddle.contrib.subprocess.backend import (
    SubprocessBackend,
    SubprocessBackendError,
    SubprocessExitError,
    SubprocessOutputParseError,
    SubprocessTimeoutError,
)

__all__ = [
    "SubprocessBackend",
    "SubprocessBackendError",
    "SubprocessExitError",
    "SubprocessOutputParseError",
    "SubprocessTimeoutError",
]
