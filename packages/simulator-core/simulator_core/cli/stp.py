"""
Spanning tree: global and per-interface settings and ``show spanning-tree``.
"""

from __future__ import annotations

from typing import Optional

from simulator_core.types import InterfaceState
from simulator_core.cli.engine import Cmd, _int_in, _match, _parse_vlan_ids, _vlan_arg


def _stp_global_vlan_tree(negate: bool) -> "Cmd":
    """``[no] spanning-tree vlan <list> ...`` in global configuration."""
    if negate:
        run = lambda s, t: s._cmd_no_stp_global_vlan(t)  # noqa: E731
    else:
        run = lambda s, t: s._cmd_stp_global_vlan(t)  # noqa: E731

    def option(word: str, help_str: str, rng: tuple[int, int], val_help: str) -> "Cmd":
        value = Cmd(f"<{rng[0]}-{rng[1]}>", val_help, arg=_int_in(*rng), handler=run)
        return Cmd(word, help_str, children=[value], handler=run if negate else None)

    diameter = Cmd("diameter", "Network diameter of this spanning tree", children=[
        Cmd("<2-7>", "Maximum number of bridges between any two end nodes",
            arg=_int_in(2, 7), handler=run)])
    root = Cmd("root", "Configure switch as root", handler=run if negate else None, children=[
        Cmd("primary", "Configure this switch as primary root for this spanning tree",
            children=[diameter], handler=run),
        Cmd("secondary", "Configure switch as secondary root",
            children=[diameter], handler=run),
    ])
    options = [
        option("forward-time", "Set the forward delay for the spanning tree", (4, 30),
               "number of seconds for the forward delay timer"),
        option("hello-time", "Set the hello interval for the spanning tree", (1, 10),
               "number of seconds between generation of config BPDUs"),
        option("max-age", "Set the max age interval for the spanning tree", (6, 40),
               "maximum number of seconds the information in a BPDU is valid"),
        option("priority", "Set the bridge priority for the spanning tree", (0, 61440),
               "bridge priority in increments of 4096"),
        root,
    ]
    return Cmd("vlan", "VLAN Switch Spanning Tree", children=[_vlan_arg(options, handler=run)])


def _stp_iface_vlan_tree() -> "Cmd":
    """``spanning-tree vlan <list> cost|port-priority <value>`` on an interface."""
    run = lambda s, t: s._cmd_stp_iface_vlan(t)  # noqa: E731
    return Cmd("vlan", "VLAN Switch Spanning Tree", children=[_vlan_arg([
        Cmd("cost", "Change an interface's per VLAN spanning tree path cost", children=[
            Cmd("<1-200000000>", "port path cost", arg=_int_in(1, 200000000), handler=run)]),
        Cmd("port-priority", "Change an interface's spanning tree port priority", children=[
            Cmd("<0-240>", "port priority in increments of 16", arg=_int_in(0, 240), handler=run)]),
    ])])


