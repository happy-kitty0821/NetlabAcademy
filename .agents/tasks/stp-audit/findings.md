# STP Implementation Audit — NetLab Academy
**Commits audited:** 77da506, 1c39d19, 57d0643 (branch: main)  
**Test suite result (confirmed):** `405 passed in 5.06s`  
**Date:** 2025  
**Status:** READ-ONLY — no source files were modified.

---

## 1. Executive Summary

The STP implementation is a correctly-functioning **centralized calculator** masquerading as a protocol simulation. The root election and port-role assignment work reliably, but they are computed by a global topology-traversal function (`_recalculate_instance_with_peers`) that reads peer `STPManager` objects directly — not from BPDUs received over the wire. The BPDU frame pipeline (`send_bpdus` → `FrameTransmit` → `FrameArrival` → `_process_bpdu`) exists and is exercised by tests, but its output is immediately discarded because it triggers the same centralized recalculation, making the BPDU path functionally redundant. Periodic BPDU transmission, hello-timer loops, message-age tracking, max-age expiry, and neighbor-failure detection are entirely absent from the implementation. The 405-test suite passes because every test either measures centralized state directly or calls `run_stp()` before asserting — no test would fail if `_process_bpdu` were deleted or if `send_bpdus` were removed.

---

## 2. BPDU Independence Findings

### 2.1 Trace of the BPDU chain

**Full chain exists on paper:**

| Step | Code location | Present? |
|------|--------------|---------|
| BPDU generation | `simulation.send_bpdus()` (simulation.py:299) | ✅ |
| FrameTransmit event | `simulation.schedule(FrameTransmit(...))` (simulation.py:369) | ✅ |
| Link delivery | `simulation._deliver_frame()` (simulation.py:234) | ✅ |
| FrameArrival dispatch | `simulation._handle_frame_arrival()` (simulation.py:272) | ✅ |
| frame_received → _process_bpdu | `switch.handle_frame_arrival()` (switch.py:626) | ✅ |
| STP state update | `switch._process_bpdu()` (switch.py:560) | ⚠️ see §2.2 |

The chain is complete in terms of object calls, but its effect is hollow.

### 2.2 Does `_process_bpdu` read ONLY the received BPDU? — **NO** (HIGH)

`_process_bpdu` reads `bpdu.root_bridge_id`, `bpdu.root_path_cost`, and `bpdu.bridge_id` from the received frame correctly (switch.py:584–607). However, when it determines a received BPDU carries superior root information, it calls:

```python
# switch.py line 607-608
if self._sim is not None:
    self._sim._trigger_stp()
```

`_trigger_stp()` calls `run_stp()` (simulation.py:206), which calls `_recalculate_instance_with_peers()` on every switch. That function reads **all peer `STPManager` objects directly** via the `all_stps` dict (simulation.py:187):

```python
# simulation.py:187-188
all_stps = {dev_id: sw.stp for dev_id, sw in self._switches.items()}
for dev_id in sorted(self._switches):
    self._switches[dev_id].stp.recalculate(self._topology, all_stps)
```

Inside `_recalculate_instance_with_peers` (stp.py:468), the peer election reads:

```python
# stp.py:490-494
peer_inst = peer_stp.get_instance(vlan_id)
if peer_inst and peer_inst.bridge_id:
    all_bids.append(peer_inst.bridge_id)
```

**Conclusion:** Receiving a BPDU triggers a full re-election that ignores the BPDU content in favour of direct peer object inspection. The partial state update in `_process_bpdu` lines 601–606 (`inst.root_bridge_id = bpdu.root_bridge_id`, `inst.root_path_cost = ...`, `inst.root_port_name = ingress_iface`) is immediately overwritten by the following `_trigger_stp()` call, which recomputes everything from scratch.

### 2.3 Can `run_stp()` / centralized recalculation override BPDU-derived state? — **YES** (HIGH)

Every BPDU-derived state update in `_process_bpdu` is overwritten on the very next line by calling `_trigger_stp()`. There is no flag, epoch counter, or priority mechanism to prevent this. The BPDU-derived root info written to lines 601–606 of switch.py is functionally a dead write.

### 2.4 Remaining direct peer STPManager reads in BPDU processing path — **YES** (HIGH)

