# STP Protocol Correctness Improvements — Phases 1–6

This commit replaces the centralized-inspector model with a genuine BPDU-driven STP simulation across six coordinated phases: fixing the trunk egress VLAN bug, decoupling `_process_bpdu` from peer-object inspection, adding a periodic hello timer, implementing message-age and max-age expiry, introducing timer-driven LEARNING state, and enforcing BPDUGuard/BPDUFilter/RootGuard. All 405 baseline tests pass and 33 new tests are added (438 total, 2.51 s). The commit message records these numbers directly.

Watch for: (1) **confirmed** — `_schedule_next_hello` reads the generation from `_hello_generation` instead of using the bumped generation passed from `start_hello_timers`, creating a window where duplicate chains can still form at the same tick; (2) **confirmed** — RootGuard runs *after* `recalculate_from_bpdus()` has already executed on a superior BPDU, meaning the per-port state may be briefly inconsistent before the guard clears it; (3) **confirmed** — `is_port_learning_or_forwarding` retains a stale docstring saying LEARNING is deferred, now that Phase 5 implements it; (4) **likely** — the inferior-first-BPDU guard in `_process_bpdu` holds back any first-received BPDU that is worse than centralized state, but this means a port that starts with no `best_bpdu` and receives an equal-to-current-root BPDU will store it, potentially creating asymmetric `best_bpdu` population across ports; (5) **confirmed** — `ROOT_INCONSISTENT` has no automatic clearing path in the production code — only the test manually resets the state.

**Verdict**: NEEDS_CHANGES

---

## High-level view

`_forward()` now takes `frame_vlan` as an explicit parameter, and all three call sites (known unicast, unknown unicast via `_flood_in_vlan`, flood) pass the VLAN from `handle_frame_arrival` context. The fallback to `iface.trunk_native_vlan` survives only when no `frame_vlan` is supplied, which only occurs on the BPDU path.

`_trigger_stp()` is removed from `_process_bpdu()` and replaced with `STPManager.recalculate_from_bpdus()`, a method that accepts only `self` and `inst` — no topology, no peer dict. The priority vector `(root_bid, root_path_cost, sender_bid, sender_port_id)` is correctly compared in strictly decreasing importance. `_recalculate_instance_with_peers` is preserved unchanged for the `run_stp()` / topology-event path.

`BPDUHelloEvent` carries a per-switch generation counter. `start_hello_timers()` is opt-in, correctly avoiding BPDU flood in existing unit tests. There is a confirmed generation-read bug in `_schedule_next_hello`: when called from `_handle_bpdu_hello` to reschedule the next hello, it re-reads the generation from the dict rather than using the validated generation from the event, creating a window where a topology-event bump can produce a second active chain.

RootGuard runs *after* `recalculate_from_bpdus()` already committed the superior root to `inst.root_bridge_id`. The guard clears `best_bpdu` and sets `ROOT_INCONSISTENT`, but does not revert the instance-level root update. The inconsistency persists until the next `_check_max_age_expiry` or hello cycle calls `recalculate_from_bpdus` again. Additionally, `ROOT_INCONSISTENT` has no automatic recovery path: `recalculate_from_bpdus` skips such ports, and `_check_max_age_expiry` does not reset them to DISCARDING when the superior BPDUs have aged out.

---

<details>
<summary>Issues (5)</summary>

1. **Generation read bug in `_schedule_next_hello`** — The method reads the current generation from `_hello_generation` rather than using the bumped generation that `start_hello_timers` just wrote. When called from `start_hello_timers`, `gen` in `_schedule_next_hello` is correctly the bumped value because `start_hello_timers` already wrote it before calling `_schedule_next_hello`. But when called recursively from `_handle_bpdu_hello`, the read is a no-op assign that works only because generation is not changed between calls. If a topology event bumps the generation between a hello firing and its reschedule, `_schedule_next_hello` would re-read the new (higher) generation and schedule a new event under it — creating a second active chain alongside the one still running from the previous `_handle_bpdu_hello` invocation for the original generation. The deduplication test (`test_calling_start_hello_timers_twice_does_not_create_duplicate_chains`) only tests the `start_hello_timers`-double-call path, not the topology-event-during-active-chain path. Pass the bumped generation into `_schedule_next_hello` as a parameter rather than re-reading it.

