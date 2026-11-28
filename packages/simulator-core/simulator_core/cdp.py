"""
Moved to ``simulator_core.l2.cdp``.  This alias keeps existing
``import simulator_core.cdp`` / ``from simulator_core.cdp import ...``
code working: both names refer to the same module object.
"""
import sys

from simulator_core.l2 import cdp as _module

sys.modules[__name__] = _module
