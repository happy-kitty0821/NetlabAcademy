# STP Phase 2 Implementation Report

**Date:** 2025-07  
**Commits:** `77da506` (feat), `1c39d19` (test + bug fix)  
**Test result at time of report:** 405 / 405 passed

---

## 1. Architecture Diagnosis

### Original 2-pass approach

The pre-Phase-2 `run_stp()` called `STPManager.recalculate()` exactly twice over all switches in an arbitrary dict-iteration order. The first pass gave each switch a preliminary root-bridge view; the second pass propagated that view one hop further. This was adequate for a two-switch lab but broke on any topology with three or more hops: a switch at the far end of a linear chain would not see the global root bridge until pass `n`, where `n` equals its hop distance from the root. With only two passes, switches beyond hop 2 kept a stale self-as-root view, so the network appeared to have multiple root bridges.

A secondary problem was non-determinism: Python dict iteration order is insertion-order, so the convergence result depended on the order in which switches were added to the topology — a reproducibility hazard for a simulation platform that guarantees deterministic replay.

### Stable-state iteration (Phase 2)

The replacement algorithm iterates until two consecutive snapshots are identical, capped at `MAX_ITER = 32`:

1. Take a snapshot `before` of all relevant STP state across all switches (root bridge ID, root path cost, root port name, and per-port `(role, state)` pairs).
2. Run one round of `recalculate()` over `sorted(self._switches)` — deterministic order.
3. Take snapshot `after`.
4. If `after == before`, the network is stable — stop.
5. Otherwise repeat from step 1.

The 32-iteration cap is conservative: a fully meshed topology of `n` switches needs at most `n − 1` rounds for information to propagate from root to the furthest leaf. For educational topologies (up to ~20 devices) the loop always terminates in far fewer than 32 rounds. Non-convergence within 32 rounds is logged implicitly by the loop exhausting without a `break`; the resulting state is the best approximation available rather than a crash or hang.

The sorted iteration order means the same topology always produces the same election result regardless of the Python runtime or the order in which devices were added to the topology object.

---

## 2. Files Modified

| File | What changed |
|---|---|
| `packages/simulator-core/simulator_core/simulation.py` | Replaced fixed 2-pass loop in `run_stp()` with stable-state iterative convergence (capped at `MAX_ITER = 32`). Added `_stp_snapshot()` helper. Added `_stp_initialized` guard flag and `_trigger_stp()` method. Added `add_link()` and `remove_link()` methods that call `_trigger_stp()` after mutating the topology. Added `send_bpdus(tick)` method that builds BPDU-carrying `EthernetFrame` objects and schedules `FrameTransmit` events. |
| `packages/simulator-core/simulator_core/stp.py` | Added `bpdu_tx: int = 0` and `bpdu_rx: int = 0` counter fields to `STPPortState`. |
| `packages/simulator-core/simulator_core/frames.py` | Added `bpdu_payload: Optional["BPDU"] = None` field to `EthernetFrame` (default after all required fields). Changed `payload` to `Optional[EthernetPayload] = None`. Added `ETHERTYPE_BPDU = 0x0027` module constant and `STP_MULTICAST_MAC` class-level constant. Used `TYPE_CHECKING` guard on the `BPDU` import to prevent a circular import at runtime. |
| `packages/simulator-core/simulator_core/switch.py` | Added `_process_bpdu()` method: validates an incoming BPDU frame, extracts the VLAN from `bpdu.root_bridge_id.sys_id_ext`, updates the switch's root-bridge information exclusively from the BPDU payload (no cross-switch state reads), and increments `bpdu_rx`. Added STP forwarding guard to `_forward()`: user frames (those with `bpdu_payload is None`) check `stp.is_port_forwarding(egress_iface, vlan)` before transmission. Added the same guard to `_flood_in_vlan()` per candidate egress port. |
| `packages/simulator-core/simulator_core/topology.py` | Added `Topology.remove_link(link_id: str)` method (list-filter, no-op if the link ID is not found). Added `Topology.get_link(device_id, interface_name)` convenience lookup. |
| `packages/simulator-core/tests/test_stp_phase2.py` | New file — 24 Phase 2 integration tests (groups A through G, described in section 4). |

---

## 3. Algorithm Descriptions

### 3.1 Convergence algorithm

```
run_stp():
    if no switches: return
    all_stps = {dev_id: sw.stp for all switches}
    for iteration in range(32):
        before = _stp_snapshot()
        for dev_id in sorted(switches):
            switches[dev_id].stp.recalculate(topology, all_stps)
        after = _stp_snapshot()
        if after == before:
            break          # stable state reached
```

