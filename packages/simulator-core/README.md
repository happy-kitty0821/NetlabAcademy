# simulator-core

NetLab Academy — deterministic discrete-event network simulator core.

## Purpose

This package implements an educational, deterministic network simulator for the
NetLab Academy platform.  It models a documented subset of Ethernet and IP
networking (ARP, ICMP, Ethernet switching) using a logical clock and a
priority-queue discrete-event scheduler.

It has **zero runtime dependencies** beyond the Python standard library (≥ 3.12).
It does **not** use raw sockets, host network interfaces, subprocess, shell
execution, `eval` or any other host-I/O mechanism.  It can be imported and
tested without Django, PostgreSQL, Celery, Redis, Next.js or any other
platform component being installed.

## Scope (proof-of-concept)

This package covers **Stage A** of the simulation engine:

- Two-host, one-switch topology construction and validation.
- IPv4 address configuration on host interfaces.
- ARP request/reply and ARP cache management.
- ICMP echo request/reply (ping).
- Ethernet switch MAC-address learning and unicast/flood forwarding.
- Deterministic, seeded event scheduling and replay.
- Bounded resource limits (queue depth, simulated-time cap, trace size).
- Inspectable typed event trace.

Out of scope: VLANs beyond default VLAN 1, routing, OSPF, DHCP, NAT, IPv6,
STP, CLI terminal, Django integration, database persistence.

## Installation (development)

```sh
cd packages/simulator-core
pip install -e ".[test]"
```

## Running tests

```sh
cd packages/simulator-core
python -m pytest tests/ -v --cov=simulator_core --cov-report=term-missing
```

## Known limitations

- No CLI interface — device configuration is done through the Python API.
- No persistence — the simulation is purely in-memory.
- No per-link propagation delay variation — all links use a uniform 1-tick delay.
- MAC address aging is not implemented in this stage.
- VLAN 1 is the only broadcast domain.
- Logical ticks have no real-time correspondence (unit to be defined in a future ADR).

## Open assumptions (to be resolved before Stage B)

- OA-01: MAC address aging interval.
- OA-02: VLAN numbering convention (confirmed as 1 for this PoC).
- OA-03: Formal logical-tick time unit.
- OA-04: `reset()` strategy for large topologies (deep-copy vs. serialised snapshot).
