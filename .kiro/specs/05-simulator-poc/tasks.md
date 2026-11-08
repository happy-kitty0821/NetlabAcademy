# Simulator Proof of Concept — Tasks

**Spec:** `05-simulator-poc`  
**Phase:** 0 — Discovery & Architecture Validation  
**Status:** Draft — awaiting human review

> Do not begin implementation until requirements.md and design.md have been reviewed
> and approved. Each task must pass its own verification step before the next task
> begins. Tasks marked `[TEST]` are test-only tasks that extend coverage.

---

## Dependency graph (summary)

```
T-01 → T-02 → T-03 → T-04 → T-05 → T-06 → T-07 → T-08
                                 ↗
                           T-04
```

In full:

- T-01 (package scaffold) must be first.
- T-02 (addresses) depends on T-01.
- T-03 (topology + exceptions) depends on T-02.
- T-04 (events + scheduler) depends on T-03.
- T-05 (simulation engine + host stubs) depends on T-04.
- T-06 (host protocol logic) depends on T-05.
- T-07 (switch protocol logic) depends on T-06.
- T-08 (integration + determinism + limit tests) depends on T-06 and T-07.
- T-09 (serialisation + JSON round-trip) depends on T-04 (events) and T-08 (full trace).
- T-10 (commit + repo hygiene) depends on all tasks passing.

---

## T-01 — Package scaffold

**Goal:** Create the `packages/simulator-core/` directory structure and package
metadata so the package is importable and the test runner can be invoked.

**Files to create:**

```
packages/simulator-core/
├── pyproject.toml
├── README.md
├── simulator_core/
│   ├── __init__.py          (empty public surface for now)
│   └── exceptions.py        (all custom exception classes)
└── tests/
    └── __init__.py
```

**`pyproject.toml` requirements:**
- `[build-system]` using `setuptools` (stdlib-friendly, no heavy build tools).
- `[project]` with `name = "simulator-core"`, `requires-python = ">=3.12"`,
  `version = "0.1.0"`, no runtime dependencies.
- `[project.optional-dependencies]` with `test = ["pytest==8.3.5", "pytest-cov==5.0.0"]`  
  (verify exact latest patch versions before pinning at implementation time).
- `[tool.pytest.ini_options]` pointing `testpaths` at `tests/`.
- `[tool.coverage.run]` with `source = ["simulator_core"]`.

**`exceptions.py` requirements:**
- `TopologyError(ValueError)` — structural topology violations.
- `ConfigurationError(ValueError)` — invalid device/interface configuration.
- `SimulationLimitError(RuntimeError)` — resource/event limits exceeded.
- `UnsupportedCommandError(ValueError)` — CLI command not in allowlist (reserved for future CLI spec; define the class here so imports work).

**Verification:**
```
cd packages/simulator-core
python -m pytest tests/ -v   # should collect 0 tests, exit 0
python -c "from simulator_core.exceptions import TopologyError; print('OK')"
```

---

## T-02 — Address types

**Goal:** Implement `MACAddress` and `IPv4Interface` as described in design §3.1.

**Files to create/modify:**
- `simulator_core/addresses.py`
- `tests/test_addresses.py`

**Implementation requirements:**
- `MACAddress(value: str)`: validate six colon-separated lowercase hex octets; raise
  `ConfigurationError` on invalid input.
- `MACAddress.generate(rng)`: generate a locally-administered unicast MAC (bit 1 of
  first octet set to 1, bit 0 cleared; use the simulation RNG, not `os.urandom`).
- `MACAddress.is_broadcast`: True iff value == `"ff:ff:ff:ff:ff:ff"`.
- `IPv4Interface.parse(cidr: str)`: accept `"A.B.C.D/N"`, raise `ConfigurationError`
  for malformed strings, prefix lengths outside 0–32, or host bits set in the address
  portion if `/N < 32` and the host bits are non-zero (i.e. reject network addresses
  used as host addresses — network address is still invalid; the actual check is
  `is_host_address` which checks it is neither network nor broadcast).
- `IPv4Interface.network`, `.broadcast`, `.is_host_address`.

**Test requirements (`test_addresses.py`):**
- Valid MAC construction and string round-trip.
- Invalid MAC raises `ConfigurationError` (wrong octet count, non-hex, broadcast input
  to constructor is OK, multicast is OK — we validate at usage, not construction).
- `generate()` produces a locally-administered unicast MAC.
- `generate()` with the same `random.Random(42)` produces the same value twice.
- Valid CIDR parse.
- Invalid CIDR strings raise `ConfigurationError`.
- `is_host_address` returns False for network and broadcast addresses.

**Verification:**
```
python -m pytest tests/test_addresses.py -v
```

