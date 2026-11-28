"""
Moved to ``simulator_core.l2.stp``.  This alias keeps existing
``import simulator_core.stp`` / ``from simulator_core.stp import ...``
code working: both names refer to the same module object.
"""
import sys

from simulator_core.l2 import stp as _module

sys.modules[__name__] = _module