After `_process_bpdu` → `_trigger_stp` → `run_stp` → `recalculate` → `_recalculate_instance_with_peers`, the function at stp.py:490 reads every peer's `STPManager` directly. This is a direct peer object read triggered by the BPDU receipt path, not an isolated centralized calculation.

---

## 3. Protocol Lifecycle Findings

### 3.1 Periodic BPDU transmission — **NOT IMPLEMENTED** (HIGH)

`send_bpdus(tick)` is a one-shot method that must be called explicitly. There is no event scheduled to call it again at `tick + hello_time`. Searching the entire codebase finds zero instances of:
- A recurring `send_bpdus` call
- A hello-timer event type
- Any scheduled self-rescheduling in `send_bpdus`

BPDUs are transmitted once per explicit test invocation. The simulation clock advances but no new BPDUs are generated.

### 3.2 Message-age tracking — **PARTIAL** (MED)

The `BPDU` dataclass has a `message_age: int = 0` field (stp.py:154). `send_bpdus` always sets `message_age=0` (simulation.py:348). `_process_bpdu` does not read or increment `message_age`. The field is populated in the BPDU wire object but never used in any decision.

### 3.3 Max-age expiration — **NOT IMPLEMENTED** (HIGH)

No code anywhere checks whether a port's `best_bpdu.message_age >= max_age`. The `STPPortState.best_bpdu` field (stp.py:187) is updated on receipt but never aged out. A switch that stops receiving BPDUs will permanently retain the last-known root info. This means neighbor failure detection is impossible through the BPDU path.

### 3.4 Neighbor failure detection — **PARTIAL** (HIGH)

The only mechanism for detecting upstream root failure is `simulation.remove_link()` and `Switch.shutdown_interface()`, both of which call `_trigger_stp()` → centralized recalculation. This works for topological changes known to the test harness but does not model the real protocol behavior where a switch detects root loss by aging out received BPDUs after `max_age` seconds of silence.

### 3.5 Proper event cancellation/cleanup during reset — **PARTIAL** (MED)

`simulation.reset()` calls `self._scheduler.clear()` (simulation.py:135), which removes all pending events. This correctly clears any in-flight `FrameTransmit` BPDU events. However, there is no mechanism to cancel only BPDU-related events (e.g., to restart periodic transmission at a new interval) because periodic transmission is never scheduled in the first place. After reset, `send_bpdus` must be called manually again.

---

## 4. Port-Role and State Transition Findings

### 4.1 Discarding / Learning / Forwarding states — **PARTIAL** (MED)

`PortState` enum has DISCARDING and FORWARDING. Alternate ports are set to DISCARDING in Rapid-PVST mode (stp.py:559–562). However:
- **LEARNING state is never assigned** to any port during transitions. The comment in `STPManager.is_port_learning_or_forwarding` (stp.py:306) explicitly acknowledges: *"ports go directly to FORWARDING in the current educational model"*.
- Ports transition immediately from BLOCKING/DISCARDING to FORWARDING on reconvergence, with no learning delay.

### 4.2 RSTP Proposal/Agreement — **NOT IMPLEMENTED** (HIGH)

The BPDU dataclass has `agreement: bool = False` and `port_role: int = 0` fields (stp.py:143–145). These are populated in `send_bpdus` as zeros and are never read. `_process_bpdu` does not implement the RSTP proposal-agreement handshake. Fast transitioning via proposal/agreement is not modeled.

### 4.3 Edge-port (PortFast) behavior — **IMPLEMENTED** (LOW)

`set_portfast(iface, True)` correctly sets `role=PortRole.EDGE`, `state=PortState.FORWARDING` immediately (stp.py:286–290). The centralized election preserves the EDGE role (stp.py:508–510). This works correctly for its stated educational purpose.

### 4.4 Point-to-point link detection — **PARTIAL** (LOW)

The `_format_instance` method in STPManager renders `"P2p"` for all ports (stp.py:810: `type_flags = "P2p" + (" Edge" if port.portfast else "")`). This is a display-only assumption — there is no actual point-to-point link detection from duplex mode or topology.

### 4.5 Backup port role — **NOT IMPLEMENTED** (MED)

`PortRole.BACKUP` is defined and displayed, but `_recalculate_instance_with_peers` never assigns it. The backup role requires detecting two ports on the same LAN segment (same bridge as the designated bridge). The centralized algorithm only assigns DESIGNATED, ROOT, or ALTERNATE. No topology in any test produces a BACKUP role port.

