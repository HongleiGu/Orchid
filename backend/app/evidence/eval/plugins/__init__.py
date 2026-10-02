"""Benchmark plugins. Importing this package registers every plugin."""
from app.evidence.eval.plugins import base  # noqa: F401
from app.evidence.eval.plugins import hallumix, ragtruth, tofueval, verigray  # noqa: F401  (register on import)
from app.evidence.eval.plugins.base import (  # noqa: F401
    EvalItem,
    PLUGINS,
    available,
    get_plugin,
    register,
)
