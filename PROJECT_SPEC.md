# NetLab Academy — Product & Technical Project Specification

**Document status:** Draft v1.0 — product and architecture baseline  
**Working product name:** NetLab Academy (provisional; rename before public launch)  
**Product type:** Web-based networking education, assessment and software-simulation platform  
**Primary audience:** CCNA and CCNP learners, networking instructors and training administrators  
**Development environment:** Kiro agentic IDE using spec-driven development  
**Initial implementation approach:** Modular monolith for the education platform + separately executable simulation runtime  

> This document is the long-term product baseline. It is not an instruction to implement every feature in one pass. Build the product in small, reviewed, testable feature specifications. Do not begin implementation until the relevant feature requirements, design and tasks are reviewed.

---

## 1. Product vision

Build an independent, browser-based networking education platform that combines:

1. A Boson ExSim-inspired examination and question-bank experience.
2. A Packet Tracer-inspired visual network topology workspace.
3. An original software network simulator that models selected networking protocols and device behaviour.
4. Learning management, instructor workflows, student records and performance analytics.

The platform should let an administrator or instructor publish courses, assessments and practical labs. Students should be able to study, take examinations, launch assigned labs, configure simulated devices, troubleshoot networks, receive feedback, track progress and create private practice topologies of their own.

The product will initially focus on Cisco-oriented CCNA learning outcomes and then expand into CCNP-level scenarios. It must remain architecturally capable of supporting other vendors and general networking topics later.

### 1.1 Product positioning

This is an independent educational platform. It may implement a documented, limited Cisco-style educational command-line interface, but it will **not** claim to run Cisco IOS or to be an exact Cisco Packet Tracer replacement. The initial simulator will model device behaviour in software; it will not boot or execute proprietary router/switch operating-system images.

Use original content or content for which the platform has permission. Do not copy Boson exam questions, Cisco proprietary content, Packet Tracer assets, device images or product branding. Do not imply endorsement or affiliation with Cisco, Boson or another vendor.

### 1.2 Product principles

- **Learning first:** Every feature should support a measurable learning outcome.
- **Correctness over breadth:** A small set of accurately modelled protocols is better than a large set of inaccurate protocol labels.
- **Simulation is deterministic:** A lab attempt must be reproducible from its lab version, configuration and random seed.
- **Keep authoring separate from execution:** Published lab definitions are versioned and immutable; each learner receives an isolated runtime instance.
- **Assess behaviour, not command strings:** Grade the resulting configuration and network behaviour, not merely whether a student typed a particular sequence of commands.
- **Secure by default:** Student-created topologies and CLI input must never execute arbitrary host commands or gain access to the host network.
- **Modular, not prematurely distributed:** Start with a modular Django application and a clearly separated simulator runtime. Do not introduce many microservices without demonstrated need.
- **Engine portability:** The education platform must communicate with a simulator through an adapter contract so another engine could be added later.
- **Human-reviewed content:** AI may help draft questions, explanations or lab instructions, but an authorized instructor/admin must review and publish them.

---

## 2. Goals and non-goals

### 2.1 Goals

The platform shall:

- Provide role-based accounts for administrators, instructors and students.
- Support courses, cohorts/classes, enrolment and assignments.
- Provide a versioned question bank and randomized practice exams.
- Support timed examinations, answer review, explanations and topic-level results.
- Provide a visual topology editor for creating network labs.
- Provide a software simulation engine for a carefully defined subset of networking behaviour.
- Implement an educational Cisco-style CLI with documented supported commands and predictable errors for unsupported commands.
- Allow admins/instructors to create, version, publish, assign and grade labs.
- Allow students to create, save, duplicate, reset and privately manage personal labs.
- Evaluate labs using configurable, machine-readable rubrics.
- Maintain student activity, attempts, scores and progress history.
- Support future CCNP content without redesigning the platform's core data model.
- Provide audit logs, secure access controls, backups and operational observability.

### 2.2 Non-goals for the first major release

The first release will not:

- Reimplement every feature of Cisco Packet Tracer.
- Execute real Cisco IOS, IOS XE, NX-OS or proprietary switch firmware.
- Guarantee bit-for-bit protocol conformance for every RFC or every vendor implementation.
- Run arbitrary student-provided Python, shell scripts, binaries or plugins inside the simulator.
- Provide unrestricted access from simulated networks to the public internet or the college LAN.
- Include real hardware appliances, serial/console cables or physical-device control.
- Include video conferencing, payments, marketplace functionality or mobile native apps.
- Use AI-generated answers as the sole source of truth for automated grading.
- Launch a multi-institution SaaS tenancy model until single-institution workflows and authorization boundaries are stable.

These may be considered later through separate approved feature specs.

---

## 3. Users, roles and permissions

Implement role-based access control (RBAC). A user's role must be enforced on the backend for every protected API and object, not only hidden in the frontend.

### 3.1 Roles