### 4.6 Alternate-to-root-port transition during failure recovery — **NO LEARNING DELAY** (MED)

When `sim.remove_link()` causes an alternate port to become a root port, `_recalculate_instance_with_peers` sets it directly to FORWARDING. No learning timer is applied. For an educational RSTP simulator this is noted; for IEEE 802.1D it would be a correctness violation.

---

## 5. Forwarding Enforcement Findings

### 5.1 STP check on ingress — **CORRECT** (OK)

`handle_frame_arrival` (switch.py:642–645) checks `is_port_forwarding(ingress_iface, vlan)` before learning or forwarding. This is correctly placed after the BPDU bypass.

### 5.2 STP check on known unicast egress — **CORRECT** (OK)

`_forward` (switch.py:704–713) checks `is_port_forwarding(egress_iface, vlan)` for user frames before transmitting.

### 5.3 STP check on unknown unicast/broadcast — **CORRECT** (OK)

`_flood_in_vlan` (switch.py:747–748) checks `is_port_forwarding(iface_name, vlan)` for each candidate egress port.

### 5.4 Trunk port egress VLAN for STP check — **BUG** (MED)

In `_forward` (switch.py:708–712), when the egress port is a trunk, the code uses `iface.trunk_native_vlan` for the STP check:

```python
vlan = (
    iface.vlan
    if iface.switchport_mode == "access"
    else iface.trunk_native_vlan   # always uses native VLAN — WRONG
)
if not self._stp.is_port_forwarding(egress_iface, vlan):
    return
```

If the frame belongs to VLAN 10 and the native VLAN is 1, the STP check is performed against VLAN 1 instead of VLAN 10. A trunk port that is DISCARDING for VLAN 10 but FORWARDING for VLAN 1 will incorrectly forward VLAN 10 traffic. The `_flood_in_vlan` path passes the correct `vlan` parameter but then calls `_forward`, which re-derives it incorrectly.

### 5.5 BPDUs bypass discarding ports — **CORRECT** (OK)

`handle_frame_arrival` (switch.py:625–628) processes BPDUs before the ingress STP check. BPDUs are not forwarded; they are consumed by `_process_bpdu`. This is correct.

### 5.6 MAC learning blocked on discarding ports — **CORRECT** (OK)

The `_learn` call (switch.py:649) is only reached after the ingress forwarding check at line 642. A discarding port returns before line 649.

### 5.7 BPDU egress STP bypass — **CORRECT** (OK)

`_forward` (switch.py:702–703) explicitly bypasses the STP egress check for BPDU frames (`if frame.bpdu_payload is None`).

---

## 6. VLAN-Specific STP Findings

### 6.1 Per-VLAN independent instances — **IMPLEMENTED** (OK)

`STPManager._instances` is a `dict[int, STPInstance]`, one per VLAN. `BridgeID.sys_id_ext` carries the VLAN ID, ensuring different bridge IDs for different VLANs even with the same MAC and priority. Test F (test_stp_integration.py) and Test G (test_stp_phase2.py) both confirm independent per-VLAN root elections.

### 6.2 Per-VLAN BPDU VLAN identification — **BUG** (MED)

In `_process_bpdu` (switch.py:568–569):

```python
vlan_id = bpdu.root_bridge_id.sys_id_ext or 1
```

This uses `or 1`, meaning a BPDU for VLAN 0 (a theoretical edge case) would be mapped to VLAN 1. More importantly, for classic 802.1D (non-PVST+) BPDUs where `sys_id_ext=0`, this correctly falls back to VLAN 1. However, `send_bpdus` builds BPDU objects where `bridge_id.sys_id_ext` is the VLAN ID (from `inst.bridge_id`), so round-trip is correct for PVST+. The issue is a latent correctness gap rather than a current failure.

### 6.3 Allowed-VLAN trunk list respected for STP instance participation — **NOT CHECKED** (MED)

`_recalculate_instance_with_peers` does not verify that a trunk port's `trunk_allowed_vlans` permits the VLAN being calculated. If VLAN 10 is excluded from a trunk, the centralized algorithm still computes a port role for that VLAN on the trunk and may assign it FORWARDING. The forwarding path's `_port_carries_vlan` check would catch it at runtime, but the STP instance itself would show an incorrect role.

