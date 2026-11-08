# Simulator Proof of Concept — Requirements

**Spec:** `05-simulator-poc`  
**Phase:** 0 — Discovery & Architecture Validation  
**Status:** Draft — awaiting human review  
**Scope:** `packages/simulator-core/` only. No Django, no database, no frontend.

---

## 1. Purpose

Prove that the NetLab Academy original simulation architecture can model a minimal
Ethernet network — two PC hosts connected through one educational Ethernet switch —
and produce a deterministic, inspectable event trace. This proof of concept is the
gate criterion before any platform-level work begins (see PROJECT_SPEC.md §13 Phase 0).

---

## 2. Roles and context

For this proof of concept there is no authenticated user. The simulator is exercised
directly through its Python API and through automated tests. A future integration will
wrap this core behind an authenticated service boundary (§7.3 of the project spec).

---

## 3. User stories and acceptance criteria

### US-01 — Topology construction

**Story:** As a test harness, I can describe a topology of two PC nodes connected to
one switch and pass it to the simulator, so that the simulator initialises all devices
and links in the correct state before any events are scheduled.

**Acceptance criteria:**

| ID | Criterion |
|----|-----------|
| AC-01-1 | A `Topology` can be constructed with exactly two `Host` nodes and one `Switch` node. |
| AC-01-2 | Each host has one `Interface` with a generated unique unicast MAC address. |
| AC-01-3 | Each switch port connected to a host starts in the `UP` admin and operational state. |
| AC-01-4 | Constructing the topology with fewer than two nodes, duplicate node IDs or duplicate interface names raises a typed `TopologyError`. |
| AC-01-5 | Constructing a link between two interfaces on the same device raises a `TopologyError`. |
| AC-01-6 | Topology construction does not perform any I/O, execute shell commands or open network sockets. |

---

### US-02 — IPv4 host configuration

**Story:** As a test harness, I can assign a valid IPv4 address and prefix to each host
interface, so that each host knows its own address and can derive its network prefix and
broadcast address.

**Acceptance criteria:**

| ID | Criterion |
|----|-----------|
| AC-02-1 | A host interface accepts a valid IPv4 address and prefix length (e.g. `192.168.1.1/24`). |
| AC-02-2 | Setting an address on an interface that is administratively `DOWN` stores the configuration and marks the interface as not yet sending traffic. |
| AC-02-3 | Assigning an address that is already in use on another interface in the same simulation raises a `ConfigurationError`. |
| AC-02-4 | Supplying a malformed address string (e.g. `999.0.0.1/24`, `192.168.1.1/33`) raises a typed `ConfigurationError` with a human-readable message. |
| AC-02-5 | Assigning a host address that equals the network or broadcast address of its own prefix raises a `ConfigurationError`. |
| AC-02-6 | After configuration the host can return its own IP address, MAC address, network prefix, broadcast address and default gateway (if set). |

---

### US-03 — Simulation initialisation and lifecycle

**Story:** As a test harness, I can create a `Simulation` from a topology and seed,
start it, run it to completion or advance it event by event, and reset it back to its
initial state.

**Acceptance criteria:**

| ID | Criterion |
|----|-----------|
| AC-03-1 | `Simulation(topology, seed)` initialises a logical clock at time zero and an empty event queue. |
| AC-03-2 | `simulation.run()` processes all scheduled events and returns when the queue is empty or a configurable tick limit is reached. |
| AC-03-3 | `simulation.step()` processes exactly one event and returns control to the caller. |
| AC-03-4 | `simulation.reset()` restores the simulation to the state it had at construction time, including clock, event queue and all device state. |
| AC-03-5 | Creating a simulation with a `seed` of `42` and then calling `reset()` followed by a replay of the same input commands produces the identical event sequence and identical final device state as the first run. |
| AC-03-6 | The simulation enforces a maximum event queue depth (default 10 000). Attempting to schedule beyond this limit raises a `SimulationLimitError` without corrupting existing state. |
| AC-03-7 | The simulation enforces a maximum simulated-time limit (default 3 600 logical seconds). Scheduling an event beyond this limit raises a `SimulationLimitError`. |
| AC-03-8 | The simulation does not create threads, processes, sockets or file handles. |