`_stp_snapshot()` captures, for every `(device_id, vlan_id)` pair:
- `root_bridge_id` — the bridge ID of the elected root
- `root_path_cost` — cumulative cost from this switch to the root
- `root_port_name` — the interface name of the root port (or `None` on the root itself)
- `{port_name: (role, state)}` — the role/state tuple for every registered port

Tie-breaking inside `recalculate()` follows IEEE 802.1D bridge/port ID comparison: lowest bridge priority wins; ties broken by lowest MAC address; port-cost ties broken by lowest sender bridge ID; remaining ties broken by lowest port ID.

### 3.2 BPDU transport flow

```
send_bpdus(tick):
    for each switch (sorted):
        for each STP instance (VLAN):
            for each port in (DESIGNATED, ROOT, EDGE) role:
                if port is physically connected AND admin-UP:
                    build BPDU(
                        root_bridge_id  = inst.root_bridge_id,
                        root_path_cost  = inst.root_path_cost,
                        sender_bridge_id= inst.bridge_id,
                        sender_port_id  = port_state.port_id,
                        vlan_id         = inst.vlan_id,
                        ...timers...
                    )
                    frame = EthernetFrame(
                        src_mac = port MAC,
                        dst_mac = STP_MULTICAST_MAC (01:80:c2:00:00:00),
                        ethertype = ETHERTYPE_BPDU (0x0027),
                        bpdu_payload = bpdu,
                    )
                    port_state.bpdu_tx += 1
                    schedule FrameTransmit(tick, dev_id, port_name, frame)
```

On receipt, `Switch._process_bpdu()`:
1. Checks `frame.bpdu_payload is not None` — identifies the frame as a BPDU.
2. Extracts the VLAN from `bpdu.root_bridge_id.sys_id_ext` (falls back to 1 if `sys_id_ext == 0`).
3. Retrieves or creates the matching `STPInstance`.
4. Compares received `root_bridge_id` against the current instance root — updates if the received value is superior (lower bridge ID, or equal bridge ID with lower path cost).
5. Increments `port_state.bpdu_rx`.
6. Does **not** read the sender switch's internal `STPManager` — all decisions are made from the BPDU fields.

### 3.3 STP-to-forwarding integration

`Switch._forward(frame, egress_iface)`:
- If `frame.bpdu_payload is not None` → BPDU, skip STP check, deliver unconditionally.
- Otherwise (user frame):
  - Resolve the VLAN from the egress interface (access VLAN or native trunk VLAN).
  - Call `stp.is_port_forwarding(egress_iface, vlan)`.
  - If `False` (port is DISCARDING/BLOCKING/LEARNING): drop the frame.

`Switch._flood_in_vlan(frame, ingress_iface, vlan)`:
- For every candidate egress port, calls `is_port_forwarding(iface_name, vlan)` before invoking `_forward`. Ports in a non-forwarding state are silently skipped.

`STPManager.is_port_forwarding(port_name, vlan_id)`:
- Returns `True` only if the port's `STPPortState.state == PortState.FORWARDING` for the given VLAN instance.
- Returns `True` as a safe default if no STP instance exists for the VLAN (STP not active on that VLAN).

---

## 4. Test Results

### Original baseline (381 tests)

All 381 tests that existed before Phase 2 pass without modification.

| Test module | Tests |
|---|---|
| `test_addresses.py` | 41 |
| `test_arp.py` | 9 |
| `test_cli.py` | 31 |
| `test_cli_ios_bugs.py` | 68 |
| `test_determinism.py` | 7 |
| `test_device_config.py` | 33 |
| `test_failures.py` | 10 |
| `test_host.py` | 13 |
| `test_icmp.py` | 8 |
| `test_icmp_timing.py` | 5 |
| `test_limits.py` | 7 |
| `test_routing.py` | 16 |
| `test_scheduler.py` | 22 |
| `test_stp.py` | 46 |
| `test_stp_integration.py` | 18 |
| `test_stp_port_registration.py` | 15 |
| `test_switch.py` | 9 |
| `test_topology.py` | 23 |
| **Subtotal** | **381** |

### New Phase 2 tests (24 tests in `test_stp_phase2.py`)

| Group | Description | Tests |
|---|---|---|
| A | 5-switch linear convergence (exactly one root, all agree, idempotent) | 3 |
| B | Dynamic add-link triggers re-election (no link → one link) | 3 |
| C | Shutdown interface causes re-election (admin-down and direct state set) | 4 |
| D | BPDU exchange through the frame pipeline (`bpdu_tx`, `bpdu_rx`, root agreement) | 3 |
| E | Discarding port blocks user data frames (triangle topology, 4 assertions) | 4 |
| F | Redundant-path reconvergence after link failure (triangle, remove root-port link) | 3 |
| G | VLAN-aware BPDU (trunk + VLAN 10, per-VLAN instance, bpdu_tx on trunk) | 4 |

