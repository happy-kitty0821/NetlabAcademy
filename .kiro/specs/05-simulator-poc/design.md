# Simulator Proof of Concept — Design

**Spec:** `05-simulator-poc`  
**Phase:** 0 — Discovery & Architecture Validation  
**Status:** Draft — awaiting human review  
**Package:** `packages/simulator-core/`

---

## 1. High-level design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Location | `packages/simulator-core/` as a standalone Python package | Isolates simulation logic from Django, database and frontend (PROJECT_SPEC §6.1) |
| Simulation model | Discrete-event simulation (DES) with a logical clock | Deterministic, inspectable, pausable, replayable (§6.2) |
| Event ordering | Min-heap priority queue ordered by `(logical_time, sequence_number)` | `sequence_number` is a monotonically increasing integer assigned at schedule time; guarantees total order for same-tick events |
| Randomness | `random.Random(seed)` instance owned by the `Simulation`; never global `random` | Isolates randomness per-simulation, enables replay |
| Typing | Python 3.12+ `dataclasses` + `typing` throughout; no untyped dicts as domain objects | Matches project type-safety rule and PROJECT_SPEC §6.3 |
| Serialisation | `dataclasses` → plain `dict` → JSON; no third-party serialisation library in the core | Keeps the package dependency-free |
| Tests | `pytest` with `pytest-cov` in `packages/simulator-core/tests/` | Standard Python testing aligned with project quality strategy |
| No I/O | Explicit import guard: the package's `__init__.py` asserts that `socket`, `subprocess`, `ctypes` are not imported at load time | Enforces AC-09-1 |

### 1.1 Unresolved assumptions recorded here

The following points were not fully resolved by PROJECT_SPEC.md and are recorded as
open items; they do not block this PoC but must be closed before Stage B work:

- **OA-01:** MAC address aging and exact aging interval — deferred to switching spec.
- **OA-02:** Default VLAN numbering convention (1 vs 0) — this PoC treats the default broadcast domain as VLAN 1; the lab-schema spec must confirm.
- **OA-03:** Logical tick unit (microsecond, millisecond, nanosecond) — this PoC uses an arbitrary integer tick with no real-time correspondence. A formal unit must be defined before RTT is exposed to students.
- **OA-04:** Whether `reset()` deep-copies initial state or reconstructs from a serialised snapshot — this PoC uses deep-copy; the decision affects performance for large topologies.

---

## 2. Package layout

```
packages/simulator-core/
├── pyproject.toml              # package metadata and dependencies (pinned)
├── README.md
├── simulator_core/
│   ├── __init__.py             # public API surface + import guard
│   ├── types.py                # shared enums, constants, primitive type aliases
│   ├── addresses.py            # MACAddress, IPv4Address, IPv4Prefix helpers
│   ├── topology.py             # Topology, Device, Interface, Link
│   ├── frames.py               # EthernetFrame, ARPMessage, IPv4Packet, ICMPMessage
│   ├── events.py               # SimulationEvent hierarchy (all event dataclasses)
│   ├── scheduler.py            # EventScheduler (heap + sequence counter)
│   ├── simulation.py           # Simulation (clock, scheduler, reset, run, step)
│   ├── devices/
│   │   ├── __init__.py
│   │   ├── host.py             # Host device protocol logic
│   │   └── switch.py           # Switch device protocol logic
│   └── exceptions.py           # TopologyError, ConfigurationError, SimulationLimitError,
│                               # UnsupportedCommandError
└── tests/
    ├── __init__.py
    ├── test_addresses.py
    ├── test_topology.py
    ├── test_scheduler.py
    ├── test_host.py
    ├── test_switch.py
    ├── test_arp.py
    ├── test_icmp.py
    ├── test_failures.py
    ├── test_determinism.py
    └── test_limits.py
```

---

## 3. Domain object types

All domain objects are immutable or explicitly mutable with documented mutation points.

### 3.1 Primitive address types (`addresses.py`)