class StpCommands:
    """Spanning tree: global and per-interface settings and ``show spanning-tree``. (mixed into ``CLISession``)."""

    def _cmd_stp_portfast(self, tokens: list[str], enabled: bool) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        iface_name = self.current_iface
        if iface_name is None:
            return "% No interface selected."
        switch.stp.set_portfast(iface_name, enabled)
        return ""

    def _cmd_stp_bpduguard(self, tokens: list[str], enabled: bool) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        if self.current_iface:
            switch.stp.set_bpduguard(self.current_iface, enabled)
        return ""

    def _cmd_stp_bpdufilter(self, tokens: list[str], enabled: bool) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        if self.current_iface:
            switch.stp.set_bpdufilter(self.current_iface, enabled)
        return ""

    def _cmd_stp_guard(self, tokens: list[str], guard: str) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        if self.current_iface:
            switch.stp.set_guard(self.current_iface, guard)
        return ""

    def _cmd_stp_port_cost(self, tokens: list[str]) -> str:
        # tokens: ['spanning-tree', 'cost', '<value>']
        if len(tokens) < 3:
            return "% Incomplete command."
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        try:
            cost = int(tokens[2])
        except ValueError:
            return f"% Invalid cost: {tokens[2]!r}"
        for vlan_id in switch.vlans:
            if self.current_iface:
                switch.stp.set_port_cost(self.current_iface, vlan_id, cost)
        return ""

    def _cmd_stp_port_priority_iface(self, tokens: list[str]) -> str:
        # tokens: ['spanning-tree', 'port-priority', '<value>']
        if len(tokens) < 3:
            return "% Incomplete command."
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        try:
            priority = int(tokens[2])
        except ValueError:
            return f"% Invalid priority: {tokens[2]!r}"
        for vlan_id in switch.vlans:
            if self.current_iface:
                switch.stp.set_port_priority(self.current_iface, vlan_id, priority)
        return ""

    def _cmd_stp_iface_vlan(self, tokens: list[str]) -> str:
        """spanning-tree vlan <list> cost|port-priority <value> (interface)"""
        # tokens: ['spanning-tree', 'vlan', '<list>', 'cost|port-priority', '<val>']
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        vlans = _parse_vlan_ids(tokens[2])
        sub, value = tokens[3].lower(), int(tokens[4])
        stp = switch.stp
        try:
            with stp.deferred_changes():
                for vlan_id in vlans:
                    if "cost".startswith(sub):
                        stp.set_port_cost(self.current_iface or "", vlan_id, value)
                    else:
                        stp.set_port_priority(self.current_iface or "", vlan_id, value)
        except ValueError as exc:
            return f"% {exc}"
        return ""

    def _cmd_stp_mode(self, tokens: list[str], mode_str: str) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree mode is only available on switch devices."
        from simulator_core.l2.stp import STPMode
        mode_map = {
            "pvst": STPMode.PVST,
            "rapid-pvst": STPMode.RAPID_PVST,
            "mst": STPMode.MST,
        }
        switch.stp.mode = mode_map.get(mode_str, STPMode.RAPID_PVST)
        return ""

    _PRIORITY_ERROR = (
        "% Bridge Priority must be in increments of 4096.\n"
        "% Allowed values are: \n"
        "  0     4096  8192  12288 16384 20480 24576 28672\n"
        "  32768 36864 40960 45056 49152 53248 57344 61440"
    )

    def _cmd_stp_global_vlan(self, tokens: list[str]) -> str:
        """
        spanning-tree vlan <list>
        spanning-tree vlan <list> priority <0-61440>
        spanning-tree vlan <list> root primary|secondary [diameter <2-7>]
        spanning-tree vlan <list> hello-time|forward-time|max-age <value>

        <list> is an IOS VLAN range such as 1-100 or 1,3-5,7.
        """
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        vlans = _parse_vlan_ids(tokens[2])
        if len(tokens) == 3:
            return ""          # STP already runs on every VLAN
        stp = switch.stp
        sub = _match(tokens[3], ["priority", "root", "hello-time", "forward-time", "max-age"])[0]
        errors: list[str] = []
        with stp.deferred_changes():
            if sub == "priority":
                priority = int(tokens[4])
                if priority % 4096:
                    return self._PRIORITY_ERROR
                for vlan_id in vlans:
                    stp.store_bridge_priority(vlan_id, priority)
            elif sub == "root":
                primary = "primary".startswith(tokens[4].lower())
                for vlan_id in vlans:
                    if primary:
                        # Only VLANs with a tree can be measured against their root.
                        if stp.get_instance(vlan_id) is None and vlan_id not in switch.vlans:
                            stp.store_bridge_priority(vlan_id, 24576)
                            continue
                        try:
                            stp.set_root_primary(vlan_id)
                        except ValueError as exc:
                            errors.append(f"% {exc}")
                    else:
                        stp.store_bridge_priority(vlan_id, 28672)
            else:
                value = int(tokens[4])
                attr = {"hello-time": "hello_time", "forward-time": "forward_delay",
                        "max-age": "max_age"}[sub]
                for vlan_id in vlans:
                    inst = stp.get_instance(vlan_id)
                    if inst is not None:
                        setattr(inst.timers, attr, value)
        return "\n".join(errors)

    def _cmd_no_stp_global_vlan(self, tokens: list[str]) -> str:
        """
        no spanning-tree vlan <list> priority|root  -- back to priority 32768
        no spanning-tree vlan <list> hello-time|forward-time|max-age
        """
        # tokens: ['no', 'spanning-tree', 'vlan', '<list>', ...]
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        vlans = _parse_vlan_ids(tokens[3])
        if len(tokens) == 4:
            return "% Disabling spanning tree for a VLAN is not supported by the simulator."
        stp = switch.stp
        sub = _match(tokens[4], ["priority", "root", "hello-time", "forward-time", "max-age"])[0]
        defaults = {"hello-time": ("hello_time", 2), "forward-time": ("forward_delay", 15),
                    "max-age": ("max_age", 20)}
        with stp.deferred_changes():
            for vlan_id in vlans:
                if sub in ("priority", "root"):
                    stp.store_bridge_priority(vlan_id, 32768)
                else:
                    inst = stp.get_instance(vlan_id)
                    if inst is not None:
                        attr, value = defaults[sub]
                        setattr(inst.timers, attr, value)
        return ""

    def _cmd_stp_portfast_default(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch:
            switch.stp._portfast_default = True
        return ""

    def _cmd_stp_bpduguard_default(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch:
            # Apply bpduguard to all current portfast ports
            for inst in switch.stp.all_instances():
                for port in inst.port_states.values():
                    if port.portfast:
                        port.bpduguard = True
        return ""

    def _cmd_show_stp_vlan(self, tokens: list[str], vlan_id: Optional[int]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show spanning-tree is only available on switch devices."
        return switch.stp.show_spanning_tree(vlan_id, active_ports=self._stp_up_ports())

    def _stp_up_ports(self) -> set[str]:
        """Switch ports that are up (IOS lists only these in STP output)."""
        device = self.simulation.topology.devices[self.device_id]
        return {
            n for n, i in device.interfaces.items()
            if i.is_physical_switchport and i.oper_state == InterfaceState.UP
        }

    def _cmd_show_stp_vlan_dispatch(self, tokens: list[str]) -> str:
        """show spanning-tree vlan <list>"""
        # tokens: ['show', 'spanning-tree', 'vlan', '<list>']
        switch = self._get_switch()
        if switch is None:
            return "% show spanning-tree is only available on switch devices."
        vlans = _parse_vlan_ids(tokens[3])
        if len(vlans) == 1:
            return self._cmd_show_stp_vlan(tokens, vlans[0])
        up = self._stp_up_ports()
        shown = [switch.stp.show_spanning_tree(v, active_ports=up) for v in vlans
                 if switch.stp.get_instance(v) is not None]
        shown = [out for out in shown if not out.startswith("Spanning tree instance")]
        if not shown:
            return f"Spanning tree instance(s) for vlan {tokens[3]} does not exist."
        return "\n".join(shown)

    def _cmd_show_stp_summary(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show spanning-tree is only available on switch devices."
        return switch.stp.show_spanning_tree_brief(active_ports=self._stp_up_ports())
