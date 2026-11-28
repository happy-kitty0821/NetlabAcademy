"""
Moved to ``simulator_core.l2.port_security``.  This alias keeps existing
``import simulator_core.port_security`` / ``from simulator_core.port_security import ...``
code working: both names refer to the same module object.
"""
import sys

from simulator_core.l2 import port_security as _module

sys.modules[__name__] = _module