```python
from __future__ import annotations
import re
from dataclasses import dataclass
from ipaddress import IPv4Address as _StdIPv4Address, IPv4Network

@dataclass(frozen=True)
class MACAddress:
    """48-bit unicast MAC address stored as a normalised lowercase colon-hex string."""
    value: str                    # e.g. "aa:bb:cc:dd:ee:ff"

    def __post_init__(self) -> None:
        # validate 6 octets, colon-separated, hex
        ...

    @staticmethod
    def generate(rng: random.Random) -> "MACAddress":
        """Generate a locally-administered, unicast MAC using the simulation RNG."""
        ...

    @property
    def is_broadcast(self) -> bool: ...

    def __str__(self) -> str: return self.value


@dataclass(frozen=True)
class IPv4Interface:
    """An IPv4 address bound to a prefix length."""
    address: _StdIPv4Address
    prefix_length: int            # 0–32

    @staticmethod
    def parse(cidr: str) -> "IPv4Interface":
        """Parse '192.168.1.1/24'; raises ConfigurationError on invalid input."""
        ...

    @property
    def network(self) -> IPv4Network: ...
    @property
    def broadcast(self) -> _StdIPv4Address: ...
    @property
    def is_host_address(self) -> bool:
        """True iff address is not the network or broadcast address."""
        ...
```

### 3.2 Topology (`topology.py`)

```python
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional
from .addresses import MACAddress, IPv4Interface

class InterfaceState(Enum):
    UP   = auto()
    DOWN = auto()

class DeviceModel(Enum):
    HOST   = "host"
    SWITCH = "switch"

@dataclass
class Interface:
    name: str                          # e.g. "eth0", "Gi0/1"
    mac: MACAddress
    admin_state: InterfaceState = InterfaceState.UP
    oper_state:  InterfaceState = InterfaceState.UP
    ip_config:   Optional[IPv4Interface] = None
    # counters
    rx_frames: int = field(default=0, repr=False)
    tx_frames: int = field(default=0, repr=False)

@dataclass
class Device:
    id: str                            # stable UUID string
    model: DeviceModel
    hostname: str
    interfaces: dict[str, Interface]   # name → Interface

@dataclass
class Link:
    id: str
    endpoint_a: tuple[str, str]        # (device_id, interface_name)
    endpoint_b: tuple[str, str]
    admin_state: InterfaceState = InterfaceState.UP

@dataclass
class Topology:
    devices: dict[str, Device]         # device_id → Device
    links: list[Link]

    def validate(self) -> None:
        """Raise TopologyError for any structural violation."""
        ...

    def neighbours(self, device_id: str, interface_name: str) -> Optional[tuple[str, str]]:
        """Return (peer_device_id, peer_interface_name) or None if no link."""
        ...
```

### 3.3 Frame and packet types (`frames.py`)

```python
from dataclasses import dataclass
from typing import Union
from ipaddress import IPv4Address

from .addresses import MACAddress

@dataclass(frozen=True)
class ARPMessage:
    operation: int          # 1=request, 2=reply
    sender_mac: MACAddress
    sender_ip:  IPv4Address
    target_mac: MACAddress  # zero MAC for requests
    target_ip:  IPv4Address

@dataclass(frozen=True)
class ICMPMessage:
    type: int               # 8=echo-request, 0=echo-reply
    code: int
    sequence: int
    identifier: int
    payload: bytes = b""

@dataclass(frozen=True)
class IPv4Packet:
    src: IPv4Address
    dst: IPv4Address
    protocol: int           # 1=ICMP
    ttl: int
    payload: Union[ICMPMessage]  # extend for future protocols

@dataclass(frozen=True)
class EthernetFrame:
    src_mac: MACAddress
    dst_mac: MACAddress
    ethertype: int          # 0x0800=IPv4, 0x0806=ARP
    payload: Union[IPv4Packet, ARPMessage]
    # metadata — not part of wire format, used for tracing
    frame_id: str           # UUID assigned at creation
```

### 3.4 Event hierarchy (`events.py`)

All events are frozen dataclasses that extend `SimulationEvent`. The event type tag
is the class itself; no string-typed discriminator is needed.

