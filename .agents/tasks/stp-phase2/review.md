# STP Phase 2 Code Review

**Commits reviewed:** `77da506` (feat) and `1c39d19` (test + bug fix)  
**Diff range:** `HEAD~2..HEAD`  
**Recorded test results:** 405 passed (381 original + 24 new Phase 2 tests)

---

## Checklist Findings

### 1. `run_stp()` convergence loop

**PASS.**  
`simulation.py` replaces the fixed 2-pass loop with an iterative loop bounded at `MAX_ITER = 32`. The loop takes a snapshot before each pass with `_stp_snapshot()`, re-runs `recalculate()` over all switches in `sorted(self._switches)` order, then takes a second snapshot. It breaks on equality (`after == before`). The 32-iteration cap prevents infinite loops and is explicitly documented as sufficient for educational topologies.

`_stp_snapshot()` captures `root_bridge_id`, `root_path_cost`, `root_port_name`, and `{port: (role, state)}` per `(device_id, vlan_id)` pair — covers all state required by the spec. Iteration is over `sorted(self._switches.items())` making it deterministic and independent of dict insertion order.

### 2. `_trigger_stp` guard against pre-init calls

**PASS.**  
`_stp_initialized: bool = False` is set in `__init__` and in `_init_devices()` (line 390). It is set to `True` only after `run_stp()` completes at the end of `_init_devices()`. `_trigger_stp()` is a no-op until then. `reset()` also sets it `False` before re-calling `_init_devices()`, preserving the guard through replay.

### 3. `Simulation.add_link` / `remove_link` existence and `_trigger_stp` calls

**PASS.**  
Both methods are present in `simulation.py`. `add_link` calls `self._topology.add_link(link)` then `self._trigger_stp()`. `remove_link` calls `self._topology.remove_link(link_id)` then `self._trigger_stp()`. `Topology.remove_link(link_id)` is added in `topology.py` as a list-filter no-op-if-not-found.

### 4. `Switch._process_bpdu` updates root info from BPDU content

**PASS.**  
`_process_bpdu` (switch.py lines 547–609) reads all comparison values from the received `frame.bpdu_payload` (a `BPDU` dataclass). It never accesses another switch's `STPManager` directly. Root info update at line 594 uses `bpdu.root_bridge_id` and `bpdu.root_path_cost`. The centralized topology graph is not read inside this method.

**Minor note (not a blocker):** VLAN routing in `_process_bpdu` uses `bpdu.root_bridge_id.sys_id_ext or 1`. This is correct because `send_bpdus` builds BPDU frames where `root_bridge_id` is `inst.root_bridge_id`, and all BridgeIDs are created with `sys_id_ext=vlan_id`. The `or 1` fallback handles the edge case where `sys_id_ext == 0`.

### 5. `EthernetFrame.bpdu_payload` field

**PASS.**  
`frames.py` adds `bpdu_payload: Optional["BPDU"] = None` as a field with a default after the required fields. `payload` is changed to `Optional[EthernetPayload] = None`. Both fields now have defaults. The `ETHERTYPE_BPDU = 0x0027` sentinel and `STP_MULTICAST_MAC` constant are added as module-level and class-level values respectively. The `TYPE_CHECKING` guard on the `BPDU` import avoids a circular import at runtime.

**Note on frozen dataclass mutation:** `EthernetFrame` is `@dataclass(frozen=True)`. The `bpdu_tx` / `bpdu_rx` increments live on `STPPortState` (which is not frozen), not on `EthernetFrame`. No issue here.

### 6. `STPPortState.bpdu_tx` and `bpdu_rx` counters

**PASS.**  
`stp.py` lines 189–190 add `bpdu_tx: int = 0` and `bpdu_rx: int = 0` to `STPPortState` with zero defaults. `bpdu_tx` is incremented in `send_bpdus()` before scheduling the `FrameTransmit`. `bpdu_rx` is incremented inside `_process_bpdu` on the receiving switch.

### 7. `Switch._forward` STP state check for user frames

**PASS.**  
`_forward` (switch.py lines 700–715) adds a guard: when `frame.bpdu_payload is None` (i.e. a user frame), it resolves the VLAN from the egress interface and calls `self._stp.is_port_forwarding(egress_iface, vlan)`. BPDUs skip this guard. `_flood_in_vlan` also gates each candidate port with `is_port_forwarding(iface_name, vlan)` before calling `_forward`, using the correct VLAN derived from the ingress port.

**Non-blocking observation:** In `_forward`, trunk egress ports resolve VLAN as `iface.trunk_native_vlan`. This is correct for the ingress path (the calling code already tracked the VLAN through the `vlan` local variable), but the `_forward` egress check uses the native VLAN regardless of the frame's actual VLAN. For multi-VLAN trunk topologies this could permit a frame to exit through a port whose STP state for the actual payload VLAN differs from its native-VLAN state. This is a pre-existing architectural simplification (the simulator does not track per-frame VLAN tags) and not introduced by this change. `_flood_in_vlan` guards correctly with the right VLAN before calling `_forward`, so no regression is introduced. Noted but out of scope.

### 8. Test pass count

**PASS.**  
Commit `77da506` records `381/381 passed`. Commit `1c39d19` records `405 passed` (381 + 24 new). The original baseline of 381 is preserved and all new Phase 2 tests pass per the commit log. No re-run was performed per instructions; the evidence is the recorded commit messages.

### 9. No circular imports, no Django/socket/eval/shell

**PASS.**  
All new imports in the changed files are within `simulator_core.*` or Python standard library (`uuid`, `copy`, `random`). The `BPDU` import in `frames.py` is guarded by `TYPE_CHECKING`. Deferred imports inside method bodies (`from simulator_core.stp import ...`) are used consistently to break potential cycles. The existing `test_limits.py` test suite already asserts no forbidden imports across the package. No `django`, `socket`, `subprocess`, `eval`, or `exec` appears in any modified file.

### 10. Code stays within `simulator_core` package

**PASS.**  
All changed files are under `packages/simulator-core/simulator_core/` or `packages/simulator-core/tests/`. No cross-package contamination. No files outside `packages/simulator-core/` are modified.

---

## Summary

All ten checklist items pass. The two observations noted (BPDU VLAN routing fallback, trunk-port VLAN resolution in `_forward`) are either correct-by-design or pre-existing architectural simplifications not introduced by this change and carrying no test regression. No blockers remain.
