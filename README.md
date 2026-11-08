# NetLab Academy — Kiro starter pack

This starter pack contains the long-term product/technical specification and initial Kiro steering files.

## Contents

- `PROJECT_SPEC.md` — product, architecture, simulator, security, roadmap and Kiro workflow baseline.
- `FIRST_KIRO_PROMPT.md` — copy/paste kickoff prompt for the first simulator proof-of-concept spec.
- `.kiro/steering/product.md` — always-on product context.
- `.kiro/steering/tech.md` — always-on technology and engineering constraints.
- `.kiro/steering/structure.md` — repository organization rules.
- `.kiro/steering/simulator-principles.md` — simulator-specific constraints, loaded for simulator/schema files.

## How to use it

1. Create or open the project root in Kiro.
2. Copy the contents of this starter pack into that project root, preserving the `.kiro/steering/` directory.
3. Keep `PROJECT_SPEC.md` at the repository root or move it to `docs/PROJECT_SPEC.md` and update the steering references.
4. Review the specification and decide the open Phase 0 decisions that affect your deployment.
5. In Kiro, create a feature spec named `simulator-proof-of-concept` using Section 15.2 of `PROJECT_SPEC.md`.
6. Review `requirements.md`, `design.md` and `tasks.md` before asking Kiro to implement the tasks.
7. Build and test one vertical slice at a time. Do not ask Kiro to generate the entire platform in a single run.

The product name is provisional. This is a planning baseline, not a finished implementation or guarantee that every proposed feature has already been validated.
