# Copyright (c) ModelScope Contributors. All rights reserved.
"""Auto-register all built-in framework workspace specifications.

Importing this package triggers registration of all bundled frameworks into
:data:`ms_agent.agent_hub.FRAMEWORK_REGISTRY`.
"""
from . import hermes  # noqa: F401
from . import ms_agent  # noqa: F401
from . import nanobot  # noqa: F401
from . import openclaw  # noqa: F401
from . import openhuman  # noqa: F401
from . import qoder  # noqa: F401
from . import qwenpaw  # noqa: F401
