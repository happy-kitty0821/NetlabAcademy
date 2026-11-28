"""
Moved to ``simulator_core.l3.routing``.  This alias keeps existing
``import simulator_core.routing`` / ``from simulator_core.routing import ...``
code working: both names refer to the same module object.
"""
import sys

from simulator_core.l3 import routing as _module

sys.modules[__name__] = _module