```python
from dataclasses import dataclass
from typing import Optional
from .frames import EthernetFrame, ARPMessage, ICMPMessage

@dataclass(frozen=True)
class SimulationEvent:
    """Base class for all simulation events."""
    time: int               # logical tick
    seq:  int               # tie-breaker (assigned by scheduler)

# ── Frame delivery ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FrameArrival(SimulationEvent):
    """A frame arrives at a device interface."""
    device_id:      str
    interface_name: str
    frame:          EthernetFrame

@dataclass(frozen=True)
class FrameTransmit(SimulationEvent):
    """A device transmits a frame on an interface."""
    device_id:      str
    interface_name: str
    frame:          EthernetFrame

# ── ARP ───────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ARPRequestSent(SimulationEvent):
    device_id: str
    message:   ARPMessage

@dataclass(frozen=True)
class ARPReplySent(SimulationEvent):
    device_id: str
    message:   ARPMessage

@dataclass(frozen=True)
class ARPCacheUpdated(SimulationEvent):
    device_id:  str
    ip_address: str        # IPv4Address.str()
    mac_address: str       # MACAddress.str()

# ── MAC table ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MACTableLearned(SimulationEvent):
    switch_id:      str
    mac_address:    str
    interface_name: str
    vlan:           int

# ── ICMP ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ICMPEchoRequestSent(SimulationEvent):
    src_device_id: str
    dst_device_id: str
    message:       ICMPMessage

@dataclass(frozen=True)
class ICMPEchoReplySent(SimulationEvent):
    src_device_id: str
    dst_device_id: str
    message:       ICMPMessage

# ── Drops / failures ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FrameDropped(SimulationEvent):
    device_id:      str
    interface_name: Optional[str]
    frame:          EthernetFrame
    reason:         str     # human-readable; one of a defined set of constants

# ── Limits ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TraceLimitReached(SimulationEvent):
    limit: int
```

**Drop reason constants** (defined in `events.py`):

```python
DROP_INTERFACE_ADMIN_DOWN = "interface administratively down"
DROP_PORT_DOWN            = "port down"
DROP_NO_ROUTE             = "no route to host"
DROP_TTL_EXCEEDED         = "TTL exceeded"
DROP_UNRESOLVABLE_ARP     = "ARP unresolvable — target unreachable"
```

### 3.5 PingResult (returned by `Host.ping()`)

```python
@dataclass
class PingResult:
    target_ip:   str
    count:       int
    sent:        int
    received:    int
    results:     list[EchoResult]

@dataclass(frozen=True)
class EchoResult:
    sequence:  int
    success:   bool
    rtt_ticks: Optional[int]   # None if no reply received
    drop_reason: Optional[str]
```

---

## 4. Event scheduler (`scheduler.py`)

```python
import heapq
from dataclasses import dataclass
from typing import Optional
from .events import SimulationEvent
from .exceptions import SimulationLimitError

class EventScheduler:
    """
    Min-heap priority queue.
    Ordering: (event.time, event.seq) — total order, no ties possible.
    """
    MAX_DEPTH = 10_000   # default; overridable at construction

    def __init__(self, max_depth: int = MAX_DEPTH) -> None:
        self._heap: list[tuple[int, int, SimulationEvent]] = []
        self._seq:  int = 0
        self._max_depth = max_depth

    def schedule(self, event: SimulationEvent) -> None:
        if len(self._heap) >= self._max_depth:
            raise SimulationLimitError(
                f"Event queue depth limit {self._max_depth} reached"
            )
        heapq.heappush(self._heap, (event.time, event.seq, event))

    def pop(self) -> SimulationEvent:
        _, _, event = heapq.heappop(self._heap)
        return event

    def peek_time(self) -> Optional[int]:
        return self._heap[0][0] if self._heap else None

    def is_empty(self) -> bool:
        return not self._heap

    def next_seq(self) -> int:
        seq = self._seq
        self._seq += 1
        return seq

    def clear(self) -> None:
        self._heap.clear()
        self._seq = 0
```

---

## 5. Simulation engine (`simulation.py`)