**Platform administrator**
- Manage users, roles, account status and platform settings.
- Create and manage courses, question categories and lab catalogues.
- Review platform activity, audit logs and system health.
- Publish, archive or withdraw content.
- View reports across the platform.
- Manage simulator capacity limits and global policies.

**Instructor**
- Create and manage assigned courses/classes.
- Enrol or invite students where permitted by administrator policy.
- Create, edit, preview and publish questions and examinations within permitted courses.
- Create, version, preview and publish lab assignments.
- Set due dates, time limits, attempt limits and grading rules.
- Review submissions, override a grade with a recorded reason, and provide feedback.
- View performance reports for their own classes only.
- Share instructor-created labs with selected classes or make them available in an approved catalogue.

**Student**
- View and enrol in courses according to course policy.
- Take available practice examinations and assigned assessments.
- Launch assigned labs and work within their isolated lab instances.
- Create, edit, save, duplicate, reset and delete personal labs.
- View their own history, scores, feedback and progress.
- Share a personal lab only through an explicit supported sharing action.
- Never view another student's private lab, answer key, hidden rubric or private records.

### 3.2 Permission rules

- Apply least privilege and deny access by default.
- A student must not be able to publish catalogue content or change a published instructor lab.
- A published lab/question version must not be silently mutated. Edits create a new draft/version.
- Students may only access their own records and resources plus resources explicitly shared with them or their class.
- Instructor access is limited to courses/classes they manage unless an administrator grants broader scope.
- Administrative overrides must be audited.
- Use Django permissions plus object-level authorization checks. Do not rely solely on frontend route guards.

---

## 4. Functional product requirements

### 4.1 Authentication and profile management

- Secure login/logout and password reset.
- Email verification when email delivery is configured.
- Optional future MFA; design authentication so MFA can be added.
- User profile with name, email, avatar (optional), timezone and learning preferences.
- Account status: invited, active, suspended and archived.
- Session management and rate limits for authentication endpoints.
- Administrator-managed invitations and role changes.

### 4.2 Course and class management

- Courses have title, code, description, level (CCNA/CCNP/general), status and owner.
- A course contains modules/topics and may reference questions, exams and labs.
- Instructors can create class/cohort instances for a course.
- Students can be enrolled in one or more classes.
- Class membership has active/withdrawn/completed states.
- Assignments reference an immutable exam or lab version and contain availability window, deadline, attempt policy and grading policy.
- Course progress is derived from completed learning activities; it must not be represented by a manually editable percentage alone.

### 4.3 Question bank

Support the following question types through a versioned question schema:

1. Single-answer multiple choice.
2. Multiple-select.
3. True/false.
4. Matching.
5. Ordered sequence.
6. Drag-and-drop classification or placement.
7. Fill-in-the-blank with normalized accepted answers.
8. Numeric answer with tolerance and units where relevant.
9. Subnetting/IP addressing problem with generated parameters and deterministic answer validation.
10. CLI output interpretation.
11. Configuration/troubleshooting scenario linked to a lab or simulated device state (later phase).

Each question should support:
- Stable ID and version.
- Title/prompt, question type and topic tags.
- CCNA/CCNP level and difficulty label.
- Points, estimated time and optional references.
- Answer key and grading strategy, hidden from students.
- Explanation shown according to exam mode/settings.
- Status: draft, review, published, archived.
- Author, reviewer and timestamps.
- Media attachments with safe file validation.

Do not store the correct answer in student-facing API responses. Randomized question generation must store the generation seed and parameter snapshot with each attempt so the assessment can be reproduced.

### 4.4 Examination engine

Modes:
- **Study mode:** Immediate feedback and explanation where enabled.
- **Practice exam:** Timed or untimed configurable practice with a review at the end.
- **Assignment/exam mode:** Instructor-controlled availability, time limit, attempt count and feedback release.

Capabilities:
- Build exams from fixed questions or topic/difficulty blueprints.
- Randomize question order and answer order without changing answer semantics.
- Support save/resume according to assessment policy.
- Autosave responses and record timestamps.
- Handle time expiration consistently on the server.
- Submit and calculate a score using versioned grading logic.
- Provide a review screen with correct/incorrect status, explanations and topic tags according to release policy.
- Record attempts, duration, score, question-level response and exam version.
- Detect and record suspicious technical events (for example repeated reconnects) without making unsupported claims of cheating.
- Keep a complete audit trail for instructor grade changes.

### 4.5 Student records and analytics

Record at minimum:
- Course enrolments and status.
- Exam attempts, scores and durations.
- Question-level outcomes and topic-level performance.
- Lab launches, completion state, submissions and scores.
- Instructor feedback and grade overrides.
- Last activity and completion dates.

Dashboards should show:
- Student: current courses, upcoming work, recent activity, exam performance, lab progress and weak topics.
- Instructor: class completion, score distributions, common misconceptions, overdue work and student-level detail.
- Administrator: user totals, active courses, published content, usage and system-level health.