---

### US-04 — ARP resolution

**Story:** As a test harness, I can trigger a ping from Host A to Host B. The simulator
must generate an ARP request from Host A, deliver it to Host B through the switch, and
return an ARP reply from Host B back through the switch to Host A so that Host A learns
Host B's MAC address before sending the ICMP echo request.

**Acceptance criteria:**

| ID | Criterion |
|----|-----------|
| AC-04-1 | Before any ARP exchange the ARP cache of each host is empty. |
| AC-04-2 | When Host A needs to reach Host B (same subnet, no cached entry), exactly one `ARPRequest` broadcast event is scheduled. |
| AC-04-3 | The switch floods the ARP request on all ports in the same broadcast domain except the ingress port. |
| AC-04-4 | Host B receives the ARP request and schedules exactly one `ARPReply` unicast event addressed to Host A's MAC. |
| AC-04-5 | After Host A receives the reply, Host A's ARP cache contains an entry mapping Host B's IP address to Host B's MAC address. |
| AC-04-6 | After Host B sends the reply, Host B's ARP cache contains an entry mapping Host A's IP address to Host A's MAC address (populated from the request). |
| AC-04-7 | All ARP events are recorded in the simulation event trace with their logical timestamp, source node, destination node and frame metadata. |
| AC-04-8 | If Host A sends a second ping to the same target, no additional ARP request is generated (cache hit). |

---

### US-05 — ICMP echo (ping)

**Story:** As a test harness, I can schedule a ping command on Host A targeting
Host B's IP address and observe a successful echo request/reply cycle with a reported
round-trip event.

**Acceptance criteria:**

| ID | Criterion |
|----|-----------|
| AC-05-1 | After ARP resolves, Host A sends an `ICMPEchoRequest` encapsulated in an Ethernet frame to Host B's MAC. |
| AC-05-2 | Host B receives the echo request and schedules an `ICMPEchoReply` addressed to Host A. |
| AC-05-3 | Host A receives the echo reply; the ping result records the logical round-trip time (destination node, sequence number, success=True, rtt in logical ticks). |
| AC-05-4 | The echo request event and the echo reply event are both present in the simulation event trace with correct source, destination and timestamp ordering. |
| AC-05-5 | A second ping using the cached ARP entry completes successfully without additional ARP events. |
| AC-05-6 | Sending four successive echo requests produces four echo replies (simulating a standard ping batch). The results list contains four entries, all with `success=True`. |

---

### US-06 — Ethernet switch forwarding and MAC learning

**Story:** As a test harness, I can observe that the switch learns source MAC addresses
from frames it receives and uses learned entries to forward subsequent unicast frames
only on the correct port, without flooding.

**Acceptance criteria:**

| ID | Criterion |
|----|-----------|
| AC-06-1 | When the switch receives a frame, it records the source MAC address and the ingress port in its MAC address table. |
| AC-06-2 | Before the MAC table contains an entry for the destination MAC, the switch floods the frame on all other ports in the same broadcast domain. |
| AC-06-3 | After the switch has learned the destination MAC, it forwards the frame only on the port associated with that MAC. |
| AC-06-4 | Broadcast frames (destination MAC `FF:FF:FF:FF:FF:FF`) are always flooded on all ports except the ingress port, regardless of MAC table state. |
| AC-06-5 | Each MAC table entry in the event trace records the MAC address, learned port, VLAN (default VLAN 1 for this PoC) and the logical timestamp at which it was learned. |
| AC-06-6 | The switch does not forward a frame back out the same port it arrived on. |

---

### US-07 — Failure cases and meaningful errors

**Story:** As a test harness, I can observe that the simulator produces a deterministic,
inspectable failure event when a link is down or an IP configuration is invalid, rather
than silently dropping the frame or hanging.

**Acceptance criteria:**