### 6.4 VLAN 1 and VLAN 10 root elections independent — **IMPLEMENTED** (OK)

The `BridgeID.sys_id_ext` difference (1 vs 10) produces different bridge IDs. With equal MAC and base priority, the bridge priority for VLAN 1 is `32768+1=32769` and for VLAN 10 is `32768+10=32778`, meaning the same switch would be elected differently if priorities differ. Test confirms independence.

---

## 7. Event Scheduling Safety Findings

### 7.1 Duplicate BPDU events from multiple `send_bpdus()` calls — **RISK** (MED)

`send_bpdus(tick=0)` can be called multiple times and will schedule duplicate `FrameTransmit` BPDU events at the same tick. There is no deduplication guard, no "in-flight" flag, and no check for existing BPDU events in the scheduler queue. Calling it N times multiplies the BPDU traffic N-fold. The `try/except` on scheduling (simulation.py:370–372) only catches `SimulationLimitError`, not duplicates.

### 7.2 Infinite event loop from BPDU-triggered recalculation — **NOT A RISK** (OK)

`_process_bpdu` calls `_trigger_stp()`, which calls `run_stp()`. `run_stp()` is bounded by `MAX_ITER=32` (simulation.py:183). No new events are scheduled inside `run_stp()` itself. The loop is safe.

### 7.3 After `reset()`, BPDU events cleared — **CORRECT** (OK)

`simulation.reset()` calls `self._scheduler.clear()` (simulation.py:135), which removes all pending events including any in-flight BPDU `FrameTransmit` events. `_stp_initialized` is set to False and `_init_devices()` runs `run_stp()` before re-enabling. No stale BPDU events survive a reset.

### 7.4 Convergence loop bounded — **CORRECT** (OK)

`run_stp()` runs at most `MAX_ITER=32` iterations (simulation.py:183). The snapshot-equality check provides early exit. This is correct and safe for educational topologies.

### 7.5 `run_stp()` called without a link does global election across disconnected switches — **ARCHITECTURAL NOTE** (LOW)

Without physical links, `_recalculate_instance_with_peers` still collects all bridge IDs from `all_switches` (stp.py:488–494) regardless of physical connectivity. This means two completely disconnected switches elect the same root bridge. Test B (test_stp_phase2.py:187) explicitly tests and accepts this behavior. This is a consequence of centralized calculation and would not occur in a real protocol.

---

## 8. Test Coverage Gaps

For each of the 10 scenarios in the audit brief:

| # | Scenario | Covered? | Would test fail if `_recalculate_instance_with_peers` removed? |
|---|----------|----------|--------------------------------------------------------------|
| 1 | BPDU-based root election WITHOUT centralized peer inspection | ❌ **Not covered** | No — TestBPDUExchangeFramePipeline.test_sw2_root_bridge_id_equals_sw1_bridge_id calls `run_stp()` before `send_bpdus()`, so root is already known. `_process_bpdu` overwrites with same value from `_trigger_stp`. |
| 2 | Periodic BPDU exchange | ❌ **Not covered** | N/A — no periodic mechanism exists |
| 3 | Neighbor information expiration (max-age) | ❌ **Not covered** | N/A — not implemented |
| 4 | Root bridge failure (device removed or all ports admin-down) | ⚠️ **Partial** | TestShutdownInterfaceCausesReelection covers interface shutdown; remove_link covered in TestReconvergenceAfterLinkFailure. Both go through centralized recalc only. |
| 5 | Root port failure and alternate path recovery | ⚠️ **Partial** | TestReconvergenceAfterLinkFailure covers this but via `remove_link` → centralized. |
| 6 | Five-switch chain convergence | ✅ Covered | TestFiveSwitchLinearConvergence covers root election. Would still pass without BPDU path. |
| 7 | Triangle topology without persistent forwarding loops | ✅ Covered | TestTriangleTopology + TestDiscardingPortBlocksFrames. Loops prevented by centralized calc. |
| 8 | VLAN 10 and VLAN 20 independent elections | ⚠️ **Partial** | TestVLANSeparation and TestVLANAwareBPDU cover VLAN 10; VLAN 20 is not explicitly tested. Independence verified structurally. |
| 9 | Reset while BPDU events are pending | ❌ **Not covered** | No test schedules BPDUs and then calls reset() |
| 10 | No MAC learning from BPDU frames | ✅ Covered | TestDiscardingPortBlocksFrames.test_no_mac_learned_via_discarding_port covers this indirectly. The BPDU bypass at switch.py:625 returns before the learn call. |