Reports must respect RBAC and support CSV export for authorized roles. Do not expose answer keys, hidden rubrics or other students' private records in exports.

---

## 5. Lab Studio and topology editor

### 5.1 Workspace experience

Provide a browser-based topology workspace with:
- Palette of supported simulated devices.
- Canvas with pan, zoom, select, move, multi-select and delete.
- Link creation between compatible interfaces.
- Device and interface labels.
- Context menus and property panels.
- Device CLI terminal.
- Run, pause, step, stop and reset controls.
- Event/packet inspection panel.
- Save, duplicate, import and export of the platform's own lab format.
- Undo/redo for topology editing.

Use a graph representation with stable IDs for devices, ports and links. The frontend visual graph is not the source of truth; the backend validates and stores a canonical topology document.

### 5.2 Device models for initial release

Initial device types:
- PC/end host.
- Generic server.
- Ethernet switch (educational model).
- IPv4 router (educational model).

Later device types may include wireless access point, firewall, multilayer switch, cloud/network service node and additional router/switch capability profiles.

Do not name an educational model in a way that falsely implies it runs a real Cisco hardware platform. Device labels may offer familiar teaching examples, but the device model and supported feature profile must remain explicit.

### 5.3 Lab lifecycle

A lab definition has:
- Owner and visibility.
- Draft/published/archived state.
- Version number.
- Topology document.
- Device initial configurations.
- Supported feature profile and simulator version requirement.
- Instructions, objectives and completion criteria.
- Optional time limit and resource budget.
- Optional grading rubric.

Publishing creates an immutable version. When an instructor edits a published lab, the system creates a new draft version. Existing student attempts stay tied to the original version.

A learner lab instance has:
- Student/owner.
- Lab definition and exact published version (or personal lab revision).
- Unique runtime ID.
- Simulator version.
- State: queued, starting, running, paused, stopped, submitted, completed, failed or expired.
- Start/last-activity/end timestamps.
- Snapshot/checkpoint references where supported.
- Attempt number and resource usage summary.

### 5.4 Personal labs

Students can create and save their own labs independently from assigned labs. Personal labs are private by default. Students may duplicate an instructor template into their own workspace without modifying the original. Students must not be able to change the source published lab by editing their copy.

### 5.5 Lab file format

Create a versioned, documented JSON schema for topology and lab definitions. Requirements:
- Schema version field.
- Stable node, interface and edge IDs.
- Explicit device model and feature profile.
- Initial configuration stored as structured data plus optional CLI text where needed.
- Link properties such as type, state, bandwidth/delay (only when modelled), and VLAN tagging mode where relevant.
- No executable scripts, shell commands or arbitrary code.
- Strict validation, size limits and resource limits before runtime creation.
- Import must validate and report errors; never trust uploaded JSON.

---

## 6. Original network simulation engine

### 6.1 Engine objective

Implement an educational, deterministic, discrete-event network simulator. It models a documented subset of Ethernet and IP networking. It does not execute real vendor firmware and does not send simulated packets onto real host interfaces.

The engine should be a separate Python package/service with a stable internal API. Keep it independent of Django ORM models and browser-specific code.

### 6.2 Simulation model

Use a discrete-event simulation loop with:
- A logical simulation clock.
- A priority queue of scheduled events.
- A deterministic ordering rule for events with the same logical timestamp.
- A seeded random source where randomness is needed.
- Explicit event types and typed payloads.
- Pause, resume, single-step and reset support.
- A bounded event queue, packet TTL/hop limit and per-lab resource budgets to prevent runaway simulations.

The engine should be deterministic: identical topology, initial state, simulator version, inputs and seed should produce the same observable outcome. Tests must verify this property.

### 6.3 Core domain objects

- `Simulation`: runtime context, clock, event queue, seed and lifecycle.
- `Topology`: nodes and links.
- `Device`: common identity, model, hostname, interfaces, state and supported capabilities.
- `Interface`: name, MAC address, admin/operational state, IP configuration, VLAN mode and counters.
- `EthernetFrame`: source/destination MAC, VLAN metadata, payload and frame metadata.
- `IPv4Packet`: source/destination IP, protocol, TTL and payload.
- `ARPMessage`: request/reply and address mapping fields.
- `ICMPMessage`: echo request/reply and error types as supported.
- `RouteEntry`: prefix, next hop, outgoing interface, source/protocol and metric.
- `MacTableEntry`: MAC, VLAN, learned interface and aging timestamp.
- `ProtocolProcess`: protocol-specific state (for example OSPF neighbor/LSDB state in a later phase).
- `SimulationEvent`: typed event with timestamp, source, destination and inspectable metadata.

Use explicit types and validation. Avoid a single untyped dictionary as the internal representation of every network object.

### 6.4 Data-plane behaviour

Initial implementation stages:

