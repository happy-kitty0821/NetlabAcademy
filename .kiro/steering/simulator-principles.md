---
inclusion: fileMatch
fileMatchPattern: ["packages/simulator-core/**/*", "services/simulator/**/*", "packages/lab-schema/**/*"]
---
# Simulator engineering principles

- The simulator is a deterministic, educational, discrete-event model. It is not a real IOS/IOS XE/NX-OS runtime.
- The simulator must not use raw sockets, host network interfaces, shell execution, `eval`, dynamic code execution or arbitrary user scripts.
- All commands are parsed through an explicit allowlisted grammar and mapped to typed operations.
- Store device configuration as structured state; render CLI output from that state.
- Model packets, frames, interfaces, routes, MAC tables and events with explicit types.
- Use a logical clock, deterministic event ordering and seeded randomness.
- Bound nodes, edges, events, simulated time, trace size and runtime resources.
- A feature is not supported until its behaviour, limitations and acceptance tests are documented.
- Explain the difference between an unsupported feature and a packet dropped by a supported rule.
- Grade the resulting configuration and network behaviour, not just raw CLI text.
- Keep simulator core independent of Django models, database persistence and frontend code.
- Add positive, negative, boundary, deterministic replay and end-to-end topology tests for every protocol milestone.