---

## T-03 — Topology and link model

**Goal:** Implement `Interface`, `Device`, `Link`, `Topology` as described in
design §3.2, including `validate()` and `neighbours()`.

**Files to create/modify:**
- `simulator_core/topology.py`
- `simulator_core/types.py` (enums and constants)
- `tests/test_topology.py`

**Implementation requirements:**
- `types.py`: `InterfaceState`, `DeviceModel`, `PROPAGATION_DELAY = 1`.
- `Topology.validate()`:
  - At least one device.
  - No duplicate device IDs.
  - No duplicate interface names within a device.
  - No self-links (both endpoints on the same device).
  - Both endpoints of every link exist in `devices`.
  - No interface appears in more than one link.
- `Topology.neighbours(device_id, interface_name)` returns the peer or `None`.
- `Topology` must not accept more than `max_nodes=64` devices or `max_links=128` links
  (checked in `validate()`; defaults configurable at construction or as class constants).

**Test requirements (`test_topology.py`):**
- Valid two-host-one-switch topology constructs without error.
- Duplicate device ID raises `TopologyError`.
- Duplicate interface name raises `TopologyError`.
- Self-link raises `TopologyError`.
- Non-existent link endpoint raises `TopologyError`.
- `neighbours()` returns correct peer.
- `neighbours()` returns `None` for unconnected interface.
- Exceeding node cap raises `TopologyError`.

**Verification:**
```
python -m pytest tests/test_topology.py -v
```

---

## T-04 — Frame/packet types and events

**Goal:** Implement all frame, packet and event dataclasses as described in design
§3.3 and §3.4.

**Files to create/modify:**
- `simulator_core/frames.py`
- `simulator_core/events.py`

**Implementation requirements:**
- All types are `frozen=True` dataclasses.
- `EthernetFrame` carries a `frame_id` (UUID string) assigned at creation time.
  Since the frame is frozen, `frame_id` must be supplied at construction; callers use
  `uuid.uuid4()` — the simulation engine generates this, not the dataclass itself.
- Drop reason constants (`DROP_*`) are module-level strings in `events.py`.
- No test file for this task — types are exercised by subsequent tasks. A minimal
  import smoke test in `tests/test_topology.py` or inline is sufficient.

**Verification:**
```
python -c "from simulator_core.events import ARPRequestSent, FrameDropped; print('OK')"
python -c "from simulator_core.frames import EthernetFrame, ARPMessage; print('OK')"
```

---

## T-05 — Event scheduler and simulation skeleton

**Goal:** Implement `EventScheduler` and the `Simulation` class skeleton (lifecycle
only — `step()`, `run()`, `reset()`; `_dispatch()` is a no-op stub).

**Files to create/modify:**
- `simulator_core/scheduler.py`
- `simulator_core/simulation.py`
- `tests/test_scheduler.py`

**Implementation requirements:**
- `EventScheduler`: heap, depth limit, `schedule()`, `pop()`, `peek_time()`,
  `is_empty()`, `next_seq()`, `clear()` — as specified in design §4.
- `Simulation.__init__`: deep-copy topology snapshot for reset, init RNG, scheduler,
  trace, clock.
- `Simulation.run()` / `step()`: process events, call `_record()`, call `_dispatch()`.
- `Simulation.reset()`: restore clock, RNG, scheduler, trace, device state.
- `_dispatch()` stub: log event type to trace only, no routing yet.
- `_init_devices()` stub: returns empty dict for now.
- **Import guard**: in `simulator_core/__init__.py` add:
  ```python
  import sys as _sys
  _FORBIDDEN = {"socket", "subprocess", "ctypes", "cffi"}
  _loaded = _FORBIDDEN & set(_sys.modules)
  if _loaded:
      raise ImportError(f"simulator_core forbids these modules: {_loaded}")
  ```

**Test requirements (`test_scheduler.py`):**
- Events are popped in ascending `(time, seq)` order.
- Scheduling beyond `max_depth` raises `SimulationLimitError`.
- `is_empty()` / `peek_time()` behave correctly.
- `clear()` resets the heap and seq counter.
- `Simulation` with empty topology and no events: `run()` returns immediately, trace is empty.
- `Simulation.reset()` resets clock to 0 and clears trace.

**Verification:**
```
python -m pytest tests/test_scheduler.py -v
```

---

## T-06 — Host protocol logic

**Goal:** Implement `Host` device protocol logic — ARP cache, ping initiation,
ARP reply handling and ICMP echo reply handling — as described in design §6.1.

**Files to create/modify:**
- `simulator_core/devices/__init__.py` (empty)
- `simulator_core/devices/host.py`
- `simulator_core/simulation.py` (update `_init_devices` to create `Host` instances,
  update `_dispatch` to route `FrameArrival` to host handlers)