**Stage A — basic Ethernet and hosts**
- Point-to-point Ethernet links.
- Interface up/down state.
- MAC address generation and validation.
- Ethernet frame delivery.
- PC/server IPv4 addressing.
- ARP request/reply and ARP cache.
- ICMP echo request/reply.
- Basic ping result and packet-event trace.

**Stage B — switching**
- MAC address learning and aging.
- Known unicast forwarding.
- Unknown unicast flooding within the correct broadcast domain.
- Broadcast handling.
- Access ports and VLAN membership.
- 802.1Q trunk tagging/untagging in the educational model.
- VLAN isolation and allowed-VLAN checks.

**Stage C — routing**
- Router interfaces and connected routes.
- Local routes.
- Static routes and default routes.
- Longest-prefix-match route selection.
- TTL decrement and expiry handling.
- ARP resolution on egress networks.
- Inter-VLAN routing using subinterfaces/router-on-a-stick.
- ICMP unreachable/time-exceeded outcomes where implemented.

**Stage D — routing protocols and advanced behaviour**
- Single-area OSPFv2 educational model, including neighbor state, adjacency requirements, LSDB and route installation. Document simplifications and unsupported areas.
- Additional OSPF capabilities and multi-area scenarios only after single-area correctness tests pass.
- ACL processing with clearly specified evaluation order and implicit behaviour.
- NAT/PAT model.
- DHCP server/relay model.
- IPv6 neighbour discovery and IPv6 forwarding.
- STP/RSTP and EtherChannel in later switching milestones.
- EIGRP/BGP and advanced CCNP topics only through separate protocol specs with protocol-specific state machines and conformance tests.

Do not mark a feature as supported until its behaviour and limitations are documented and tested.

### 6.5 Control-plane and CLI model

Implement a documented educational Cisco-style CLI grammar. The CLI is a command parser and configuration interface; it is not an IOS shell.

Initial CLI modes:
- User EXEC.
- Privileged EXEC.
- Global configuration.
- Interface configuration.
- Later: router-protocol configuration and line configuration.

Initial command families should be selected and frozen in a command-support matrix. Suggested examples:
- `enable`, `disable`, `configure terminal`, `hostname`.
- `interface`, `ip address`, `no shutdown`, `shutdown`, `description`.
- `show running-config`, `show ip interface brief`, `show interfaces`.
- `show ip route`, `show arp`, `show mac address-table`.
- `show vlan brief`, `switchport mode`, `switchport access vlan`, `switchport trunk allowed vlan`.
- `ip route` and `ping`, with `traceroute` after forwarding and TTL logic are available.

Requirements:
- Parse commands into structured operations; do not use `eval`, shell execution or dynamic code execution.
- Validate mode, argument count, address syntax, interface existence and supported features.
- Return educationally useful syntax and mode errors.
- Support command help and command completion only where the grammar is defined.
- Provide a clear message for unsupported commands; never silently pretend an unimplemented command worked.
- Store running configuration as structured state. Render CLI output from state rather than using terminal text as the canonical configuration.
- Configuration changes must trigger the appropriate recomputation/events (for example interface state change, route update or protocol transition).

### 6.6 Real-time and step simulation modes

- **Realtime:** advance logical time automatically and stream events to the UI.
- **Step mode:** user advances one event or one bounded event group at a time.
- **Pause/resume:** preserve current event queue and device state.
- **Reset:** restore the exact initial lab state and seed.
- **Trace:** users can inspect packet/event path, ingress/egress interface, decision and drop reason where available.

The UI must distinguish between an event that is not implemented and a packet that is actually dropped by a modelled rule.

### 6.7 Assessment interface

The simulator must expose a grading interface that evaluates structured state and controlled test outcomes. Example checks:
- Required interface has expected IP/prefix and is operational.
- Required VLAN exists and a port belongs to it.
- Trunk has the expected allowed VLAN list.
- A route to a prefix exists with the expected next hop/source.
- OSPF neighbor reaches an expected state.
- A host can ping a target from a specified source.
- An ACL permits or denies a defined test flow.

Rubric checks should have:
- Stable check ID and description.
- Weight/points.
- Required or optional flag.
- Evaluation function/version.
- Safe expected values.
- Feedback message that does not reveal hidden answer data prematurely.

Do not grade only by comparing raw CLI text. Equivalent valid configurations should receive credit if they produce the required state/behaviour.

### 6.8 Simulator isolation and limits

- The initial simulator runs in-process or in isolated worker processes but does not need OS-level network access.
- Do not create real TAP/TUN interfaces or bridge student labs to the host network in the first release.
- Enforce maximum nodes, ports, events, simulated time, packet hops and retained trace size per lab.
- Enforce per-user and global concurrent simulation quotas.
- Kill/recycle a worker after timeout, memory threshold or invalid runtime state.
- A future real-emulation adapter must be a separate security review and deployment project.