```python
import copy
import random
from dataclasses import dataclass, field
from typing import Optional
from .topology  import Topology
from .scheduler import EventScheduler
from .events    import SimulationEvent, TraceLimitReached
from .exceptions import SimulationLimitError

class Simulation:
    """
    Discrete-event simulation runtime.

    Owns: logical clock, event scheduler, device protocol state, event trace.
    Does not own: topology description (passed in at construction).
    """
    DEFAULT_MAX_TICKS       = 3_600
    DEFAULT_MAX_TRACE       = 50_000
    DEFAULT_MAX_QUEUE_DEPTH = 10_000

    def __init__(
        self,
        topology:       Topology,
        seed:           int = 0,
        max_ticks:      int = DEFAULT_MAX_TICKS,
        max_trace:      int = DEFAULT_MAX_TRACE,
        max_queue:      int = DEFAULT_MAX_QUEUE_DEPTH,
    ) -> None:
        topology.validate()
        self._topology_snapshot = copy.deepcopy(topology)  # for reset()
        self._seed = seed
        self._max_ticks = max_ticks
        self._max_trace = max_trace
        self._rng = random.Random(seed)
        self._clock = 0
        self._scheduler = EventScheduler(max_depth=max_queue)
        self._trace: list[SimulationEvent] = []
        self._devices = self._init_devices(topology)

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def clock(self) -> int: return self._clock

    @property
    def trace(self) -> list[SimulationEvent]:
        return list(self._trace)  # defensive copy

    def schedule(self, event: SimulationEvent) -> None:
        """Schedule an event; raises SimulationLimitError if tick > max_ticks."""
        if event.time > self._max_ticks:
            raise SimulationLimitError(
                f"Event at tick {event.time} exceeds max_ticks {self._max_ticks}"
            )
        self._scheduler.schedule(event)

    def step(self) -> Optional[SimulationEvent]:
        """Process one event. Returns the event, or None if queue is empty."""
        if self._scheduler.is_empty():
            return None
        event = self._scheduler.pop()
        self._clock = event.time
        self._record(event)
        self._dispatch(event)
        return event

    def run(self) -> None:
        """Process all events."""
        while not self._scheduler.is_empty():
            self.step()

    def reset(self) -> None:
        """Restore initial state. Subsequent run() with same commands → same trace."""
        self._clock = 0
        self._rng = random.Random(self._seed)
        self._scheduler.clear()
        self._trace.clear()
        self._devices = self._init_devices(copy.deepcopy(self._topology_snapshot))

    # ── Internal ─────────────────────────────────────────────────────────────

    def _record(self, event: SimulationEvent) -> None:
        if len(self._trace) >= self._max_trace:
            if not any(isinstance(e, TraceLimitReached) for e in self._trace[-5:]):
                self._trace.append(
                    TraceLimitReached(time=self._clock,
                                      seq=self._scheduler.next_seq(),
                                      limit=self._max_trace)
                )
            return
        self._trace.append(event)

    def _dispatch(self, event: SimulationEvent) -> None:
        """Route events to the correct device handler."""
        ...

    def _init_devices(self, topology: Topology) -> dict:
        """Instantiate Host and Switch protocol objects from topology."""
        ...
```

---

## 6. Device protocol logic

### 6.1 Host (`devices/host.py`)

Responsibilities:
- Maintain ARP cache: `dict[IPv4Address, MACAddress]`.
- Maintain pending ping results awaiting reply.
- On `FrameArrival`:
  - Decode ARP frame → update cache, schedule ARPReply if request.
  - Decode IPv4/ICMP echo request → schedule ICMPEchoReply.
  - Decode IPv4/ICMP echo reply → complete pending ping result.
- Expose `ping(dst_ip, count, simulation)`:
  1. Validate own IP is configured; raise `ConfigurationError` immediately if not.
  2. **Pre-flight route check:** if `dst_ip` is outside the host's local subnet and no
     default gateway is configured, return a `PingResult` immediately with `received=0`
     and each `EchoResult` having `success=False` and
     `drop_reason="no route to host — destination outside local subnet and no gateway configured"`.
     No events are scheduled, no frames are transmitted, no `ConfigurationError` is raised.
  3. Check ARP cache for `dst_ip`.
  4. If miss: schedule `ARPRequestSent` + `FrameTransmit` (broadcast) at `clock + 1`.
     Register a pending ARP callback that, when the reply arrives, continues with step 5.
  5. Schedule `ICMPEchoRequestSent` + `FrameTransmit` (unicast to dst MAC) at `clock + 2`.

### 6.2 Switch (`devices/switch.py`)

Responsibilities:
- Maintain MAC address table: `dict[tuple[str, int], str]` i.e. `(mac, vlan) → interface_name`.
- On `FrameArrival`:
  1. Learn source MAC → record `MACTableLearned` event.
  2. If dst MAC is broadcast → flood all ports except ingress, schedule `FrameTransmit` per port.
  3. If dst MAC is unicast and found in table → forward, schedule `FrameTransmit` on that port only.
  4. If dst MAC is unicast and not found → flood (unknown unicast).
  5. Never transmit back on ingress port.
  6. If egress port is `DOWN` → schedule `FrameDropped` with `DROP_PORT_DOWN`.