- `tests/test_host.py`

**Implementation requirements:**
- `Host` stores a reference to its `Device` (topology entry) and the `Simulation`.
- `Host.ping(dst_ip: str, count: int = 4)`: validates own IP config; checks ARP cache;
  initiates ARP if needed; schedules `ICMPEchoRequestSent` events; collects
  `EchoResult` entries; returns a `PingResult`.
- `Host` handles `FrameArrival`:
  - ARP request → update cache, schedule reply.
  - ARP reply → update cache, unblock pending ping.
  - IPv4/ICMP echo request → schedule echo reply.
  - IPv4/ICMP echo reply → record result.
- `PingResult` and `EchoResult` dataclasses as specified in design §3.5.
- If the host interface is `DOWN` when `ping()` is called: schedule `FrameDropped`
  with `DROP_INTERFACE_ADMIN_DOWN`; do not raise an exception (requirement US-07 /
  AC-07-6 states no unhandled exception from `run()`; the caller's `ping()` call may
  raise `ConfigurationError` only if IP is unconfigured — AC-07-2).
- If the host has no IP configured: raise `ConfigurationError` immediately in `ping()`.

**Test requirements (`test_host.py`):**
- IP assignment accepted for valid CIDR.
- Malformed CIDR raises `ConfigurationError`.
- Address equal to network/broadcast address raises `ConfigurationError`.
- ARP cache starts empty.
- After a simulated ARP exchange (manually schedule events), cache is populated.

**Verification:**
```
python -m pytest tests/test_host.py -v
```

---

## T-07 — Switch protocol logic

**Goal:** Implement `Switch` device protocol logic — MAC learning, known-unicast
forward, unknown-unicast flood, broadcast flood, no-ingress-echo, port-down drop — as
described in design §6.2.

**Files to create/modify:**
- `simulator_core/devices/switch.py`
- `simulator_core/simulation.py` (update `_init_devices` and `_dispatch` for Switch)
- `tests/test_switch.py`

**Implementation requirements:**
- `Switch` owns a MAC address table:
  `dict[tuple[str, int], str]` keyed by `(mac_value, vlan)` → interface_name.
  VLAN is `1` for all frames in this PoC.
- `Switch` handles `FrameArrival`:
  1. Learn source MAC (record `MACTableLearned` event if new).
  2. Lookup destination MAC:
     - Broadcast → flood all ports except ingress, `FrameTransmit` per port.
     - Known unicast → `FrameTransmit` on known port only (not ingress).
     - Unknown unicast → flood all ports except ingress.
  3. Before scheduling each `FrameTransmit`: check egress interface state; if `DOWN`
     schedule `FrameDropped(DROP_PORT_DOWN)` instead.
- `Simulation._dispatch` handles `FrameTransmit` and delivers to peer via
  `topology.neighbours()`; if no link / link down → `FrameDropped`.

**Test requirements (`test_switch.py`):**
- First frame: source MAC learned, broadcast flooded (two port switch → one egress).
- Second frame: known unicast forwarded on correct port only.
- Broadcast always flooded regardless of table state.
- Ingress port never in egress list.
- Port-down egress produces `FrameDropped` with `DROP_PORT_DOWN`.
- `MACTableLearned` event appears in trace.

**Verification:**
```
python -m pytest tests/test_switch.py -v
```

---

## T-08 — Integration and scenario tests

**Goal:** Write the full integration tests covering ARP exchange, ICMP ping, failure
scenarios, determinism and resource limits.

**Files to create/modify:**
- `tests/test_arp.py`
- `tests/test_icmp.py`
- `tests/test_failures.py`
- `tests/test_determinism.py`
- `tests/test_limits.py`
- `tests/scenarios.py` (shared scenario helpers)

**Test requirements:**

`test_arp.py`:
- ARP cache starts empty (AC-04-1).
- Single ARP request/reply cycle; trace contains `ARPRequestSent`, `ARPReplySent`,
  two `ARPCacheUpdated` events (AC-04-2 to AC-04-7).
- Second ping does not produce a second ARP request (AC-04-8).

`test_icmp.py`:
- Successful ping after ARP; trace contains `ICMPEchoRequestSent` and
  `ICMPEchoReplySent`; `PingResult.received == 1` (AC-05-1 to AC-05-3).
- Four-echo batch: `PingResult.received == 4` (AC-05-6).
- Second ping (cache hit): no new ARP events; `received == 1` (AC-05-5).

