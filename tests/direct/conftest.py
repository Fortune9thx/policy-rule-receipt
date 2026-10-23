"""Direct-mode test configuration.

The gltest package registers its direct-mode fixtures through the
``gltest_direct`` pytest entry point, so no plugin declaration is needed here.
This conftest makes the project root importable and patches a Windows-only
gltest issue: the direct loader unlinks the stdin snapshot while fd 0 still
references it, which Windows forbids. The snapshot is already installed on
fd 0, so failing to unlink it is harmless for the test process.
"""

from pathlib import Path
import os
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


if sys.platform == "win32":
    from gltest.direct import loader as _direct_loader

    _original_inject = _direct_loader._inject_message_to_fd0
    _real_unlink = os.unlink

    def _tolerant_unlink(path, *args, **kwargs):
        try:
            _real_unlink(path, *args, **kwargs)
        except PermissionError:
            pass

    def _inject_message_without_unlink_failure(vm):
        os.unlink = _tolerant_unlink
        try:
            return _original_inject(vm)
        finally:
            os.unlink = _real_unlink

    _direct_loader._inject_message_to_fd0 = _inject_message_without_unlink_failure
