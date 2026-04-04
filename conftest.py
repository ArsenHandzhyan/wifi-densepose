from __future__ import annotations

import asyncio
import importlib.util
import inspect
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parent
V1_ROOT = ROOT / "v1"

for candidate in (ROOT, V1_ROOT):
    text = str(candidate)
    if text not in sys.path:
        sys.path.insert(0, text)


if importlib.util.find_spec("asyncssh") is None and "asyncssh" not in sys.modules:
    asyncssh_stub = types.ModuleType("asyncssh")
    asyncssh_stub.connect = AsyncMock(name="asyncssh.connect")
    sys.modules["asyncssh"] = asyncssh_stub


def pytest_pyfunc_call(pyfuncitem):
    """Run async tests without requiring pytest-asyncio in the local venv."""
    test_func = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_func):
        return None

    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
        if name in pyfuncitem.funcargs
    }
    asyncio.run(test_func(**kwargs))
    return True