| ID | Criterion |
|----|-----------|
| AC-07-1 | If a host interface is administratively `DOWN`, any frame it would send is dropped and a `LinkDownDrop` event is recorded in the trace with the reason `"interface administratively down"`. |
| AC-07-2 | If Host A has no IP address configured and attempts a ping, the simulator raises a `ConfigurationError` immediately (before any events are scheduled). |
| AC-07-3 | If Host A and Host B are on different subnets with no default gateway configured, the ping attempt records an `UnreachableDrop` event with reason `"no route to host"`. |
| AC-07-4 | Disconnecting a link between the switch and Host B after ARP has resolved and then issuing a ping from Host A results in the ICMP echo request being dropped at the switch with a `PortDownDrop` event. |
| AC-07-5 | All drop events include: logical timestamp, the node that dropped the frame, the reason string and the frame/packet metadata sufficient to identify the original flow. |
| AC-07-6 | None of the failure cases cause an unhandled Python exception to propagate out of `simulation.run()` or `simulation.step()`. |

---

### US-08 — Deterministic replay

**Story:** As a test harness, I can run the same scenario twice with the same seed and
the same sequence of inputs and get the exact same event trace both times, regardless
of Python interpreter version or run order.

**Acceptance criteria:**

| ID | Criterion |
|----|-----------|
| AC-08-1 | Running `scenario_two_hosts_ping()` with `seed=42` twice in the same process produces identical event trace lists (same event types, same timestamps, same node identifiers, same order). |
| AC-08-2 | Running `scenario_two_hosts_ping()` with `seed=42` in a fresh process produces the same trace as the in-process run. |
| AC-08-3 | Running the same scenario with `seed=99` produces a different trace from `seed=42` only when randomness is actually exercised (e.g. MAC address generation); deterministic protocol mechanics must be identical regardless of seed. |
| AC-08-4 | The event trace can be serialised to JSON and deserialised back to an equivalent list of typed event objects without data loss. |
| AC-08-5 | Calling `simulation.reset()` and re-running with the same commands restores the deterministic trace from step one inside the same process. |

---

### US-09 — Resource limits and host-isolation guarantee

**Story:** As a platform operator, I can trust that the simulator cannot exhaust host
resources, access host networking or execute arbitrary code, even when given a
pathological topology or rapid command injection.

**Acceptance criteria:**

| ID | Criterion |
|----|-----------|
| AC-09-1 | The simulator package imports do not import `socket`, `subprocess`, `os.system`, `ctypes`, `cffi` or any other module that enables host I/O. |
| AC-09-2 | Scheduling more events than the configured maximum raises `SimulationLimitError`; it does not block or OOM. |
| AC-09-3 | The topology admits a maximum of 64 nodes and 128 links per `Simulation` instance (configurable at construction). Exceeding this raises `TopologyError`. |
| AC-09-4 | The event trace is bounded by a configurable maximum size (default 50 000 entries). When the limit is reached the simulation records a `TraceLimitReached` sentinel event and stops appending to the trace (the simulation may continue running). |
| AC-09-5 | The CLI command parser (if used in this PoC) contains an allowlist of supported tokens; any unrecognised token raises `UnsupportedCommandError` rather than evaluating arbitrary Python or shell code. |

---

## 4. Out of scope for this proof of concept

The following items are explicitly deferred and must not be implemented in this spec:

- VLANs beyond the implicit default VLAN 1.
- 802.1Q trunking.
- Routing between subnets (no router device).
- OSPFv2, EIGRP, BGP or any dynamic routing protocol.
- DHCP server or relay.
- NAT/PAT.
- IPv6.
- STP/RSTP.
- Wireless or any non-Ethernet media.
- ACLs.
- CLI terminal (the PoC uses a Python API; CLI is a separate spec).
- Django, PostgreSQL, Celery, Redis or any web framework.
- WebSocket or any real-time transport.
- Frontend or topology editor.
- Authentication or authorisation.

Any attempt to implement out-of-scope items as part of this spec should be rejected
during review and deferred to its own feature spec.