---

## 7. Backend architecture

### 7.1 Architecture pattern

Use a modular monolith for the primary education platform and a separate simulation runtime boundary. Avoid splitting every domain into a microservice.

**Web frontend:** Next.js + TypeScript.  
**Primary API:** Django + Django REST Framework.  
**Database:** PostgreSQL.  
**Background jobs:** Celery + Redis.  
**Real-time communication:** Django Channels or a dedicated WebSocket gateway, selected after a small technical spike.  
**Topology editor:** React Flow / XYFlow.  
**Terminal:** xterm.js.  
**Simulation engine:** Python package with a worker/runtime API.  
**Observability:** structured application logs, metrics, error tracking and audit events.

Pin exact dependency versions in lockfiles. Confirm current library compatibility during implementation rather than relying on unverified version assumptions.

### 7.2 Suggested logical modules

Django apps/modules:
- `accounts` — users, profiles, roles and invitations.
- `organizations` — future institution/tenant boundary; may be minimal initially.
- `courses` — courses, modules, classes and enrolments.
- `questions` — question schemas, versions, tags and review workflow.
- `assessments` — exam definitions, attempts, answers and grading.
- `labs` — lab definitions, versions, assignments, personal labs and submissions.
- `simulation_orchestration` — runtime allocation, lifecycle, quotas and provider adapter.
- `analytics` — derived reports and exports.
- `audit` — security-sensitive administrative and grading events.
- `notifications` — in-app and email notifications.

Keep domain logic in service/domain layers, not in oversized views or serializers. Use transactions for multi-record state changes.

### 7.3 Simulator API boundary

Define a versioned internal contract, independent of the simulator implementation. Minimum operations:
- Create runtime from a validated lab version.
- Get runtime status.
- Send a CLI command to a device.
- Start/pause/resume/step/stop/reset runtime.
- Fetch device state permitted to the requesting user.
- Stream or page simulation events.
- Run a set of grading checks.
- Export a sanitized checkpoint/trace.

Every call must include authenticated service identity, runtime ID and correlation ID. A user must never be able to select another user's runtime by guessing an ID.

Use an adapter interface such as `SimulationProvider`; do not couple course/assessment code directly to a specific engine implementation. A future provider may be an external engine, but the initial provider is the original simulator.

### 7.4 Topology execution flow

1. User edits a topology in the browser.
2. Frontend sends a topology document to the API.
3. Backend validates authorization and JSON schema.
4. Backend validates graph constraints and simulator capability support.
5. Lab orchestration creates an isolated runtime using the selected simulator version.
6. Runtime initializes devices, interfaces, links, configuration and seed.
7. Browser receives a scoped session token for CLI and event streaming.
8. Commands and simulation controls go through authenticated APIs/gateway.
9. Runtime emits typed events; UI renders topology status and trace.
10. On submission, the grading service runs the rubric and persists results.
11. Runtime is stopped or retained according to lab policy; cleanup is guaranteed on expiration.

---

## 8. Data model baseline

Use UUID primary keys for externally exposed records. Use timestamps in UTC and store a user's timezone separately for display and deadline interpretation.

Core entities (final fields to be designed in feature specs):
- `User`, `UserProfile`, `Role`, `Invitation`.
- `Course`, `CourseModule`, `ClassGroup`, `Enrollment`.
- `Topic`, `Question`, `QuestionVersion`, `QuestionTag`.
- `Exam`, `ExamVersion`, `ExamQuestion`, `ExamAssignment`, `ExamAttempt`, `ExamResponse`, `ExamResult`.
- `LabDefinition`, `LabVersion`, `LabAssignment`, `LabInstance`, `LabCheckpoint`, `LabSubmission`.
- `TopologyDocument`, `DeviceDefinition`, `SimulationRuntime`, `SimulationEventReference`.
- `Rubric`, `RubricVersion`, `RubricCheck`, `RubricResult`.
- `InstructorFeedback`, `GradeOverride`, `AuditEvent`, `Notification`.

Important integrity rules:
- Published versions are immutable.
- Attempts reference exact question/exam/lab versions.
- A response references the exact question version shown to the student.
- Randomized generation stores seed and generated parameters.
- Scores store grading algorithm/version.
- Grade overrides store actor, timestamp, previous value, new value and reason.
- Runtime records have explicit ownership and expiry.
- Use database constraints for uniqueness and valid state transitions where practical.

---

## 9. API and integration conventions

- Prefix APIs with `/api/v1/`.
- Use consistent pagination, filtering, sorting and error response formats.
- Validate request and response schemas.
- Use idempotency keys for operations that may be retried, such as lab launch or exam submission.
- Use server-side authorization on every request.
- Avoid exposing internal database IDs where UUID/public IDs are appropriate.
- Use WebSockets only for real-time terminal/event flows; normal CRUD remains HTTP.
- Document APIs with OpenAPI.
- Version simulator contracts independently from public education APIs where necessary.

