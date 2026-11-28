"""
simulator_core.cli
~~~~~~~~~~~~~~~~~~
IOS-style command-line sessions for simulated devices.

``CLISession`` (session.py) owns the modes, prompts, parsing and dispatch;
the command handlers live in one module per topic and are mixed into it:

=================  ==========================================================
engine.py          command-tree engine (``Cmd``, matching, help, errors)
trees.py           the command tree of every CLI mode
system.py          hostname, users, lines, logging, banners, saving config
interfaces.py      interface configuration and ``show interfaces``
vlan.py            VLANs, access ports, trunks, DTP
stp.py             spanning tree
switching.py       MAC address table, err-disable, port security
etherchannel.py    EtherChannel
cdp.py             CDP
routing.py         static routes, ping, ipconfig, ``show ip route`` / ARP
running_config.py  ``show running-config`` building blocks
helpers.py         interface naming and formatting helpers
=================  ==========================================================
"""

from simulator_core.cli.engine import CLIMode, Cmd
from simulator_core.cli.helpers import _long_name  # noqa: F401  (used by tests)
from simulator_core.cli.session import CLISession

__all__ = ["CLISession", "CLIMode", "Cmd"]