---

## 7. Frame delivery model

The `Simulation._dispatch()` method implements delivery as follows:

```
FrameTransmit(device_id, interface_name, frame)
  → look up link from topology.neighbours(device_id, interface_name)
  → if link admin_state is DOWN or interface oper_state is DOWN:
      schedule FrameDropped at same tick + 1
  → else:
      schedule FrameArrival(peer_device_id, peer_interface_name, frame)
      at current_tick + PROPAGATION_DELAY (default: 1 tick)
```

`PROPAGATION_DELAY = 1` is a named constant in `types.py`. All link delays are uniform
in the PoC; per-link delay is a future enhancement.

---

## 8. ARP flow (sequence)

```
tick 0: simulation.schedule(ICMPPingCommand)   ← caller injects via host.ping()
tick 1: ARPRequestSent + FrameTransmit(host_a, eth0, bcast)
tick 2: FrameArrival(switch, port1, arp_req)
        → MACTableLearned(switch, mac_a, port1)
        → FrameTransmit(switch, port2, arp_req)   [flood]
tick 3: FrameArrival(host_b, eth0, arp_req)
        → ARPCacheUpdated(host_b, ip_a, mac_a)
        → ARPReplySent + FrameTransmit(host_b, eth0, unicast to mac_a)
tick 4: FrameArrival(switch, port2, arp_reply)
        → MACTableLearned(switch, mac_b, port2)   [if not already learned]
        → FrameTransmit(switch, port1, arp_reply) [known unicast]
tick 5: FrameArrival(host_a, eth0, arp_reply)
        → ARPCacheUpdated(host_a, ip_b, mac_b)
        → [ARP resolved; continue with ICMP]
tick 6: ICMPEchoRequestSent + FrameTransmit(host_a, eth0, unicast)
...
```

The exact tick numbers are illustrative. Actual ticks depend on the scheduler's
propagation delay constant and event ordering at each tick.

---

## 9. Simulator public API boundary

The public surface exposed from `simulator_core/__init__.py`:

```python
# Topology construction
from simulator_core.topology   import Topology, Device, Interface, Link, DeviceModel, InterfaceState
from simulator_core.addresses  import MACAddress, IPv4Interface

# Simulation lifecycle
from simulator_core.simulation import Simulation

# Device interaction
from simulator_core.devices.host   import Host
from simulator_core.devices.switch import Switch

# Events (for trace inspection)
from simulator_core.events import (
    SimulationEvent,
    FrameArrival, FrameTransmit, FrameDropped,
    ARPRequestSent, ARPReplySent, ARPCacheUpdated,
    MACTableLearned,
    ICMPEchoRequestSent, ICMPEchoReplySent,
    TraceLimitReached,
    # Drop reason constants
    DROP_INTERFACE_ADMIN_DOWN, DROP_PORT_DOWN,
    DROP_NO_ROUTE, DROP_TTL_EXCEEDED, DROP_UNRESOLVABLE_ARP,
)

# Result types
from simulator_core.devices.host import PingResult, EchoResult

# Exceptions
from simulator_core.exceptions import (
    TopologyError,
    ConfigurationError,
    SimulationLimitError,
    UnsupportedCommandError,
)
```

No other internals are part of the public contract. The `services/simulator/` worker
will import only from this surface.

---

## 10. Serialisation and event trace format

Each event serialises to a JSON object with the following guaranteed fields:

```json
{
  "type":    "ARPRequestSent",
  "time":    3,
  "seq":     7,
  "device_id": "host-a-uuid",
  "message": { ... }
}
```

A `trace_to_json(trace: list[SimulationEvent]) -> list[dict]` helper is exposed.
`trace_from_json(data: list[dict]) -> list[SimulationEvent]` reconstructs the list
for replay comparison in tests.

The serialisation uses a registry pattern: each event class registers its own
`to_dict` / `from_dict` methods, called by the helpers. No `eval` or `pickle` is used.

---

## 11. Test strategy

### 11.1 Test categories

