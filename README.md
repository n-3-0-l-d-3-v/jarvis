# Jarvis

Orchestrator agent for the personal multi-agent developer ecosystem. Single
entry point for "talk to my system": classifies intent, assigns a
sensitivity tier, and dispatches to the sibling agent (Friday, Ultron,
Alfred) whose MCP server can handle the request.

Built from `10x/docs/agents/jarvis.md` and `10x/docs/omniroute-privacy-spec.md`
in the ecosystem's umbrella repo — read those for the design intent this
implements.

## What's actually built (v1)

- **Sensitivity-tier engine** (`jarvis/tiers.py`) — the real, tested
  implementation of the `private` / `personal-token` / `work` / `public`
  model from the privacy spec: fail-closed defaults, path-based forcing
  (`vault/private/**` in a request forces `private` unconditionally),
  and refusal to dispatch when a request's tier is stricter than the
  target agent's declared `default_sensitivity_tier` floor.
- **Agent registry** (`jarvis/registry.py` + `jarvis/agents.yaml`) — loads
  each sibling agent's repo path (env-var overridable), launch command,
  health-check command, and declared tier.
- **MCP client manager** (`jarvis/mcp_client.py`) — launches a sibling
  agent's MCP server as a stdio subprocess (via the standard `mcp` SDK)
  and calls a tool on it. Launch-per-call, not pooled (see "v1
  placeholders" below).
- **Intent classifier** (`jarvis/classifier.py`) — v1 keyword/rule-based
  router. Explicitly a placeholder (see below).
- **Context store + audit log** (`jarvis/store.py`) — one SQLite file,
  two separate concerns: `ContextStore` (short-term "what did we just
  talk about") and `AuditLog` (privacy/compliance dispatch trail for a
  future Wall-E agent to read).
- **CLI** (`jarvis/cli.py`): `jarvis ask`, `jarvis route --dry-run`,
  `jarvis health`, `jarvis daily`, `jarvis --health`.

## v1 placeholders — read this before trusting the routing

- **The intent classifier is not smart.** It counts keyword hits per
  agent category and picks the max, with a fixed tie-break order and a
  default fallback to Friday. It exists only because Phase 5 (local
  Ollama models) hasn't landed yet. Use `--agent <name>` to override it
  any time it's wrong — that escape hatch is the actual point of v1, not
  the classifier's accuracy. It should be replaced by a local-model
  classifier once Phase 5 exists.
- **No provider routing.** The privacy spec's OmniRoute (local Ollama +
  free-tier cloud fallback, chosen per tier) doesn't exist yet — that
  infrastructure is Phase 5. Jarvis v1 computes and enforces the tier
  (refusing to dispatch on a conflict) and logs every decision, but does
  not choose an LLM provider. There is nothing to route to yet.
- **MCP servers are launched per call, not pooled.** Every `jarvis ask`
  pays full interpreter-startup + MCP-handshake cost. Fine for a CLI used
  a few times a day; would matter for a hot-path/voice-latency use case.
  A long-lived per-agent server process (or pool) is the tracked future
  optimization.
- **`jarvis ask` only has a generic default tool for Friday.** Friday's
  `ask_knowledge_base(question)` is the one sibling-agent tool whose shape
  is "free text in, free text out." Ultron's tools are all structured
  (artifact ids, claim predicates, project graph queries) and Alfred's all
  require a problem `slug` — neither has a natural mapping from an
  arbitrary sentence. `jarvis ask --agent ultron` or `--agent alfred`
  requires explicit `--tool <name> --tool-arg key=value`; without it,
  Jarvis fails with a clear error rather than guessing an argument.
- **Context store isn't pruned.** It grows forever in v1. Fine for
  personal use at this scale; rotation/pruning is a follow-up.
- **`jarvis daily` is health-only unless Friday's MCP server is reachable.**
  It always calls `jarvis health` internally; it *also* tries Friday's
  `daily_briefing` MCP tool and folds the result in, but doesn't block or
  fail the command if that call doesn't work (missing deps, no vault
  configured, etc.) — the failure is reported inline in the JSON, not
  swallowed silently.

## Design notes / judgment calls

The task spec left several things ambiguous. Here's what was decided and why:

- **`jarvis --health` vs `jarvis health`.** Both exist, on purpose. The
  ecosystem contract fixes the *health_check_command* in `agent.yaml` to
  `jarvis --health` (an eager top-level flag, matching Friday's
  `friday --health` and Ultron's `ultron --health` — confirmed by reading
  both CLIs) — that command reports **only Jarvis's own** status (context
  store reachable, at least one agent config loadable), symmetric with how
  Friday/Ultron/Alfred's own `--health` reports only their own status. The
  separate `jarvis health` **subcommand** is Jarvis-specific: it aggregates
  all three sibling agents' own `health_check_command` output plus Jarvis's
  self-health, because the task explicitly asked for an orchestrator-level
  aggregate view. They answer different questions; collapsing them into one
  would lose one of the two.
- **Tier "floor" semantics.** The spec says an agent's declared
  `default_sensitivity_tier` is "the floor" for anything routed to it, and
  separately that Jarvis must "refuse to dispatch a request whose computed
  tier conflicts with the target agent's declared tier." Reading both
  together: a request may always go to an agent that's *at least as
  protective* as the request needs (e.g. `work`-tier content routed to
  Ultron, whose floor is `private`, is fine — over-protection is safe).
  It's a conflict only when the computed tier is *more sensitive* than
  what the target agent guarantees (e.g. `private` content routed to
  Friday, whose floor is only `personal-token` — Friday isn't built to
  guarantee zero network calls). Implemented as
  `check_conflict(tier, agent, agent_floor)` in `jarvis/tiers.py`, tested
  in `tests/test_tiers.py`.
- **Path-based override is absolute, not just a default.** "Forces
  private tier regardless of which agent would otherwise handle it" is
  implemented literally: even an explicit `--tier` flag cannot weaken a
  path-forced `private` tier (`PathForcedTierError`). You can still pass
  `--tier private` redundantly; you cannot pass `--tier public` to escape
  it.
- **"Explicit per-request confirmation" for upgrading a tier's eligible
  providers** (spec: "You can never have Jarvis silently upgrade a
  private request to use cloud... requires an explicit, per-request
  confirmation, not a config flag flipped once") is approximated in v1 by
  treating the CLI's `--tier` flag itself as that explicit confirmation —
  there's no interactive prompt loop. This is a real simplification: a
  script that always passes `--tier work` isn't "confirming per request"
  in spirit even though it satisfies the letter of "flag, not silent."
  Since there's no provider routing yet (see above), nothing currently
  depends on this distinction actually gating a cloud call — it only
  gates whether Jarvis will *attempt* dispatch. Revisit when Phase 5
  provider routing lands.
- **Path-override pattern matching.** `vault/private/**` detection is a
  regex over the request *text* (`vault[\\/]+private[\\/]`), not a
  filesystem check — Jarvis's own repo doesn't contain a vault, and the
  spec's example paths are things a user would reference in a request
  ("summarize vault/private/journal.md"), not files Jarvis reads directly
  in v1. This means a request that describes private content without
  literally typing a `vault/private/...` path won't be caught by the path
  rule — it still gets the fail-closed default or the agent's own floor,
  just not this specific override.
- **Health check command literalism.** `jarvis/agents.yaml`'s
  `health_check_command` entries match each sibling's own `agent.yaml`
  *exactly* (e.g. Friday's is the `friday` console script, not
  `python -m friday`, because Friday has no `friday/__main__.py`) rather
  than whatever would be most convenient to launch from Jarvis. This
  means `jarvis health` can report a sibling as unhealthy for reasons
  that are really "that agent's own console script isn't installed in
  this environment" — see "Known gaps" below, this was observed on the
  build machine for Alfred (missing `pydantic_settings`) and Friday's
  console script (stale/broken entry point independent of Jarvis).
- **`jarvis ask`'s exit codes** are deliberately distinct per failure
  mode so scripts can branch on them: `2` = bad input (unknown agent,
  unknown tier, missing `--ultron-project`, no tool for a request),
  `3` = tier/agent conflict refusal, `4` = MCP dispatch failure (couldn't
  launch or talk to the subprocess), `1` = the tool itself returned an
  MCP-level error. Not specified in the task; chosen for CLI usability.

## What's NOT completed, and why

- **Ultron and Alfred real end-to-end integration tests.** Only Friday's
  MCP server was confirmed launchable in this environment (its deps
  happen to already be installed globally). Ultron's console script
  isn't installed here (`pip install -e ultron/` was not run — out of
  scope for this task, which said not to vendor sibling deps), and
  Alfred's `apps/api/.venv` wasn't activated/built here either. The unit
  tests for `jarvis.mcp_client` cover the same code path against a real
  (if trivial) MCP server (`tests/fake_mcp_server.py`), so the transport
  logic itself is exercised — just not against Ultron/Alfred's actual
  tool implementations. See "How to verify" below for how to get those
  running if you have those environments set up.