### Additional specific gaps

**Gap A — The "BPDU-only election" test cannot exist without architectural change:**  
To test that SW2 derives root info purely from received BPDUs, the test must either (a) prevent `_trigger_stp()` from firing after BPDU receipt, or (b) provide a topology where the centralized calculator would choose a different root than the BPDU. Currently both paths always agree because they use the same bridge ID data.

**Gap B — Egress trunk VLAN STP check bug (§5.4) has no test:**  
No test sends user traffic from VLAN 10 through a discarding trunk port and verifies the frame is dropped. All blocking tests use VLAN 1 access ports.

**Gap C — No test for `send_bpdus()` called twice → duplicate events:**  
No test calls `send_bpdus()` twice and checks for duplicate arrivals.

**Gap D — No test for VLAN 20 independent election:**  
Only VLAN 1 and VLAN 10 are tested. VLAN 20 is listed in the original brief but absent.

**Gap E — Backup port role never produced:**  
No test topology creates a scenario where two ports on the same switch connect to the same LAN segment, which is the only condition producing a BACKUP role.

---

## 9. Feature Matrix

| Feature | Status |
|---------|--------|
| Root bridge election (centralized) | ✅ Implemented |
| Root bridge election (BPDU-driven) | ❌ Not implemented |
| Designated port assignment | ✅ Implemented |
| Root port assignment | ✅ Implemented |
| Alternate port role | ✅ Implemented |
| Backup port role | ❌ Not implemented |
| EDGE / PortFast role | ✅ Implemented |
| FORWARDING state | ✅ Implemented |
| DISCARDING state | ✅ Implemented |
| BLOCKING state | ✅ Implemented |
| LEARNING state (timer-driven) | ❌ Not implemented |
| BPDU frame generation | ✅ Implemented |
| BPDU frame delivery (FrameTransmit → FrameArrival) | ✅ Implemented |
| BPDU receipt parsing (`_process_bpdu`) | ⚠️ Partial (overridden by centralized) |
| Periodic BPDU transmission (hello timer loop) | ❌ Not implemented |
| Message-age field (wire) | ⚠️ Partial (field present, never used) |
| Message-age increment per hop | ❌ Not implemented |
| Max-age expiry / neighbor failure detection | ❌ Not implemented |
| RSTP proposal/agreement | ❌ Not implemented |
| Topology change notification (TCN) | ❌ Not implemented |
| Topology change flag in BPDUs | ❌ Not implemented |
| Per-VLAN STP instances (PVST+) | ✅ Implemented |
| Independent per-VLAN root election | ✅ Implemented |
| Trunk allowed-VLAN respects STP instance | ⚠️ Partial (forwarding checked, STP role not filtered) |
| Egress STP check — access ports | ✅ Implemented |
| Egress STP check — trunk ports (correct VLAN) | ⚠️ Bug (uses native VLAN instead of frame VLAN) |
| Ingress STP check | ✅ Implemented |
| MAC learning blocked on discarding ports | ✅ Implemented |
| BPDU bypass discarding ports (ingress) | ✅ Implemented |
| Point-to-point detection (actual) | ❌ Not implemented (display only) |
| Duplicate BPDU event guard | ❌ Not implemented |
| Reset clears BPDU events | ✅ Implemented |
| Convergence loop bounded (MAX_ITER) | ✅ Implemented |
| BPDUGuard (flag stored) | ⚠️ Partial (flag stored, not enforced) |
| BPDUFilter (flag stored) | ⚠️ Partial (flag stored, not enforced) |
| Root Guard | ⚠️ Partial (flag stored, not enforced) |

---

## 10. Recommended Next Priorities (Ranked)

### Priority 1 — Fix the egress trunk VLAN STP check (MED effort, HIGH correctness impact)
**File:** `simulator_core/devices/switch.py`, `_forward()`, lines 708–712.  
The egress STP check for trunk ports must use the frame's actual VLAN, not the native VLAN. The frame VLAN is already correctly tracked in `handle_frame_arrival` and passed into `_forward` indirectly, but `_forward` re-derives it from the interface. Pass the VLAN ID explicitly into `_forward` or look it up from the frame context.

