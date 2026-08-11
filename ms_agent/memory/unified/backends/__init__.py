"""Pluggable memory backend adapters.

Import each adapter module so its ``backend_registry.register()`` call runs
at module load time.  Import errors are silenced for optional backends
so that missing dependencies don't crash the framework.
"""
from . import file_based  # noqa: F401 — always available

# Optional backends — swallow ImportError for missing packages
try:
    from . import reme_adapter  # noqa: F401
except ImportError:
    pass

try:
    from . import mem0_adapter  # noqa: F401
except ImportError:
    pass

try:
    from . import mempalace_adapter  # noqa: F401
except ImportError:
    pass

try:
    from . import byterover_adapter  # noqa: F401
except ImportError:
    pass

try:
    from . import supermemory_adapter  # noqa: F401
except ImportError:
    pass