Example endpoint groups (illustrative, not a complete API contract):

```text
/api/v1/auth/
/api/v1/users/
/api/v1/courses/
/api/v1/classes/
/api/v1/enrolments/
/api/v1/questions/
/api/v1/exams/
/api/v1/exam-attempts/
/api/v1/labs/
/api/v1/lab-versions/
/api/v1/lab-assignments/
/api/v1/lab-instances/
/api/v1/simulation-sessions/
/api/v1/reports/
/api/v1/audit-events/
```

---

## 10. Security, privacy and operational requirements

### 10.1 Application security

- Follow OWASP ASVS principles appropriate to the application risk.
- Secure cookies, CSRF protection, CORS allowlists and appropriate CSP.
- Password hashing through Django's supported password hashers.
- Rate limiting for login, password reset, exam submission and runtime creation.
- Input validation and output encoding.
- File upload type/size limits, malware scanning where available, and non-executable storage.
- Secrets only in environment/secret management; never commit credentials.
- Audit role changes, exports, grade overrides, content publication and security-sensitive actions.
- Do not log passwords, tokens, full session cookies or unnecessary personal information.

### 10.2 Simulator security

- The simulator must not expose host shell, host filesystem or arbitrary code execution.
- CLI parser is a strict allowlisted grammar.
- Topology import is schema-validated and resource-bounded.
- Student labs have strict isolation at runtime and data-access levels.
- Runtime/session tokens are short-lived, scoped and revocable.
- Rate-limit commands and event subscriptions.
- Prevent cross-student runtime access and cross-class data leakage.
- Denial-of-service protections: node/edge/event caps, logical-time caps, CPU/memory/time budgets and cleanup.

### 10.3 Privacy and retention

- Collect only information needed for learning administration and platform security.
- Define retention and deletion policies before production.
- Students can view their own records; instructors only see authorized class records.
- Provide administrator workflows for data export and account deactivation.
- Do not use student data to train external AI systems without a separate lawful basis, clear disclosure and appropriate consent.

### 10.4 Reliability and recovery

- Automated database backups and tested restore procedure.
- Versioned lab and question content.
- Runtime cleanup for abandoned sessions.
- Graceful handling of WebSocket disconnects and browser refresh.
- Exam autosave and well-defined recovery behaviour.
- Health/readiness checks for web, worker, database, Redis and simulator runtime.
- Centralized logs with correlation IDs.

---

## 11. Non-functional requirements and initial targets

These are initial engineering targets to validate, not guarantees. Record actual results in load tests before production claims.

- Standard API read requests: target p95 below 500 ms under the agreed test workload, excluding simulation execution and large exports.
- Exam answer autosave: target acknowledgement below 1 second under the agreed test workload.
- Simulation UI: event streaming must remain responsive for a bounded lab; use backpressure and trace truncation rather than unbounded memory growth.
- Initial reference load test: 10 concurrent learners, each operating a small topology of up to 5 simulated devices; measure CPU, memory, event throughput and latency. Increase targets only after profiling.
- Availability: establish a realistic target after deployment topology and backup/recovery are defined.
- Accessibility: keyboard operability for core forms and exam flows; meaningful labels and contrast; topology editor must provide a non-canvas alternative for inspecting devices and links.
- Browser support: current stable Chrome, Edge and Firefox; validate Safari before promising full support.
- Maintainability: typed frontend, linting, formatting, test coverage for domain logic and documented database migrations.

---

## 12. Testing and quality strategy

### 12.1 Required test layers

- Unit tests for command parsing, addressing, route selection, MAC learning, VLAN forwarding, protocol state transitions and grading checks.
- Property-based tests for IP prefix handling, longest-prefix matching, topology graph validation and deterministic simulation.
- Integration tests for API authorization, exam attempts, lab lifecycle and simulator-provider contract.
- End-to-end tests for admin/instructor/student workflows.
- Security tests for IDOR, privilege escalation, unsafe imports, injection and session isolation.
- Load tests for exam concurrency and simulation runtime capacity.
- Regression fixtures for packet traces and protocol scenarios.

### 12.2 Simulator correctness requirements

For every supported protocol/feature:
- Define the intended subset and explicit exclusions.
- Provide positive, negative and boundary test cases.
- Include at least one end-to-end topology scenario.
- Verify deterministic replay.
- Verify observable CLI output and event trace.
- Verify incorrect/missing configuration produces the documented outcome.
- Do not advertise the feature as supported until its acceptance tests pass.

### 12.3 Definition of done

A feature is done only when:
- Reviewed requirements and acceptance criteria are satisfied.
- Backend authorization and validation are implemented.
- Tests cover success, failure and permission boundaries.
- Migrations are reversible or have a documented recovery plan.
- UI loading, empty, error and success states exist.
- API documentation and relevant product documentation are updated.
- Logs and audit events exist where required.
- No secrets or generated build artifacts are committed.
- A human reviews Kiro's code diff and test results.