| Category | Module | Description |
|----------|--------|-------------|
| Unit — addresses | `test_addresses.py` | MACAddress validation, generation, broadcast check; IPv4Interface parsing, host-address check |
| Unit — topology | `test_topology.py` | Valid construction, error cases (dup IDs, self-link, bad args) |
| Unit — scheduler | `test_scheduler.py` | Ordering, depth limit, tick limit, empty-queue behaviour |
| Unit — host | `test_host.py` | IP config acceptance/rejection; ARP cache operations |
| Unit — switch | `test_switch.py` | MAC learning, known-unicast forward, flood, no-ingress-echo, port-down drop |
| Integration — ARP | `test_arp.py` | Full ARP request/reply cycle; cache state after exchange; no second ARP on cache hit |
| Integration — ICMP | `test_icmp.py` | Ping success, four-echo batch, second ping (cache hit), correct trace events |
| Negative | `test_failures.py` | Interface down, no IP, different subnets no GW, disconnected link |
| Determinism | `test_determinism.py` | Same seed same trace; reset replay; seed variation; JSON round-trip |
| Limits | `test_limits.py` | Queue overflow, tick overflow, trace cap, topology node cap |

### 11.2 Scenario helper

A `tests/scenarios.py` module provides reusable scenario builders:

```python
def build_two_host_topology(rng: random.Random) -> tuple[Topology, str, str]:
    """
    Returns (topology, host_a_id, host_b_id).
    Two hosts connected to one switch with generated MACs.
    """

def configure_same_subnet(
    topology: Topology,
    host_a_id: str, ip_a: str,
    host_b_id: str, ip_b: str,
) -> None:
    """Assign IPs; both hosts on the same /24."""
```

### 11.3 Determinism test pattern

```python
def test_deterministic_replay():
    seed = 42
    sim1 = build_sim(seed)
    sim1.get_host("host-a").ping("192.168.1.2", count=1, simulation=sim1)
    sim1.run()
    trace1 = sim1.trace

    sim2 = build_sim(seed)
    sim2.get_host("host-a").ping("192.168.1.2", count=1, simulation=sim2)
    sim2.run()
    trace2 = sim2.trace

    assert trace1 == trace2

def test_reset_replay():
    sim = build_sim(seed=42)
    sim.get_host("host-a").ping("192.168.1.2", count=1, simulation=sim)
    sim.run()
    trace1 = sim.trace

    sim.reset()
    sim.get_host("host-a").ping("192.168.1.2", count=1, simulation=sim)
    sim.run()
    trace2 = sim.trace

    assert trace1 == trace2
```

### 11.4 Negative-case test pattern

```python
def test_ping_interface_down():
    topo, ha, hb = build_two_host_topology(random.Random(1))
    configure_same_subnet(topo, ha, "192.168.1.1/24", hb, "192.168.1.2/24")
    topo.devices[ha].interfaces["eth0"].admin_state = InterfaceState.DOWN
    sim = Simulation(topo, seed=1)
    sim.get_host(ha).ping("192.168.1.2", count=1, simulation=sim)
    sim.run()
    drops = [e for e in sim.trace if isinstance(e, FrameDropped)]
    assert len(drops) == 1
    assert drops[0].reason == DROP_INTERFACE_ADMIN_DOWN

def test_ping_no_route():
    topo, ha, hb = build_two_host_topology(random.Random(1))
    configure_same_subnet(...)  # different subnets, no GW
    sim = Simulation(topo, seed=1)
    with pytest.raises(ConfigurationError):
        sim.get_host(ha).ping("10.0.0.2", count=1, simulation=sim)
```

---

## 12. Dependency list (to be pinned in `pyproject.toml`)

The `simulator-core` package has **zero runtime dependencies** beyond the Python
standard library (Python ≥ 3.12). `ipaddress` is stdlib; `dataclasses` is stdlib.

Development / test dependencies:
- `pytest == 8.3.x` (latest 8.3 patch at implementation time — verify before pinning)
- `pytest-cov == 5.x` (verify current)

No third-party libraries are permitted in the runtime package without a recorded
design decision and explicit approval.

---

## 13. What this design intentionally excludes

- **No CLI parser in this PoC.** Host configuration and ping are invoked via Python
  method calls. A CLI layer is a separate spec.
- **No persistence.** The simulator is purely in-memory for this PoC.
- **No concurrency.** Single-threaded, single-process. Worker/process model is a
  separate ADR (open decision OA-04 in PROJECT_SPEC §16).
- **No Django, ORM or database types.** This package must remain importable without
  Django installed.
- **No real-time wall-clock.** Logical ticks only.
- **No VLAN tagging** beyond default VLAN 1 membership.
