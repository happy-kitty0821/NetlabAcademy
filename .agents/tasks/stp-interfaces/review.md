# Database-driven device interfaces, STP port registration, and protocol consistency

This commit wires the device catalog from both ends of the stack: a backend `INTERFACE_CATALOG` dict in the simulation adapter generates interface lists deterministically from a `catalogId`, the frontend `DEFAULT_DEVICE_CATALOG` gains a matching `InterfaceTemplate` per entry, and `convertFlowToTopology` uses those templates when building topology payloads. On the simulator side, `Switch.__init__` now calls `_register_stp_ports()` so every physical interface is in `port_states` from the first tick, and the protocol string in `_format_instance` changes from `"RST"` to `"rapid-pvst"`. Thirty new tests cover the happy paths across both packages.

Watch for:
- **confirmed** — `hash(node_id + iface_name)` produces different integers across Python process restarts (PYTHONHASHSEED randomisation). The MAC-seed determinism test only calls the function twice inside the same process, so it passes without catching this.
- **confirmed** — `create_vlan` → `ensure_vlan` creates a fresh `STPInstance` with an empty `port_states`. Ports registered at init time are never copied into later VLAN instances. The test for this (`test_access_port_in_different_vlan_registered`) only asserts `inst10 is not None` and silently passes.
- **confirmed** — `_register_stp_ports` calls `_stp._get_or_create_port` (a private method) directly from application code in `switch.py`.

**Verdict**: NEEDS_CHANGES

---

## High-level view

The catalog lookup chain is architecturally sound. The `INTERFACE_CATALOG` on the backend and `DEFAULT_DEVICE_CATALOG` on the frontend are parallel plain-Python / plain-TypeScript structures with matching keys, so there is no DB round-trip in the hot path and backward compatibility is preserved by a simple `catalogId not in INTERFACE_CATALOG` guard. The catalog entries themselves (counts, prefixes, speeds, STP costs) match the task specification.

The `_register_stp_ports` fix is the right place and the right moment — called at the tail of `__init__` after `ensure_vlan(1)` has already run — so every new `Switch` instance arrives with a fully populated VLAN 1 `port_states`. The `register_interface_with_stp` public method provides a correct hook for dynamic additions. Both ship with thorough positive tests.

The MAC seed for catalog-generated interfaces is computed with Python's built-in `hash()`. Because CPython randomises string hashing on every interpreter startup by default, two separate API calls to the same lab will produce different MAC addresses, breaking address stability for ARP, MAC-table lookups, and topology replay. The determinism test does not catch this because both calls share the same process and therefore the same PYTHONHASHSEED.

When `Switch.create_vlan` creates a new VLAN instance after init, `_get_or_create_instance` returns a fresh `STPInstance` with an empty `port_states` dict — existing physical interfaces are never copied in. `show spanning-tree vlan 10` on a switch with ten physical ports will display an empty interface table. The test that was written to cover this (`test_access_port_in_different_vlan_registered`) only asserts the instance exists, not that it contains any ports, so the gap passed the test suite undetected.

The protocol string fix (`"RST"` → `"rapid-pvst"`) is a one-liner with positive and regression test coverage; no concerns there.

---

<details>
<summary>Issues (3)</summary>

1. **Non-deterministic MAC seeds across process restarts** — `hash(node_id + iface_name) % (2**31)` in `_generate_interfaces_from_catalog` relies on Python's randomised string hashing. Replace with a stable hash: `int(hashlib.md5((node_id + iface_name).encode()).hexdigest(), 16) % (2**31)`. The determinism test must also be updated to call the function in a subprocess (or directly compare the hash function's output) to catch cross-process divergence.

2. **New VLAN instances start with empty port_states** — `create_vlan` → `ensure_vlan` → `_get_or_create_instance` creates a bare `STPInstance`. Physical interfaces registered at init are not propagated. Fix: in `_get_or_create_instance`, when a new instance is created, populate `port_states` by copying registered ports from the VLAN 1 instance (or by iterating `_device.interfaces` if the manager holds a reference to it). `test_access_port_in_different_vlan_registered` must be strengthened to assert `"Gi0/0" in inst10.port_states` and `"Gi0/1" in inst10.port_states`.

3. **Private STP API called from application code** — `_register_stp_ports` calls `self._stp._get_or_create_port(inst, iface_name)` directly. `_get_or_create_port` is a private method on `STPManager`. Promote it to a public `register_port(inst, iface_name)` method, or expose a single `register_physical_interfaces(iface_names)` method on `STPManager` that handles the full registration loop internally, keeping the port-state creation logic inside `STPManager`.

</details>

---

<details>
<summary>Details</summary>

## MAC seed instability across process restarts

`_generate_interfaces_from_catalog` computes `mac_seed = hash(node_id + iface_name) % (2**31)`. CPython enables hash randomisation by default (`PYTHONHASHSEED=random`), so the same `("sw1", "Fa0/0")` input produces a different integer on every interpreter startup. `MACAddress.generate(random.Random(mac_seed))` then produces a different MAC on every server restart.