### Priority 2 — Implement periodic BPDU hello timer (HIGH effort, HIGH protocol fidelity)
**Files:** `simulation.py`, `stp.py`.  
Add a recurring event (e.g., `BPDUHelloEvent`) that fires every `hello_time` ticks on each switch. When processed, it calls `send_bpdus()` and schedules the next tick. This is prerequisite for max-age expiry (Priority 3). The event type must be added to the scheduler and registered in `_dispatch`.

### Priority 3 — Implement max-age expiry and neighbor failure detection (HIGH effort, HIGH fidelity)
**Files:** `stp.py` (`STPPortState`), `devices/switch.py` (`_process_bpdu`).  
Track `last_bpdu_tick` per port. On each BPDU hello event, check all ports: if `current_tick - last_bpdu_tick > max_age`, clear `best_bpdu` and trigger role recalculation. This enables the BPDU-driven convergence path and makes root failure detectable without explicit `remove_link()`.

### Priority 4 — Decouple BPDU-driven state from centralized override (HIGH effort, ARCHITECTURAL)
**File:** `devices/switch.py` (`_process_bpdu`), `simulation.py` (`run_stp`).  
`_process_bpdu` should update local instance state without calling `_trigger_stp()`. A separate converge pass using only received BPDU data (not global peer inspection) should replace `_recalculate_instance_with_peers` in the BPDU-driven path. `run_stp()` / `_recalculate_instance_with_peers` should remain only as a utility for topology-event-driven recalculation (link add/remove, priority change). This is the core architectural change that makes the simulation a protocol model rather than a calculator.

### Priority 5 — Add missing test coverage for identified gaps (MED effort)

In priority order:
1. Test that BPDUs drive root election when centralized recalculation is disabled (requires Priority 4 first).
2. Test: `send_bpdus()` called twice produces only one valid BPDU delivery per port (dedup guard).
3. Test: VLAN 10 and VLAN 20 independent elections (extend TestVLANSeparation).
4. Test: `reset()` with in-flight BPDU events produces clean state.
5. Test: Egress trunk port VLAN 10 discarding blocks VLAN 10 user frames (covers §5.4 bug).
6. Test: No MAC learned from BPDU frames (explicit BPDU-only scenario).

### Priority 6 — Implement LEARNING state timer (MED effort, educational value)
Ports transitioning to FORWARDING should pass through LEARNING for `forward_delay` ticks. This is noted as "deferred" in the codebase. It improves educational realism and is straightforward to add once hello timers are implemented.

### Priority 7 — Enforce BPDUGuard, BPDUFilter, Root Guard (LOW effort, feature completeness)
The flags are stored in `STPPortState` but checked nowhere. BPDUGuard should err-disable a portfast port on BPDU receipt. BPDUFilter should suppress BPDU transmission and processing. Root Guard should block superior BPDUs received on a guarded port.

### Priority 8 — Implement RSTP proposal/agreement (HIGH effort, advanced)
The BPDU flag fields exist. Full proposal/agreement requires tracking per-port handshake state and conditioning FORWARDING transitions on receiving an Agreement BPDU. This is an advanced feature appropriate after Priority 1–4 are complete.

---

## Appendix: Key Evidence Locations

| Claim | File | Lines |
|-------|------|-------|
| Centralized recalculation reads peer objects directly | stp.py | 488–494 |
| `_process_bpdu` overwrites state then calls `_trigger_stp` | switch.py | 601–608 |
| `run_stp` assembles all_stps from live objects | simulation.py | 187–188 |
| `send_bpdus` is one-shot, no reschedule | simulation.py | 299–372 |
| message_age always transmitted as 0 | simulation.py | 348 |
| message_age never read on receipt | switch.py | 560–609 |
| Trunk egress VLAN uses native VLAN for STP check | switch.py | 708–712 |
| Learning state acknowledged as not implemented | stp.py | 306 (docstring) |
| Backup port role never assigned | stp.py | 468–562 |
| MAX_ITER convergence bound | simulation.py | 183 |
| reset() clears scheduler | simulation.py | 135 |
| BPDU bypass before ingress STP check | switch.py | 625–628 |
| MAC learning only after forwarding check | switch.py | 642–649 |