2. **RootGuard fires after `recalculate_from_bpdus` has already run** — In `_process_bpdu`, when `received_better=True`, `port_state.best_bpdu` is set and `recalculate_from_bpdus(inst)` runs before the RootGuard block. If the port carries a superior BPDU that triggers RootGuard, the instance's `root_bridge_id`, `root_path_cost`, and `root_port_name` have already been updated to reflect that superior root before the guard clears `best_bpdu` and sets `ROOT_INCONSISTENT`. The guard then clears `best_bpdu` but does not undo the instance-level root update. A subsequent `recalculate_from_bpdus` (e.g. from the next hello tick's max-age check) would re-derive root correctly from remaining best_bpdus, but during the window between the guard trip and the next recalculation the instance state is inconsistent. Move the RootGuard check to before `received_better` is accepted, or re-run `recalculate_from_bpdus` after clearing `best_bpdu`.

3. **`ROOT_INCONSISTENT` has no automatic recovery path in production code** — When superior BPDUs stop arriving (simulating the removal of the offending switch), max-age expiry clears `best_bpdu` via `_check_max_age_expiry`, but the port remains `ROOT_INCONSISTENT` through `recalculate_from_bpdus` because that function's loop skips ports in `ERR_DISABLED` or `ROOT_INCONSISTENT` state. The port is permanently stuck unless manually reset. The test `test_rootguard_clears_after_max_age_when_superior_bpdus_stop` works around this by manually setting `ps.state = PortState.DISCARDING` before calling `recalculate_from_bpdus` — that is not production behaviour. `_check_max_age_expiry` should clear `ROOT_INCONSISTENT` to `DISCARDING` when `best_bpdu` is None (no superior BPDU has been seen recently), allowing `recalculate_from_bpdus` to restore the port to DESIGNATED.

4. **Stale docstring in `is_port_learning_or_forwarding`** — The docstring still reads "timer-driven LEARNING state is not simulated" and "ports go directly to FORWARDING in the current educational model." Phase 5 now implements timer-driven LEARNING, so the docstring is actively misleading. Update it to describe the implemented behaviour.

5. **Phase 1 test `test_vlan10_blocked_when_trunk_discarding_for_vlan10` does not test `_forward()`** — The test asserts `not sw2_stp.is_port_forwarding("Gi0/0", 10)`, which only verifies that the port state was set to DISCARDING. It does not send a frame and verify it was dropped. The spec required verifying that `_forward()` uses `frame_vlan` rather than `trunk_native_vlan`. `test_vlan10_not_permitted_because_vlan1_forwarding` does call `_forward()` directly with `frame_vlan=10` and checks the trace — that test is adequate. The first test is redundant and confusingly named. This is advisory (the actual bug fix is correct and the second test is real), but the test name implies a forwarding check that is absent.

</details>

<details>
<summary>Details</summary>

## Generation-counter read in `_schedule_next_hello`

`start_hello_timers` bumps the generation in `_hello_generation[dev_id]` and then calls `_schedule_next_hello`. Inside `_schedule_next_hello`, the code does:

```python
gen = self._hello_generation.get(device_id, 0)
self._hello_generation[device_id] = gen
```

The assign-back is a no-op. When called from `start_hello_timers` this is fine because the bumped value is already in the dict. But when called from `_handle_bpdu_hello` to reschedule the next hello, if something (a topology event, a concurrent `start_hello_timers`) has incremented the generation between firing and rescheduling, `_schedule_next_hello` reads the *new* generation and schedules under it. Now there are two chains: the original handler's chain (which will fire one more time before it notices the generation mismatch) and the new chain just scheduled. This is a narrow window in the discrete-event model but is structurally present. The fix is to pass `gen` as a parameter from `_handle_bpdu_hello` to `_schedule_next_hello`, using the generation the handler already validated.

## RootGuard / `recalculate_from_bpdus` ordering

The sequence in `_process_bpdu` for a guarded port receiving a superior BPDU is:

1. `received_better = True` (superior BPDU beats current_best)
2. `port_state.best_bpdu = bpdu`
3. `recalculate_from_bpdus(inst)` — updates `inst.root_bridge_id` to the superior root
4. RootGuard block — clears `best_bpdu`, sets `ROOT_INCONSISTENT`

