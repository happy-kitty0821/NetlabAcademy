"""
CDP configuration and ``show cdp``.
"""

from __future__ import annotations



class CdpCommands:
    """CDP configuration and ``show cdp``. (mixed into ``CLISession``)."""

    def _get_cdp_manager(self):
        """Return the CDPManager for this session's device, or None."""
        sim = self.simulation
        try:
            return sim.get_switch(self.device_id).cdp_manager
        except KeyError:
            pass
        try:
            return sim.get_router(self.device_id).cdp_manager
        except KeyError:
            pass
        try:
            return sim.get_host(self.device_id).cdp_manager
        except KeyError:
            pass
        return None

    def _cmd_show_cdp(self, tokens: list[str]) -> str:
        """show cdp — global CDP status."""
        mgr = self._get_cdp_manager()
        if mgr is None:
            return "% CDP is not available on this device."
        status = "enabled" if mgr.is_enabled else "disabled"
        return (
            f"Global CDP information:\n"
            f"        Sending CDP packets every {mgr.hello_interval} seconds\n"
            f"        Sending a holdtime value of {mgr.holdtime} seconds\n"
            f"        Sending CDPv2 advertisements is enabled\n"
            f"        CDP is {status}"
        )

    def _cmd_show_cdp_neighbors(self, tokens: list[str]) -> str:
        """show cdp neighbors — Cisco-style brief neighbor table."""
        mgr = self._get_cdp_manager()
        if mgr is None:
            return "% CDP is not available on this device."
        if not mgr.is_enabled:
            return "% CDP is disabled."
        neighbors = mgr.get_neighbors()
        lines = [
            "Capability Codes: R - Router, T - Trans Bridge, B - Source Route Bridge",
            "                  S - Switch, H - Host, I - IGMP, r - Repeater, P - Phone",
            "",
            f"{'Device ID':<16} {'Local Intrfce':<17} {'Holdtme':<10} {'Capability':<11} {'Platform':<18} {'Port ID'}",
        ]
        if not neighbors:
            lines.append("")
            lines.append("Total cdp entries displayed : 0")
            return "\n".join(lines)
        for local_iface, entry in sorted(neighbors):
            # Capability abbreviation
            cap_abbr = {"Switch": "S", "Router": "R", "Host": "H"}.get(entry.capabilities, "?")
            lines.append(
                f"{entry.device_id:<16} {local_iface:<17} {entry.holdtime:<10} {cap_abbr:<11} {entry.platform:<18} {entry.local_interface}"
            )
        lines.append("")
        lines.append(f"Total cdp entries displayed : {len(neighbors)}")
        return "\n".join(lines)

    def _cmd_show_cdp_neighbors_detail(self, tokens: list[str]) -> str:
        """show cdp neighbors detail — full CDP neighbor information."""
        mgr = self._get_cdp_manager()
        if mgr is None:
            return "% CDP is not available on this device."
        if not mgr.is_enabled:
            return "% CDP is disabled."
        neighbors = mgr.get_neighbors()
        if not neighbors:
            return "% No CDP neighbor entries found."
        blocks = []
        for local_iface, entry in sorted(neighbors):
            ip_str = ", ".join(entry.ip_addresses) if entry.ip_addresses else "(none)"
            block = (
                f"-------------------------\n"
                f"Device ID: {entry.device_id}\n"
                f"Entry address(es):\n"
                f"  IP address: {ip_str}\n"
                f"Platform: {entry.platform},  Capabilities: {entry.capabilities}\n"
                f"Interface: {local_iface},  Port ID (outgoing port): {entry.local_interface}\n"
                f"Holdtime : {entry.holdtime} sec\n"
                f"\n"
                f"Version :\n"
                f"{entry.software_version}\n"
                f"\n"
                f"advertisement version: {entry.advertisement_version}\n"
                f"Duplex: {entry.duplex}\n"
                f"Native VLAN: {entry.native_vlan}\n"
                f"VTP Management Domain: '{entry.vtp_domain}'"
            )
            blocks.append(block)
        return "\n".join(blocks)

    def _cmd_show_cdp_interface(self, tokens: list[str]) -> str:
        """show cdp interface — per-interface CDP status."""
        mgr = self._get_cdp_manager()
        if mgr is None:
            return "% CDP is not available on this device."
        device = self.simulation.topology.devices.get(self.device_id)
        if device is None:
            return "% Device not found."
        lines = []
        for iface_name, iface in device.interfaces.items():
            if iface.is_svi or iface.is_loopback:
                continue
            cdp_iface_enabled = getattr(iface, "_cdp_enabled", True)
            status = "Sending and receiving CDP packets." if (mgr.is_enabled and cdp_iface_enabled) else "CDP disabled on this interface."
            lines.append(f"{iface_name} is up, line protocol is up")
            lines.append(f"  Encapsulation ARPA")
            lines.append(f"  Sending CDP packets every {mgr.hello_interval} seconds")
            lines.append(f"  Holdtime is {mgr.holdtime} seconds")
            lines.append(f"  {status}")
            lines.append("")
        if not lines:
            return "% No physical interfaces found."
        return "\n".join(lines)

    def _cmd_cdp_run(self, tokens: list[str], enabled: bool) -> str:
        """cdp run / no cdp run — enable/disable CDP globally."""
        mgr = self._get_cdp_manager()
        if mgr is None:
            return "% CDP is not available on this device."
        mgr.is_enabled = enabled
        return ""

    def _cmd_cdp_timer(self, tokens: list[str]) -> str:
        """cdp timer <seconds> — set CDP hello interval."""
        # tokens: ['cdp', 'timer', '<seconds>']
        if len(tokens) < 3:
            return "% Incomplete command.\nUsage: cdp timer <seconds>"
        try:
            val = int(tokens[2])
            if not (5 <= val <= 900):
                return "% CDP timer must be between 5 and 900 seconds."
        except ValueError:
            return f"% Invalid value: {tokens[2]!r}"
        mgr = self._get_cdp_manager()
        if mgr is None:
            return "% CDP is not available on this device."
        mgr.hello_interval = val
        return ""

    def _cmd_cdp_holdtime(self, tokens: list[str]) -> str:
        """cdp holdtime <seconds> — set CDP holdtime."""
        # tokens: ['cdp', 'holdtime', '<seconds>']
        if len(tokens) < 3:
            return "% Incomplete command.\nUsage: cdp holdtime <seconds>"
        try:
            val = int(tokens[2])
            if not (10 <= val <= 255):
                return "% CDP holdtime must be between 10 and 255 seconds."
        except ValueError:
            return f"% Invalid value: {tokens[2]!r}"
        mgr = self._get_cdp_manager()
        if mgr is None:
            return "% CDP is not available on this device."
        mgr.holdtime = val
        return ""

    def _cmd_cdp_iface_enable(self, tokens: list[str], enabled: bool) -> str:
        """cdp enable / no cdp enable — enable/disable CDP on the current interface."""
        iface = self._get_current_iface()
        if iface is None:
            return "% No interface selected."
        iface._cdp_enabled = enabled  # type: ignore[attr-defined]
        return ""