- **Context store pruning/rotation.** Not implemented — noted above.
- **Interactive per-request confirmation for tier upgrades.** Approximated
  by the `--tier` flag itself, as discussed above.
- **Voice interface entry point.** Explicitly a later phase per
  `10x/docs/agents/jarvis.md`; not attempted here.

## Install

Each sibling agent's own dependencies are **not vendored here** — install
them separately in their own repos per their own README/requirements.

```powershell
cd jarvis
pip install -e .[dev]
```

## Configuration

Sibling agent repo paths default to this machine's actual layout but can
be overridden:

```powershell
$env:JARVIS_FRIDAY_PATH = "C:\path\to\friday"
$env:JARVIS_ULTRON_PATH = "C:\path\to\ultron"
$env:JARVIS_ALFRED_PATH = "C:\path\to\alfred"
```

Context store / audit log location (default `~/.jarvis/jarvis.db`):

```powershell
$env:JARVIS_DB_PATH = "C:\path\to\jarvis.db"
```

## Usage

```powershell
# Sanity-check routing without dispatching anything
jarvis route "explain hash maps to me" --dry-run

# Force an agent / tier
jarvis route "generic question" --agent alfred --json

# Dispatch for real (Friday only has a generic default tool in v1)
jarvis ask "what have I captured about redis lately?"

# Ultron needs an explicit project path (it's project-scoped, not global)
jarvis ask "list objects in this binary" --agent ultron --ultron-project C:\path\to\re-project --tool ultron_list_objects

# Aggregate health across Jarvis + all three sibling agents
jarvis health

# Jarvis's own health only (the ecosystem contract's health_check_command)
jarvis --health

# Morning briefing (health + Friday's daily_briefing tool if reachable)
jarvis daily
```

## Test discipline

```powershell
cd jarvis
pip install -e .[dev]
python -m pytest -q
```

79 tests, all passing on this machine: tier engine (fail-closed default,
path override, agent-floor conflict refusal), intent classifier (each
keyword category, override precedence, tie-breaking, word-boundary
matching), registry loading, context store / audit log, health checking
(mixed healthy/unhealthy aggregation), CLI argument parsing and exit
codes, and the MCP client manager.

The MCP client manager is tested two ways:

1. `tests/test_mcp_client.py` — against `tests/fake_mcp_server.py`, a
   minimal *real* MCP server (not a mock) built with the same `mcp`
   package Friday/Alfred use, so the stdio transport + JSON-RPC handling
   is genuinely exercised.
2. `tests/test_integration_real_friday.py` — launches Friday's actual
   `python -m friday.mcp_server` as a subprocess (from wherever
   `JARVIS_FRIDAY_PATH` resolves to) and calls its real `knowledge_stats`
   and lists its real tools. **This ran successfully against this
   machine's Friday checkout** — confirmed end-to-end: Jarvis's
   `mcp_client.list_tools`/`call_tool` genuinely talk to Friday's MCP
   server, not a stand-in. It skips cleanly (not a failure) if Friday's
   repo or dependencies aren't present, so the rest of the suite doesn't
   depend on that environment existing.

## Known gaps observed on the build machine (not Jarvis bugs)

Running `jarvis health` here reports Friday and Alfred unhealthy and
Ultron's command not found — these are sibling-repo/environment issues,
not something wrong in Jarvis's dispatch logic (Friday's own MCP server
launches and responds fine via `python -m friday.mcp_server`, proven by
the integration test above):

- Friday's installed `friday` console script raises
  `ModuleNotFoundError: No module named 'friday'` in this environment —
  a stale/broken entry point, unrelated to the `python -m friday.mcp_server`
  path Jarvis actually dispatches through.
- Alfred's `python -m alfred --health` fails with
  `ModuleNotFoundError: No module named 'pydantic_settings'` — a missing
  dependency in `apps/api`, not installed as part of this task per the
  instructions not to vendor sibling deps.
- Ultron's `ultron` console script isn't installed in this environment
  (`ultron/pyproject.toml` declares it via `[project.scripts]`, but
  `pip install -e ultron/` was not run here).