The consequence is concrete: a lab topology saved on Monday and re-opened on Tuesday gets different MAC addresses on its switches. ARP caches, MAC table entries saved between sessions, and any test that snapshots a MAC address will silently diverge.

`test_cisco2960_mac_seeds_are_deterministic` calls `build_topology_from_document(doc)` twice in the same test method. Both calls share the process's PYTHONHASHSEED, so `hash()` returns the same integer both times and the test passes. It does not test across-process stability. The fix is a stable hash function; `hashlib.md5` or `hashlib.sha256` truncated to 31 bits is the standard approach.

The fallback path in `build_topology_from_document` (non-catalog interfaces) also uses `hash(iface_name) % 1000` for the same reason, but that was pre-existing and is out of scope for this review.

## New VLAN instances inherit no ports from init-time registration

`_get_or_create_instance` in `STPManager`:

```python
inst = STPInstance(
    vlan_id=vlan_id,
    ...
)
self._instances[vlan_id] = inst   # port_states == {}
return inst
```

There is no code that copies the ports registered during `_register_stp_ports` into the new instance. `show spanning-tree vlan 10` immediately after `create_vlan 10` returns an empty interface table, which is the original bug being fixed for VLAN 1.

The test `test_access_port_in_different_vlan_registered` documents the _intent_ in its docstring ("VLAN 10's port_states (created later)") but only checks:

```python
inst10 = switch.stp.get_instance(10)
assert inst10 is not None
```

This assertion is satisfied by an empty instance. The test passes today despite the gap.

The `register_interface_with_stp` path correctly iterates `self._stp.all_instances()` and registers the new port in every existing VLAN instance. The gap only affects the initial `_register_stp_ports` call — it runs before any secondary VLAN exists, so it only populates VLAN 1.

## Private API boundary between Switch and STPManager

`_register_stp_ports` reaches through `self._stp._get_or_create_port(inst, iface_name)`. Port-state creation logic (auto-detecting STP cost from port type, initialising the `PortID`, setting `FORWARDING`/`DESIGNATED` defaults) lives inside `_get_or_create_port`. Calling it from outside `STPManager` creates an implicit coupling: if `_get_or_create_port`'s signature or semantics change, `switch.py` silently breaks.

The `register_interface_with_stp` public method has the same call. Both could be replaced by a single `STPManager.register_port(iface_name, priority, path_cost)` method that keeps all port-state construction inside `STPManager`.

## Test coverage shape

The 15 simulator-core tests cover the right territory: port registration on init, SVI exclusion, stable port IDs, protocol string in both `show spanning-tree` and `show spanning-tree summary`, PVST mode regression, access and trunk ports in `port_states`, and root-bridge forwarding state. The 15 adapter tests cover the cisco-2960 count/speed/cost/names/IP-preservation/determinism, fallback for unknown and absent `catalogId`, cisco-2911, and all three endpoint types.

Not tested:
- `show spanning-tree vlan <N>` where N > 1 after `create_vlan` (would expose the empty-port-states gap).
- Cross-process MAC determinism (would expose the `hash()` instability).
- A topology document that has both `catalogId` and a non-empty `interfaces` list with more than one entry — only the first entry's IP/gateway is preserved; the rest are silently dropped. This is by design but no test documents the drop behavior.
- `register_interface_with_stp` called on an interface that already exists in some VLAN instances but not others (partial registration state).

</details>

---

<details>
<summary>File map</summary>

| File | What changed |
|---|---|
| `services/api/apps/labs/services/simulation_adapter.py` | Added `INTERFACE_CATALOG` dict and `_generate_interfaces_from_catalog`; `build_topology_from_document` resolves interfaces from catalog when `catalogId` is present |
| `services/api/apps/labs/serializers.py` | Added optional `catalogId` field to `NodeSpecSerializer` |
| `packages/simulator-core/simulator_core/devices/switch.py` | Added `_register_stp_ports()` called from `__init__`; added `register_interface_with_stp()` public method |
| `packages/simulator-core/simulator_core/stp.py` | Fixed protocol name mapping: `RAPID_PVST → "rapid-pvst"`, `PVST → "pvst"`, `MST → "mst"` |
| `apps/web/src/lib/deviceTypes.ts` | Added `InterfaceTemplate` interface; added `interfaceTemplate` field to all five catalog entries |
| `apps/web/src/lib/convertFlowToTopology.ts` | Added `resolvePortName` and `generateInterfacesFromTemplate` helpers; all node outputs now include `catalogId` and use template-derived interface names |
| `apps/web/src/lib/simulation-api.ts` | Added optional `catalogId` to `TopologyNode` type |
| `packages/simulator-core/tests/test_stp_port_registration.py` | New: 15 tests for port registration, protocol strings, summary counts, access ports, root-bridge forwarding |
| `services/api/apps/labs/tests/test_simulation_adapter_catalog.py` | New: 15 Django tests for catalog-driven interface generation, fallback, IP preservation, determinism |
| `services/api/apps/labs/tests/__init__.py` | New empty file making the tests directory a Python package |

Full diff: `git diff HEAD~1..HEAD` in `c:\Users\User\Documents\NetlabAcademy`

</details>
