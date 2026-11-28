"""
simulator_core.l2
~~~~~~~~~~~~~~~~~
Layer 2 protocols and switch features.

=================  =========================================================
stp.py             spanning tree (PVST+ / Rapid-PVST+)
cdp.py             Cisco Discovery Protocol
dtp.py             trunk negotiation
etherchannel.py    EtherChannel bundles (LACP, PAgP, static), load balancing
errdisable.py      err-disable, BPDU guard, errdisable recovery
native_vlan.py     native VLAN mismatch detection
port_security.py   switchport port-security state
=================  =========================================================
"""