---

## 13. Delivery roadmap

Build in vertical slices. Do not attempt all modules concurrently.

### Phase 0 — Discovery and architecture validation

Deliverables:
- Final product name and initial deployment assumptions.
- Architecture decision records (ADRs) for frontend/backend, simulator process model, persistence, real-time delivery and hosting.
- Small simulator proof of concept: two hosts connected through a switch, ARP and ping, with deterministic packet trace.
- UI prototype for topology editor and CLI panel.
- Capacity benchmark for a small topology.

Exit criteria: prove that the simulator can model and explain one end-to-end packet path before investing in the complete UI.

### Phase 1 — Platform foundation

Deliverables:
- Repository, CI, local development environment and environment configuration.
- Django API, PostgreSQL and Next.js frontend.
- Authentication and RBAC.
- Admin/instructor/student navigation and account management.
- Audit baseline and API documentation.

Exit criteria: all three roles can sign in and only access permitted resources.

### Phase 2 — Learning and examination MVP

Deliverables:
- Courses, classes and enrolments.
- Topic taxonomy and versioned question bank.
- Single/multiple choice, matching, fill-in and subnetting questions.
- Practice exam flow, timed attempts, autosave, scoring and explanations.
- Student and instructor progress dashboards.

Exit criteria: an instructor can publish an exam, assign it, a student can complete it, and the result appears correctly in student and instructor reports.

### Phase 3 — Simulator core MVP

Deliverables:
- Device and interface model.
- Ethernet links, IPv4 hosts, ARP and ICMP.
- Basic switch forwarding and MAC learning.
- Basic router interfaces, connected/static routing and packet forwarding.
- Educational CLI subset and terminal panel.
- Deterministic event trace and step/realtime controls.

Exit criteria: a student can build a small topology, configure it using the supported CLI, ping across routed networks and inspect why a packet succeeds or fails.

### Phase 4 — Lab authoring and grading

Deliverables:
- Lab JSON schema and topology editor.
- Draft/publish/version workflow.
- Lab assignments and per-student runtime instances.
- Rubric engine and automated checks.
- Personal labs, save/duplicate/reset and submission history.

Exit criteria: instructor publishes a lab; student receives an isolated instance; the system grades the resulting configuration and behaviour and stores the result.

### Phase 5 — CCNA protocol expansion

Deliverables, ordered by validated learning needs:
- VLAN access/trunking and router-on-a-stick.
- DHCP and ACLs.
- OSPFv2 single-area model.
- IPv6 fundamentals and forwarding.
- STP/RSTP and EtherChannel.
- Additional troubleshooting scenarios and question types.

Exit criteria: each feature passes its protocol-specific acceptance suite and has at least one instructor-ready lab.

### Phase 6 — CCNP capabilities and scale

Deliverables:
- Advanced OSPF scenarios.
- BGP and/or EIGRP only after dedicated design and test specifications.
- More complex switching, redundancy and security scenarios.
- Advanced analytics and class reporting.
- Runtime worker scaling and capacity management.
- Optional institution-level tenancy.

Exit criteria: protocol support and performance are demonstrated with documented limitations and repeatable tests.

---

## 14. Suggested repository structure

Use a monorepo initially, with clear boundaries:

```text
netlab-academy/
├── .kiro/
│   ├── steering/
│   │   ├── product.md
│   │   ├── tech.md
│   │   ├── structure.md
│   │   └── simulator-principles.md
│   └── specs/
│       ├── 00-foundation/
│       ├── 01-auth-rbac/
│       ├── 02-courses-enrolment/
│       ├── 03-question-bank/
│       ├── 04-examination-engine/
│       ├── 05-simulator-poc/
│       ├── 06-topology-editor/
│       ├── 07-lab-lifecycle/
│       └── 08-lab-grading/
├── apps/
│   └── web/                  # Next.js application
├── services/
│   ├── api/                  # Django project and domain apps
│   └── simulator/            # Simulation API/worker process
├── packages/
│   ├── simulator-core/       # Pure simulation domain and protocol models
│   ├── lab-schema/           # Versioned topology/lab schemas and validators
│   └── api-client/           # Generated/shared TypeScript API client if useful
├── docs/
│   ├── PROJECT_SPEC.md
│   ├── adr/
│   ├── protocols/
│   └── operations/
├── infra/
│   ├── docker/
│   └── deployment/
├── scripts/
├── .env.example
├── .gitignore
└── README.md
```

This is a target structure, not a requirement to create all directories immediately. Keep each feature's implementation aligned with the approved architecture.

---

## 15. Kiro development workflow

Use Kiro's spec-driven workflow for every meaningful feature. Each feature should have:
- `requirements.md`: user stories and testable acceptance criteria.
- `design.md`: architecture, data flow, API changes, state transitions, edge cases and test strategy.
- `tasks.md`: small, ordered, executable tasks with dependencies.