`test_failures.py`:
- Interface DOWN → `FrameDropped(DROP_INTERFACE_ADMIN_DOWN)` in trace (AC-07-1).
- No IP configured → `ConfigurationError` raised by `ping()` (AC-07-2).
- Different subnets, no gateway → `ConfigurationError` or `FrameDropped(DROP_NO_ROUTE)`
  depending on whether the check is pre-flight or in-flight (AC-07-3; choose one
  behaviour and document it in `design.md`).
- Link disconnected after ARP → `FrameDropped(DROP_PORT_DOWN)` in trace (AC-07-4).
- All failures contain required drop event fields (AC-07-5).
- No unhandled exception propagates from `run()` (AC-07-6).

`test_determinism.py`:
- Same seed, two separate `Simulation` objects → identical traces (AC-08-1).
- Same seed, fresh Python process → use `subprocess` to run a helper script and
  compare serialised traces (AC-08-2). Note: `subprocess` is used in the **test**, not
  in the simulator itself — the import guard applies only to `simulator_core`.
- `reset()` replay → identical traces (AC-08-5).
- JSON round-trip preserves trace equality (AC-08-4).

`test_limits.py`:
- Queue overflow raises `SimulationLimitError` (AC-03-6).
- Tick overflow raises `SimulationLimitError` (AC-03-7, AC-09-2).
- Node cap raises `TopologyError` (AC-09-3).
- Trace cap records `TraceLimitReached` sentinel (AC-09-4).

**Verification:**
```
python -m pytest tests/ -v --tb=short
```
All tests must pass. Coverage of `simulator_core/` must be ≥ 90% line coverage.

---

## T-09 — Serialisation helpers

**Goal:** Implement `trace_to_json()` and `trace_from_json()` as described in
design §10, and verify JSON round-trip.

**Files to create/modify:**
- `simulator_core/serialisation.py`
- `simulator_core/__init__.py` (export `trace_to_json`, `trace_from_json`)
- Tests covered inside `test_determinism.py` (AC-08-4) — no separate test file needed.

**Implementation requirements:**
- Each event class must implement `to_dict(self) -> dict` and a
  `@classmethod from_dict(cls, d: dict) -> "EventClass"`.
- `trace_to_json(trace)` calls `.to_dict()` on each event, adds `"type": class_name`.
- `trace_from_json(data)` uses a registry `{class_name: EventClass}` to dispatch;
  raises `ValueError` for unknown type names.
- No `eval`, `exec` or `pickle` used.

**Verification:**
```
python -m pytest tests/test_determinism.py::test_json_round_trip -v
```

---

## T-10 — Repository hygiene and commit

**Goal:** Ensure the package is clean, documented, linted and committed.

**Steps:**

1. Update `packages/simulator-core/README.md` with:
   - Package purpose and scope.
   - How to install dev dependencies and run tests.
   - Known limitations and what is out of scope.

2. Ensure `packages/simulator-core/` has a `.gitignore` excluding `__pycache__`,
   `*.pyc`, `.pytest_cache`, `dist/`, `*.egg-info/`, `.coverage`, `htmlcov/`.

3. Run the full test suite and confirm all tests pass:
   ```
   python -m pytest tests/ -v --cov=simulator_core --cov-report=term-missing
   ```

4. Confirm `simulator_core` is importable with no Django/database installed:
   ```
   python -c "import simulator_core; print('clean import OK')"
   ```

5. Commit with a message following conventional commits:
   ```
   feat(simulator-core): add simulator proof-of-concept package

   Implements packages/simulator-core with discrete-event simulation engine,
   two-host-one-switch topology, ARP resolution, ICMP echo, deterministic
   replay and bounded resource limits.

   Closes #05-simulator-poc spec requirements AC-01 through AC-09.
   ```

6. Push to a branch (do not push directly to `main`):
   ```
   git checkout -b feat/simulator-poc
   git add packages/simulator-core/ .kiro/specs/05-simulator-poc/
   git commit -m "feat(simulator-core): ..."
   git push -u origin feat/simulator-poc
   ```

**Verification:**
- CI (if configured) passes.
- `git diff main...HEAD` shows only the expected new files.
- No secrets, no `.env` values, no build artefacts committed.

---

## Completion checklist

Before marking this spec done:

- [ ] All acceptance criteria in `requirements.md` are satisfied.
- [ ] All tasks T-01 through T-10 are complete.
- [ ] Test suite passes with ≥ 90% line coverage on `simulator_core/`.
- [ ] Import guard confirmed (no socket/subprocess/ctypes in simulator_core imports).
- [ ] Determinism test passes across two separate process runs.
- [ ] JSON round-trip test passes.
- [ ] `design.md` open assumptions (OA-01 through OA-04) are noted and deferred.
- [ ] Human has reviewed the code diff and test results.
- [ ] Branch is pushed; PR is open for review.
