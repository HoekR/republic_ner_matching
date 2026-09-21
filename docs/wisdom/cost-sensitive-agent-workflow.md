# Cost-sensitive agent workflow

**Status:** stable  
**Applies to:** multi-step DH pipelines (Bayesian stats, publication, long migrations)  
**Portable:** yes  
**Pilot:** `wvo_corr` (WVO correspondence, PyMC + Observable Framework)

## Rule

1. **One step per chat** — do not ask the agent to "execute the whole plan".
2. **Split docs** — agents read narrow files; humans tick progress elsewhere.
3. **User runs the terminal** — agents give commands or edit files; default to no agent shell.
4. **Tier models** — cheap model for boilerplate; strong model for specs and review only.
5. **You run heavy compute** — sampling, builds, git push stay local.

## Doc layout (recommended)

Thin bootstrap: root `PLAN.md` (headlines) plus empty `plans/` (`milestones/`, `steps/`). Add step and milestone files when the project becomes multi-step — no sample STEP stubs in the template.

| File | Role |
|------|------|
| `AGENTS.md` | Canonical agent brief (Cursor + Copilot) |
| `PLAN.md` | Headlines: short checklist + milestone index |
| `plans/<name>.md` | Cross-cutting overview (stack, risks, diagram) — optional |
| `plans/milestones/M*.md` | Milestone writeups — optional |
| `plans/steps/STEP*.md` | **One editable guide per step** (goal, done-when, commands, model notes) |
| `plans/steps/README.md` | Index linking all steps — optional |
| `plans/steps/MODEL-TIERS.md` | Project-specific handoff table — optional |
| `.cursor/rules/` | Points to `AGENTS.md`; `alwaysApply: true` |

**Wisdom lives in dighum_template.** Project steps stay in `plans/steps/` — domain-specific, versioned with the repo. Older projects may still use `docs/steps/` (workflow MCP falls back).

### Step file template

```markdown
# Step N — Short title

**Goal:** …
**Done when:** …

## Prerequisites
…

## You do
(commands — user runs these)

## Cursor guides
(what to ask for)

## Next step
Link to STEP(N+1).md
```

## Three tiers (+ human operator)

| Tier | Who | Best for |
|------|-----|----------|
| **You** | Terminal & notebooks | `uv`, sampling, `npm run build`, git, verify |
| **Ask / simple** | Cheapest model | Command lists, "explain this error", single-file scaffold |
| **Strong** | Default Agent / plan | Model specs, join logic, manifest conflicts, review diffs |

**Default:** agents are **advisors and editors**, not operators.

## Prompt patterns

### Cheapest — Ask, no tools

```
Guide step 2. List commands only; I run them myself. Do not use tools.
```

### Simple Agent — edit files, no terminal

```
Read plans/steps/STEP2-loaders.md only.
Implement load_data.py as specified. Do not run commands.
```

### Strong — spec only

```
Guide step 3a — PyMC model spec and notebook outline only.
I will run sampling myself.
```

Add **"I run commands myself"** or **"don't use terminal"** to any prompt to prevent agent shell loops.

## What agents should not do autonomously

- Run full multi-step plans in one session
- PyMC sampling or long builds in agent terminal
- Choose statistical priors without human review
- Bootstrap + model + publication in one go

## What to hand off to a simpler model

- Scaffolding from a written step guide (loaders, export scripts, YAML)
- Manifest entries copied from a table in the step doc
- Observable page stubs once export contract is defined

Keep on a **strong** model: first PyMC spec for a phase, incipit/join edge cases, `data_io.check` failures.

## Integration with dighum_template

| Concern | Wisdom / tool |
|---------|----------------|
| Paths & datasets | [manifest-discipline](manifest-discipline.md) |
| Credentials | [local-config-not-env](local-config-not-env.md) |
| Publication bridge | [observable-framework-bridge](observable-framework-bridge.md) |
| Data MCP | [data-io-mcp](data-io-mcp.md) |
| Workflow MCP | [workflow-mcp](workflow-mcp.md) |
| MCP servers (shared) | Optional sibling [dighum_template](https://github.com/HoekR/dighum_template) — not vendored |
| This workflow | **cost-sensitive-agent-workflow** (this file) |

After bootstrap with `--with-wisdom`, this topic copies to `docs/wisdom/`.

## Why

Long agent runs burn Cursor budget on shell retries, context bloat, and re-planning. DH pipelines are naturally phased (explore → semi → frozen → pub). Per-step docs let you **edit strategy without rewriting AGENTS.md**, and let cheaper models work from a fixed spec.

## Anti-patterns

| Wrong | Right |
|-------|-------|
| "Execute the plan" | "start step 3a" |
| One 50-page PLAN.md | `PLAN.md` + `plans/steps/*` (create on demand) |
| Agent runs `pm.sample()` | User runs; agent interprets PPC if stuck |
| Strong model writes boilerplate | Simple model + step guide |
| Domain steps in dighum wisdom | Portable rules here; steps in project |
| Sample STEP stubs in every new repo | Empty `plans/steps/`; add guides when needed |

## Example invocation table

| You say | Agent does |
|---------|------------|
| **start step N** | Opens `plans/steps/STEPN-*.md` only |
| **guide step N** | Spec / checklist; no later steps |
| **review my step N** | Read your diff; suggest fixes |

## Budget heuristic

Target **$20–40** on Cursor Pro for a full phased project: ~10–15 focused chats, user executes locally, strong model only for specs and unblock.