Keep persistent project rules in `.kiro/steering/`. At minimum maintain:
- `product.md` — product vision, users, boundaries and terminology.
- `tech.md` — approved stack, version policy and technical constraints.
- `structure.md` — repository layout and code organization.
- `simulator-principles.md` — determinism, no host networking, CLI safety, protocol support policy and simulator testing rules.

### 15.1 Working rules for the Kiro agent

1. Read all applicable steering files and the project specification before proposing changes.
2. Work on one feature spec at a time. Do not implement the whole project from this document in one prompt.
3. Start with requirements and acceptance criteria. Ask no redundant questions where this document already gives the answer; record unresolved assumptions in the spec.
4. Produce the design and tasks before implementation.
5. Identify dependencies and avoid parallel implementation of tightly coupled simulator state changes.
6. Implement the smallest vertical slice that proves the feature.
7. Write tests before or alongside implementation, especially for network protocol logic and permissions.
8. Run formatters, linters, type checks, unit tests and relevant integration tests.
9. Report files changed, design decisions, test commands/results, known limitations and follow-up work.
10. Never silently broaden scope, change the approved stack, add a new framework, or replace the simulator architecture. Propose an ADR and wait for human review for material architectural changes.
11. Never claim a protocol is supported without acceptance tests and documented limitations.
12. Do not add real network interfaces, shell execution, arbitrary scripts or third-party network images to the simulator MVP.
13. Keep secrets out of the repository and use `.env.example` for documented variable names only.
14. Human review is required before merging or deploying changes that affect authentication, authorization, grading, simulator isolation or data migrations.

### 15.2 First Kiro task

Do not ask Kiro to build all of NetLab Academy. Start with a discovery and proof-of-concept spec:

**Spec name:** `simulator-proof-of-concept`

**Goal:** Prove the original simulation architecture with two PC nodes connected to one educational Ethernet switch. Each PC can be assigned an IPv4 address, ARP resolution occurs, ICMP echo succeeds, and a deterministic event trace can be inspected. Include a minimal CLI or structured device configuration interface, automated tests and a small topology visualization.

**Required outputs before coding:**
- `requirements.md` with acceptance criteria for host addressing, switch learning, ARP, ICMP, deterministic replay and unsupported-feature handling.
- `design.md` describing event scheduling, frame delivery, device/interface state, event trace and simulator API boundary.
- `tasks.md` with small implementation and test tasks.

**Proof-of-concept acceptance criteria:**
- Two hosts connected to the same switch can ping each other after valid configuration.
- ARP request/reply is visible in the event trace.
- The switch learns source MAC addresses and forwards subsequent unicast frames appropriately.
- A disconnected link or incorrect IP configuration causes a meaningful, deterministic failure.
- Re-running the same scenario with the same seed and inputs produces the same event sequence and result.
- No raw sockets, host network interfaces, shell commands or arbitrary code are used.
- Unit and integration tests cover success and failure cases.

Only after this proof of concept is reviewed and accepted should Kiro proceed to platform foundation or expand the simulation engine.

---

## 16. Open decisions to resolve during Phase 0

These decisions should be recorded as ADRs, with trade-offs, before production implementation:

1. **Initial deployment model:** single college/training organization first, or public self-registration from day one?
2. **Frontend/backend repository operations:** one deployment pipeline or separate web/API releases?
3. **Realtime transport:** Django Channels versus a separate WebSocket gateway.
4. **Simulator process model:** one worker per lab, a worker pool, or a hybrid; choose based on profiling and isolation requirements.
5. **Persistence of runtime state:** event replay, periodic snapshots or both.
6. **Lab content portability:** exact JSON schema and compatibility policy between simulator versions.
7. **Assessment policy:** which exam actions are autosaved, resumable or locked after submission?
8. **Content review:** one-person instructor publishing or mandatory second-person review for shared catalogue content?
9. **Hosting and capacity:** initial server resources, backup target, concurrency target and growth path.
10. **Brand and legal review:** product name, trademark wording, content licensing, privacy policy and acceptable-use policy.

Do not let these open decisions block the first isolated simulator proof of concept unless they directly affect its design.

---

## 17. Success measures

Track product outcomes, not only feature count:
- Students can complete an exam and understand which topics need improvement.
- Instructors can create and assign a practical lab without editing application code.
- Students can independently build and troubleshoot a working small network.
- Lab grading is reproducible and based on validated configuration/behaviour.
- Student progress history remains accurate across content revisions.
- No user can access another user's private work or hidden assessment material.
- The simulator remains responsive and bounded under the agreed concurrency test.
- New protocol features can be added without rewriting the course, exam and account systems.

**North-star outcome:** a learner can move from understanding a networking concept, to answering an exam question, to configuring a network, to troubleshooting it, and finally to demonstrating mastery in a single platform.