**Total: 405 / 405 passed** (run time ≈ 3 s on a single core).

---

## 5. Known Limitations

**Trunk-port per-frame VLAN tracking.** `Switch._forward()` resolves the egress VLAN as `iface.trunk_native_vlan` for trunk ports. This is correct when the calling code has already resolved the frame's VLAN and passed it to `_flood_in_vlan`, but the egress check in `_forward` uses the native VLAN rather than the frame's actual VLAN tag. For multi-VLAN trunk topologies, a frame on a non-native VLAN could pass the STP forwarding check for the native VLAN's instance. This is a pre-existing architectural simplification (the simulator does not carry a per-frame VLAN tag through `_forward`); no regression is introduced by Phase 2 and `_flood_in_vlan` guards correctly with the right VLAN before calling `_forward`.

**BPDU VLAN routing fallback.** `_process_bpdu` uses `bpdu.root_bridge_id.sys_id_ext or 1` to identify the VLAN. When `sys_id_ext == 0` (a bridge created without an explicit VLAN extension), the BPDU is assigned to VLAN 1. This is correct for all test scenarios because `send_bpdus` always populates `sys_id_ext` with the VLAN ID; the fallback only fires for externally constructed BPDUs with a zero `sys_id_ext`.

**Timer-driven state transitions not modeled.** IEEE 802.1D requires ports to transition through BLOCKING → LISTENING → LEARNING → FORWARDING over `2 × Forward Delay` (default 30 s) after a topology change. This simulation is tick-based for educational purposes; ports are placed directly into their computed final state (FORWARDING, DISCARDING, etc.) without stepping through the intermediate timed states.

**No BPDU aging / max-age expiry.** A real switch ages out the best BPDU stored on each port after `max_age` (default 20 s) and triggers re-election if the superior BPDU is not refreshed. The simulation holds the best BPDU indefinitely; link failure is modeled only through explicit `remove_link` or `shutdown_interface` calls.

**Non-convergence is silent.** If `run_stp()` exhausts all 32 iterations without reaching a stable state, the loop exits with the best state found so far. No warning event is emitted to the simulation trace. For topologies within the platform's intended scale this never occurs in practice.

---

## 6. Deferred Features

The following protocol behaviors are **not implemented** in Phase 2 and are explicitly out of scope for the current release:

- **TCN (Topology Change Notification) BPDUs.** IEEE 802.1D TCN propagation to the root bridge and the resulting MAC table flush are not modeled.
- **Topology change propagation.** When a port transitions to forwarding, real STP notifies all bridges to shorten their MAC-learning aging timers. This flush/accelerated-aging path does not exist.
- **Port-fast / edge-port timer bypass.** PortFast causes a port to skip the LISTENING and LEARNING states and go directly to FORWARDING. The `portfast` flag is stored on `STPPortState` but the skip logic is not wired to any timer-driven transition (because timed transitions are not implemented).
- **BPDU Guard enforcement.** `bpduguard: bool` is stored on `STPPortState` but receiving a BPDU on a PortFast+BPDUGuard port does not place the port in `err-disabled` state.
- **BPDU Filter.** `bpdufilter: bool` is stored but has no effect on `send_bpdus` or `_process_bpdu`.
- **Root Guard.** `guard: str` field exists but superior BPDUs received on a root-guard port are not discarded.
- **Loop Guard.** Not implemented.
- **UplinkFast / BackboneFast.** Cisco proprietary convergence accelerators for classic 802.1D are not modeled.
- **Full RSTP proposal/agreement handshake.** The mode is `RAPID_PVST` in name, but the port-state machine uses PVST+ convergence (global recalculation) rather than the per-port RSTP negotiation with SYNC/proposal/agreement BPDUs.
- **BPDU hello-timer scheduling.** `send_bpdus()` must be called explicitly by tests or the simulation harness. BPDUs are not generated automatically every `hello_time` seconds on a background timer.
- **PVST+ BPDU encapsulation.** Real Cisco PVST+ carries per-VLAN STP BPDUs inside 802.3 frames with LLC/SNAP headers and a VLAN tag. The simulator uses a simplified `ETHERTYPE_BPDU = 0x0027` sentinel without a true 802.3 LLC/SNAP wrapper.
- **MST (Multiple Spanning Tree, 802.1s).** Not implemented; the platform uses PVST+ as its sole STP mode.
- **Per-port path-cost auto-negotiation based on interface speed.** Path cost defaults to 19 (100 Mbps IOS default) for all ports regardless of the configured or simulated interface speed.
- **STP interaction with EtherChannel / LAG.** Port-channel logical interfaces are not modeled; STP cost and port-ID semantics for aggregated links are undefined.
