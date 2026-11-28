"""
IP routing and reachability: static routes, default gateway,
``ping``, PC ``ipconfig``, ``show ip route`` and ``show arp``.
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network
from typing import Optional

from simulator_core.types import InterfaceState
from simulator_core.cli.engine import _invalid_at
from simulator_core.cli.helpers import (
    _cisco_mac,
    _is_valid_host_address,
    _join_iface_tokens,
    _long_name,
    _mask_prefix,
    _match_iface,
)


class RoutingCommands:
    """IP routing and reachability: static routes, default gateway, (mixed into ``CLISession``)."""

    def _cmd_ipconfig(self, tokens: list[str]) -> str:
        """
        ipconfig                              -- show the PC's address
        ipconfig <ip> <mask>|/<len> [<gw>]    -- set it (Packet Tracer syntax)
        """
        device = self.simulation.topology.devices[self.device_id]
        iface = next((i for i in device.interfaces.values()
                      if not (i.is_loopback or i.is_svi or i.is_subinterface)), None)
        if iface is None:
            return "% This device has no network interface."
        if len(tokens) == 1:
            cfg = iface.ip_config
            addr = str(cfg.address) if cfg else "0.0.0.0"
            mask = str(IPv4Network(f"0.0.0.0/{cfg.prefix_length}").netmask) if cfg else "0.0.0.0"
            return "\n".join([
                "",
                f"{iface.name} Connection:(default port)",
                "",
                f"   IPv4 Address....................: {addr}",
                f"   Subnet Mask.....................: {mask}",
                f"   Default Gateway.................: {iface.default_gateway or '0.0.0.0'}",
                "",
            ])
        args = tokens[1:]
        ip_str, sep, plen = args[0].partition("/")
        try:
            ip = IPv4Address(ip_str)
        except ValueError:
            return _invalid_at(" ".join(tokens[:2]), tokens[1])
        if sep:
            if not plen.isdigit() or not 0 < int(plen) <= 32:
                return _invalid_at(" ".join(tokens[:2]), tokens[1])
            prefix, rest = int(plen), args[1:]
        else:
            if len(args) < 2:
                return "% Incomplete command.\nUsage: ipconfig <ip-address> <subnet-mask> [<default-gateway>]"
            try:
                prefix = _mask_prefix(int(IPv4Address(args[1])))
            except ValueError:
                return _invalid_at(" ".join(tokens[:3]), tokens[2])
            if prefix is None:
                return f"% Bad mask {args[1]} for address {ip}"
            rest = args[2:]
        if not _is_valid_host_address(ip):
            return f"Not a valid host address - {ip}"
        gateway = None
        if rest:
            try:
                gateway = str(IPv4Address(rest[0]))
            except ValueError:
                return _invalid_at(" ".join(tokens), rest[0])
        iface.set_ip(f"{ip}/{prefix}")
        if gateway:
            iface.set_gateway(gateway)
        self._refresh_l3()
        return ""

    def _parse_network_and_mask(self, net_str: str, mask_str: str):
        """
        Parse a network + dotted-mask pair, return IPv4Network or None.
        The mask must be contiguous and the network must have no host bits
        set (IOS: "%Inconsistent address and mask").
        """
        from ipaddress import IPv4Address, IPv4Network
        try:
            prefix = _mask_prefix(int(IPv4Address(mask_str)))
            if prefix is None:
                return None
            return IPv4Network(f"{net_str}/{prefix}", strict=True)
        except Exception:
            return None

    def _cmd_ip_route(self, tokens: list[str]) -> str:
        # ip route <network> <mask> {<next-hop> | <interface> [<next-hop>]}
        if len(tokens) < 5:
            return "% Incomplete command.\nUsage: ip route <network> <mask> {<next-hop> | <interface> [<next-hop>]}"
        tokens = _join_iface_tokens(tokens, 4)
        net_str, mask_str = tokens[2], tokens[3]
        network = self._parse_network_and_mask(net_str, mask_str)
        if network is None:
            return "%Inconsistent address and mask"
        router = self._get_router()
        if router is None:
            return "% ip route is only available on router devices."
        from ipaddress import IPv4Address
        next_hop = None
        exit_iface = None
        try:
            next_hop = IPv4Address(tokens[4])
        except ValueError:
            device = self.simulation.topology.devices[self.device_id]
            found = _match_iface(tokens[4], list(device.interfaces))
            if len(found) != 1:
                return _invalid_at(" ".join(tokens[:5]), tokens[4])
            exit_iface = found[0]
            if len(tokens) > 5:
                try:
                    next_hop = IPv4Address(tokens[5])
                except ValueError:
                    return _invalid_at(" ".join(tokens[:6]), tokens[5])
        # Outgoing interfaces are resolved from the connected routes.  As on
        # IOS, a static route that cannot be resolved yet is kept in the
        # configuration but not installed until it can be.
        router.routing_table.add_static_route(network, next_hop, "", exit_interface=exit_iface)
        router.routing_table.resolve_static_routes()
        return ""

    def _cmd_no_ip_route(self, tokens: list[str]) -> str:
        # tokens: ['no', 'ip', 'route', '<network>', '<mask>']
        if len(tokens) < 5:
            return "% Incomplete command.\nUsage: no ip route <network> <mask> <next-hop>"
        net_str, mask_str = tokens[3], tokens[4]
        network = self._parse_network_and_mask(net_str, mask_str)
        if network is None:
            return f"% Invalid network or mask: {net_str} {mask_str}"
        router = self._get_router()
        if router is None:
            return "% ip route is only available on router devices."
        if not router.routing_table.remove_static_route(network):
            return f"% Route {network} not found."
        return ""

    def _cmd_ip_default_gateway(self, tokens: list[str]) -> str:
        """ip default-gateway <ip-address>"""
        if len(tokens) < 3:
            return "% Incomplete command."
        from ipaddress import IPv4Address
        try:
            IPv4Address(tokens[2])
        except ValueError:
            return f"% Invalid IP address: {tokens[2]!r}"
        config = self._get_config()
        if config:
            config.ip_default_gateway = tokens[2]
        return ""

    def _cmd_no_ip_default_gateway(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config:
            config.ip_default_gateway = ""
        return ""

    def _cmd_ping(self, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "% Incomplete command.\nUsage: ping <ip-address> [repeat <count>]"
        target = tokens[1]
        repeat = 5
        for i, tok in enumerate(tokens):
            if tok.lower() == "repeat" and i + 1 < len(tokens):
                try:
                    repeat = max(1, min(100, int(tokens[i + 1])))
                except ValueError:
                    pass
        try:
            IPv4Address(target)
        except ValueError:
            return "% Unrecognized host or address, or protocol not running."

        from simulator_core.exceptions import ConfigurationError
        pinger = None
        try:
            pinger = self.simulation.get_host(self.device_id)
        except KeyError:
            pinger = self._get_router() or self._get_switch()
        if pinger is None:
            return "% Ping is not supported on this device type."
        try:
            result = pinger.ping(target, count=repeat)
        except ConfigurationError as exc:
            return f"% {exc}"
        self.simulation.run()

        # One character per echo, in sequence order: '!' reply, '.' timeout.
        replied = {r.sequence for r in result.results if r.success}
        lines = [
            "\nType escape sequence to abort.",
            f"Sending {result.sent}, 100-byte ICMP Echos to {target}, timeout is 2 seconds:",
            "".join("!" if seq in replied else "." for seq in range(result.sent)),
        ]
        pct = int(result.received / result.sent * 100) if result.sent else 0
        summary = f"Success rate is {pct} percent ({result.received}/{result.sent})"
        if result.received:
            rtts = [r.rtt_ticks for r in result.results if r.success and r.rtt_ticks is not None]
            if rtts:
                summary += f", round-trip min/avg/max = {min(rtts)}/{sum(rtts)//len(rtts)}/{max(rtts)} ticks"
        lines.append(summary)
        if result.received == 0:
            reason = next(
                (r.drop_reason for r in result.results if r.drop_reason), None
            )
            from simulator_core.devices.router import DROP_ARP_PENDING
            if reason == DROP_ARP_PENDING:
                # The ARP request was never answered, so nothing was sent.
                reason = ("no ARP reply from the next hop - check its address, "
                          "cabling and that its interface is up")
            if reason:
                lines.append(f"% {reason}")
        return "\n".join(lines)

    def _cmd_show_ip_route(self, tokens: list[str]) -> str:
        """
        show ip route [static | connected | <address>]

        IOS layout: L (local /32) routes alongside each connected network,
        classful "is subnetted" / "is variably subnetted" headers, entries in
        address order, full interface names.
        """
        try:
            router = self.simulation.get_router(self.device_id)
        except KeyError:
            return "% show ip route is only available on router devices."
        from ipaddress import IPv4Address as _Addr, IPv4Network as _Net
        from simulator_core.l3.routing import RouteSource

        device = self.simulation.topology.devices[self.device_id]
        args = tokens[3:]
        rt = router.routing_table

        if args and args[0][:1].isdigit():
            try:
                return self._show_ip_route_entry(rt, _Addr(args[0]))
            except ValueError:
                return _invalid_at(" ".join(tokens[:4]), args[0])

        # (network, code, description) for every displayed route
        entries: list[tuple] = []
        for r in rt.routes:
            if r.source == RouteSource.CONNECTED:
                iface = device.interfaces.get(r.outgoing_interface)
                long = _long_name(r.outgoing_interface)
                entries.append((r.network, "C", f"is directly connected, {long}"))
                if iface is not None and iface.ip_config is not None:
                    entries.append((_Net(f"{iface.ip_config.address}/32"), "L",
                                    f"is directly connected, {long}"))
            elif r.source == RouteSource.STATIC:
                code = "S*" if r.network.prefixlen == 0 else "S"
                if r.next_hop is None:
                    desc = f"is directly connected, {_long_name(r.outgoing_interface)}"
                elif r.exit_interface:
                    desc = f"[1/0] via {r.next_hop}, {_long_name(r.exit_interface)}"
                else:
                    desc = f"[1/0] via {r.next_hop}"
                entries.append((r.network, code, desc))

        if args:
            word = args[0].lower()
            if "static".startswith(word):
                entries = [e for e in entries if e[1].startswith("S")]
            elif "connected".startswith(word):
                entries = [e for e in entries if e[1] in ("C", "L")]
            else:
                return _invalid_at(" ".join(tokens[:4]), args[0])

        default = next((r for r in rt.routes if r.network.prefixlen == 0), None)
        if default is not None and default.next_hop is not None:
            gw_line = f"Gateway of last resort is {default.next_hop} to network 0.0.0.0"
        elif default is not None:
            gw_line = "Gateway of last resort is 0.0.0.0 to network 0.0.0.0"
        else:
            gw_line = "Gateway of last resort is not set"
        lines = [
            "Codes: L - local, C - connected, S - static, * - candidate default",
            "",
            gw_line,
            "",
        ]

        def classful(net) -> Optional[int]:
            first = int(net.network_address) >> 24
            return 8 if first < 128 else 16 if first < 192 else 24 if first < 224 else None

        groups: dict = {}
        for net, code, desc in sorted(entries, key=lambda e: (int(e[0].network_address), e[0].prefixlen)):
            bits = classful(net)
            if bits is None or net.prefixlen < bits:
                groups.setdefault((net, None), []).append((net, code, desc))
            else:
                major = _Net(f"{net.network_address}/{bits}", strict=False)
                groups.setdefault((major, bits), []).append((net, code, desc))

        for (key, bits), items in sorted(groups.items(), key=lambda kv: int(kv[0][0].network_address)):
            subnetted = bits is not None and any(n.prefixlen > bits for n, _, _ in items)
            if subnetted:
                masks = {n.prefixlen for n, _, _ in items}
                if len(masks) == 1:
                    lines.append(f"      {key.network_address}/{masks.pop()} is subnetted, {len(items)} subnets")
                else:
                    lines.append(f"      {key} is variably subnetted, {len(items)} subnets, {len(masks)} masks")
                for net, code, desc in items:
                    lines.append(f"{code:<9}{net} {desc}")
            else:
                for net, code, desc in items:
                    lines.append(f"{code:<6}{net} {desc}")
        return "\n".join(lines)

    def _show_ip_route_entry(self, rt, address) -> str:
        """show ip route <address>: the best matching route in detail."""
        from simulator_core.l3.routing import RouteSource
        route = rt.lookup(address)
        if route is None:
            return "% Network not in table"
        lines = [f"Routing entry for {route.network}"]
        if route.source == RouteSource.CONNECTED:
            lines += [
                '  Known via "connected", distance 0, metric 0 (connected, via interface)',
                "  Routing Descriptor Blocks:",
                f"  * directly connected, via {_long_name(route.outgoing_interface)}",
                "      Route metric is 0, traffic share count is 1",
            ]
        else:
            via = (f"  * {route.next_hop}" if route.next_hop is not None
                   else f"  * directly connected, via {_long_name(route.outgoing_interface)}")
            lines += [
                '  Known via "static", distance 1, metric 0',
                "  Routing Descriptor Blocks:",
                via,
                "      Route metric is 0, traffic share count is 1",
            ]
        return "\n".join(lines)

    def _cmd_show_arp(self, tokens: list[str]) -> str:
        router = self._get_router()
        if router is not None:
            return self._show_router_arp(router.arp_cache)
        switch = self._get_switch()
        if switch is not None:
            return self._show_router_arp(switch.mgmt_arp_cache)
        try:
            host = self.simulation.get_host(self.device_id)
        except KeyError:
            return "% show arp is not supported on this device."

        cache = host.arp_cache
        lines = ["Protocol  Address          Age (min)  Hardware Addr         Type   Interface"]
        if not cache:
            lines.append("(ARP cache is empty)")
        else:
            iface_name = list(self.simulation.topology.devices[self.device_id].interfaces.keys())[0]
            for ip, mac in cache.items():
                lines.append(f"Internet  {str(ip):<16} -          {_cisco_mac(mac)}   ARPA   {iface_name}")
        return "\n".join(lines)

    def _show_router_arp(self, arp_cache: dict) -> str:
        """
        IOS-style router ARP table: the router's own interface addresses
        (age "-") followed by learned neighbours, each on the interface
        whose connected subnet contains it.
        """
        device = self.simulation.topology.devices[self.device_id]
        router = self._get_router()
        rows = []
        own_ips = set()
        for name, iface in device.interfaces.items():
            if (iface.ip_config and iface.admin_state == InterfaceState.UP
                    and iface.oper_state == InterfaceState.UP):
                own_ips.add(iface.ip_config.address)
                rows.append((iface.ip_config.address, "-", iface.mac, name))
        for ip, mac in arp_cache.items():
            if ip in own_ips:
                continue
            iface_name = next(
                (n for n, i in device.interfaces.items()
                 if i.ip_config and ip in i.ip_config.network),
                None,
            )
            if iface_name is None and router is not None:
                # Learned by proxy ARP / exit-interface routing
                route = router.routing_table.lookup(ip)
                iface_name = route.outgoing_interface if route else ""
            rows.append((ip, "0", mac, iface_name or ""))
        lines = ["Protocol  Address          Age (min)  Hardware Addr   Type   Interface"]
        for ip, age, mac, name in sorted(rows, key=lambda r: int(r[0])):
            lines.append(
                f"Internet  {str(ip):<16} {age:>9}   {_cisco_mac(mac)}  ARPA   {_long_name(name)}"
            )
        return "\n".join(lines)