After step 4, `inst.root_bridge_id` has been set to the attacker's root by step 3 and is not reverted. A subsequent periodic max-age check that calls `recalculate_from_bpdus` will find no remaining `best_bpdu` on the guarded port and will re-elect the local bridge as root, restoring correct state. The inconsistency window is bounded by the next `_check_max_age_expiry` or hello cycle, but during that window `inst.root_bridge_id` reflects the wrong root.

## `ROOT_INCONSISTENT` clearance

`recalculate_from_bpdus` protects `ERR_DISABLED` and `ROOT_INCONSISTENT` ports from role reassignment with an explicit `continue`. This prevents the guard state from being overwritten — which is correct for `ERR_DISABLED` (manual recovery only). For `ROOT_INCONSISTENT`, the IEEE intent is that the port returns to normal when the offending superior BPDUs stop arriving (after `max_age` silence). The current code has no path that transitions `ROOT_INCONSISTENT → DISCARDING` automatically. The test for this scenario manually patches `ps.state = PortState.DISCARDING` to simulate the recovery, confirming the production path does not exist. `_check_max_age_expiry` is the correct place to add: if a `ROOT_INCONSISTENT` port has `best_bpdu is None` (already cleared by the guard on receipt) and `last_bpdu_tick` is stale, reset it to `DISCARDING`.

## Phase 1 test coverage gap

`test_vlan10_blocked_when_trunk_discarding_for_vlan10` only checks `is_port_forwarding` returns False, which was already true before this commit (the state is manually forced to DISCARDING in `_setup`). The fix being tested — that `_forward()` uses `frame_vlan` rather than re-deriving the VLAN from the interface — is actually tested by `test_vlan10_not_permitted_because_vlan1_forwarding`, which calls `_forward()` directly and inspects the trace. The first test's name implies it verifies the forwarding gate but it does not.

## Test coverage — what's not tested

The test for duplicate-chain prevention (`test_calling_start_hello_timers_twice_does_not_create_duplicate_chains`) relaxes the assertion: it allows duplicate events at the first tick and only checks uniqueness after. This is a reasonable accommodation for the scheduling model but means the first-tick duplicate is accepted. More critically, no test covers the topology-event-during-active-chain scenario described in Issues item 1. The `test_reset_stops_old_hello_chain` assertion (`gen_after > gen_before or gen_after != gen_before`) is a tautology — `>` and `!=` together cover all non-equal cases, so it always passes as long as the generation changes at all.

</details>

---

<details>
<summary>File map</summary>

| File | What changed |
|------|-------------|
| `simulator_core/devices/switch.py` | Phase 1: `_forward()` gains `frame_vlan` param; all call sites updated. Phase 2: `_process_bpdu()` removes `_trigger_stp()`, adds priority-vector comparison, calls `recalculate_from_bpdus`. Phase 5: `handle_frame_arrival` learns MACs in LEARNING state. Phase 6: BPDUFilter, BPDUGuard, RootGuard enforced inline. |
| `simulator_core/events.py` | Adds `BPDUHelloEvent` (device_id, generation) and `ForwardDelayEvent` (device_id, interface_name, vlan_id, generation). Both registered in `EVENT_REGISTRY`. |
| `simulator_core/simulation.py` | Adds `_hello_generation` dict; `start_hello_timers()`, `_schedule_next_hello()`, `_handle_bpdu_hello()`, `_send_bpdus_for_switch()`, `_check_max_age_expiry()`, `schedule_forward_delay()`, `_handle_forward_delay()`. Phase 4: `send_bpdus()` sets `message_age` from `best_bpdu`. `reset()` increments all existing generations. |
| `simulator_core/stp.py` | Adds `PortState.ERR_DISABLED`, `PortState.ROOT_INCONSISTENT`; `STPPortState.last_bpdu_tick`; `STPManager.recalculate_from_bpdus()`; updates `is_blocking` and display abbreviations. |
| `tests/test_stp_correctness.py` | New file: 33 tests across Phases 1–6. |

Full diff: `git diff HEAD~1 HEAD`

</details>
