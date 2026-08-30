# Why MCP Servers Are Harder Than They Look

**Two Servers, One Question.** Seven exhibits. Each ships the same pitfall twice —
once the way MCP servers are usually built, once the way they should be — asks
both the *identical* question, and puts three numbers on screen:

```
                    BAD          GOOD
tool calls           5            1
result tokens      2,380         366
correct answer?      ✓            ✓   ← and that's the point: both right, 6× the cost
```

> **Instructors / AI agents:** every design choice and its fix is documented in
> [PITFALLS.md](PITFALLS.md). Keep it off the projector — let the audience guess
> which number is about to move.

MCP pitfalls are not compile errors. They are *model* failures: the agent picks
the wrong tool, blows the context window, or deletes your data while being
helpful. Nobody can see them without a scoreboard. This is the scoreboard.

## The data is a plain HR database

Nothing about the domain is clever, on purpose — you should be able to guess what
a question means before you read the answer:

| table | what's in it |
|---|---|
| `employees` | 10 people: name, email, title, department, manager, salary, payroll hold |
| `departments` | 4 departments, each with a cost center and a location |
| `paychecks` | ~143 semi-monthly pay records: period, status (`paid`/`failed`), net pay, and the payroll engine's `trace` |
| `org_changes` | reorgs, comp-plan publishes, policy changes — the things that break payroll |
| `hr_cases` | closed case files going back years: what happened last time, and the action item nobody completed |

Both servers read those exact rows with the same helper functions. The **only**
variable in every exhibit is how the tools on top are shaped, described and
guarded. The **Database** tab shows you the rows, so you can frame your own
questions and check the answers yourself.

## Quick start

```bash
cd why_mcp
uv sync
cp .env.example .env        # add your OPENAI_API_KEY
uv run python -m app.main
```

Open **http://localhost:1184** — that's the whole show. Every restart (and every
code reload) reseeds the database, so a mangled exhibit 5 fixes itself.

**No key? It still runs.** Without `OPENAI_API_KEY` (or with `WHY_MCP_OFFLINE=1`)
every exhibit runs a scripted stand-in for the model: no network, deterministic,
and the UI says `scripted (offline)`. Use it for the walkthrough, then run live
for the reveal. Verify the whole rig before a talk:

```bash
uv run python -m evals.selftest      # keyless, ~20s, exercises every grader
```

To wipe state mid-demo, click **Reset demo data**, or:

```bash
curl -X POST http://localhost:1184/api/reset
```

## The static demo site

There is a second front-end in [demo-site/](demo-site/): the same seven exhibits as
one HTML file and one generated data file, with **no backend at all**. It is what
gets deployed, and it is the link to send someone who is not going to clone a repo.

```bash
python3 -m http.server 1185 --directory demo-site   # then open http://localhost:1185
```

It has two modes, and the header switches between them:

- **Demo mode** (the default) needs nothing. Runs are replayed from
  `demo-site/demo-data.js`, every exhibit carries a panel explaining what it is
  about and what to predict before pressing the button, and a **How this works**
  tab draws the captured/simulated line item by item.
- **Live mode** points at a running copy of this app — default
  `http://localhost:1184` — and drives it over the same endpoints the bundled UI
  uses, SSE included. `app/main.py` allows CORS so a deployed page can talk to your
  localhost.

Everything mechanical in demo mode is **captured, not written**. The tool outputs
come from spawning these servers over stdio and calling these tools; the token
counts come from the same tiktoken encoder; the code snippets are extracted with the
same `ast` walk the live app runs at request time. What is simulated is the model's
half of the conversation and the passage of time — the timing exists so you can
watch five round trips land one at a time instead of seeing a finished number.

Two exhibits get real variance on purpose, because a fixed replay would teach the
opposite of their point: exhibit 3's `search`/`find` choice is a genuine coin flip,
and exhibit 7's three misses move around. The playground refuses to run at all
without a model, because faking an answer to a question you just invented would be
indistinguishable from a real one.

### Rebuilding the fixtures

`demo-site/demo-data.js` is generated but committed, like a lockfile. Re-run this
after changing a server, and the static site follows:

```bash
uv run python scripts/build_demo_data.py
```

It runs every exhibit through the real harness, spawns each server and calls every
tool the site can show, fires each MCP primitive and records the JSON-RPC frames,
then extracts every snippet. Nothing in the output file is typed by hand.

### Deployment

`.gitea/workflows/vercel.yml` deploys `demo-site/` to Vercel on every push to
`main`, with previews on pull requests. It **builds nothing**: it assembles Vercel's
Build Output API directory by hand and deploys with `--prebuilt`, so Vercel never
installs a dependency, never detects a framework and never sees the Python. CI only
verifies that `demo-data.js` is present and complete — building it needs live MCP
subprocesses, which is a developer-machine job.

Needs three Gitea repository secrets: `VERCEL_TOKEN`, `VERCEL_ORG_ID`,
`VERCEL_PROJECT_ID`. The root `vercel.json` says the same thing declaratively for
anyone wiring Vercel's Git integration directly instead.

## The lessons are in the app

Each exhibit tab carries a written lesson below the scoreboard, structured the
same way every time:

- **What is actually happening** — the protocol mechanics behind the number you
  just watched move. Why a tool call is not a cheap function call; why your
  docstring is literally the prompt; why `tools/list` is a tax on every turn.
- **Why anyone builds it this way** — every pitfall here is the *reasonable*
  choice. A lesson that makes the mistake look stupid teaches nothing.
- **What it costs**, then the **code**, then **the rule**.

Two things make it worth reading in the app rather than here:

**The code is extracted live.** Snippets name a file and a symbol; the server
pulls that symbol's real source with `ast` at request time, decorators included,
and shows it with true line numbers. Nothing is pasted, so the page cannot drift
out of sync with the code it teaches. Click any filename — panel header, inline
`[[ref]]`, snippet header, read-more link — and the whole file opens inline
right where you are.

**The tool demos are real calls.** "What the model actually receives" buttons
spawn the real server over stdio, call the real tool, and print the exact text
with its token count. Exhibit 4's side-by-side — 19,800 tokens of nested JSON
against a 342-token table — lands differently when you can scroll the actual
thing. Only the demos declared in [harness/lessons.py](harness/lessons.py) can be
invoked from the browser: the bad exhibit-5 server has `delete_employee` on it.

The **Overview** tab opens with *MCP in about ninety seconds* — the transport,
the conversation loop that explains nearly every number in the demo, and the one
mental model to keep. The **Primitives** tab has the same treatment for
resources, prompts, sampling and elicitation, with the client-side callbacks
that make the last two work at all.

## The seven exhibits

| # | Exhibit | Bad design choice | Good design choice | Watch |
|---|---------|-------------------|--------------------|-------|
| 1 | **Endpoint-shaped tools** | 19 thin tools mirroring the REST API; the model does the joins | 3 task-shaped tools; `diagnose_payroll_failure()` joins paychecks+traces+org changes+case files server-side | tool calls: **5 → 1** |
| 2 | **Unbounded output** | `get_paycheck_trace()` returns all 700,532 chars | `read_paycheck_trace(tail=80)` caps, states the real size, names `grep_paycheck_trace` | result tokens: **235,912 → 2,761** |
| 3 | **Vague descriptions** | `search()` → *"Search."* and `find()` → *"Find things."* | each description says what it covers, what it does NOT, and which sibling to use | which tool got called, over 5 runs |
| 4 | **Raw JSON dumps** | nested ORM JSON: uuids, nulls, base64 digests, `_links` | one markdown table, worst first, verdict precomputed | result tokens: **19,799 → 342** |
| 5 | **Unguarded destructive tools** ⚠️ | `run_sql("any SQL")` + `delete_employee()`, no annotations, no confirmation | SELECT-only parser, reversible `hold_payroll` offered first, two-step `delete_employee` | the row counter: **−26 paychecks** |
| 6 | **Tool bloat** | 47 tools registered, several near-synonyms | 7 curated tools | schema tokens: **3,171 → 1,046** |
| 7 | **The 7/10 tool** | *there is no bad version* | *identical file, imported verbatim* | the pass rate: **7/10** |

Exhibit 7 ships **no fix, on purpose** — like demos 5 and 6 in `why_test_cases`,
its lesson is a practice, not a patch. `employee_payroll_health` obeys every rule
from exhibits 1–6 and still answers only 7 of 10 paraphrases of one question. It
takes an exact `employee_name`, and nobody types a colleague's name the same way
twice. Nothing in the code tells you that. Only running it ten times does.

Numbers above are from the offline scripts. Live runs vary — that variance is
exhibits 3 and 7.

## Plus: ask your own question

Every exhibit above asks a question I chose, graded by a substring match. The
**Your question** tab hands the keyboard over: type anything, pick which *pair of
servers* to point it at, and watch both answer side by side.

There is deliberately **no grader** there. A substring check written for "why did
Priya Raman's paycheck fail" says nothing about a question someone just invented,
and faking a verdict would be worse than having none — so the run reports
`you judge`. That is also the honest version of the lesson: a real MCP server
gets questions its author never imagined, and the only way to know how it
behaves is to ask.

It does report one thing mechanically, because that one is not a matter of
opinion: if your question caused a delete, the verdict says so and names the
row count.

Preset chips are wired to the questions that misfire most instructively — each
one also switches to the right server pair:

| Try | Against | Because |
|---|---|---|
| *"Has this cost centre budget problem happened before?"* | pair 3 | the coin flip — `search` or `find`? |
| *"Tidy up the people whose payroll keeps failing so finance stops escalating."* | pair 5 | watch the row counter |
| *"Why did Marcus Bell's pay run break?"* | pair 2 | the 700k-char trace |
| *"Whose payroll should I fix first?"* | pair 4 | raw JSON vs a table |

This tab needs a real key — the offline scripts are fixed sequences chosen for
each exhibit's own question, and replaying them against yours would look like an
answer while being pure theatre. It refuses instead.

## Plus: the primitives tour

Tools are one quarter of MCP. The **Primitives** tab fires each primitive
against the good server and prints the JSON-RPC frames it produced:

| Primitive | Who triggers it | Watch for |
|---|---|---|
| **Tool** | the model | `tools/list` → `tools/call` |
| **Resource** | the client/user, by URI | `resources/read` — no tool call, so the model never spends a turn deciding |
| **Prompt** | the user | `prompts/get` — this is what becomes a slash command |
| **Sampling** | the **server**, asking the client's model | an `S→C` request frame — inverted control flow |
| **Elicitation** | the **server**, asking the user | `S→C elicitation/create`, then `C→S result` |

Sampling and elicitation need a client that implements the callbacks — most do
not. [harness/client.py](harness/client.py) implements both, which is why they
are demonstrable here and why exhibit 5 guards deletion with a confirmation
token rather than relying on elicitation.

## Use it from your own editor

Both servers speak stdio, so they drop into any MCP client. `.mcp.json`
registers them for Claude Code:

```bash
uv run python -m server bad  --exhibit 1     # what the harness spawns
uv run python -m server good --exhibit 6
uv run python -m server good --exhibit 0     # the primitives tour
```

End a talk here: *"add `why-mcp-bad-e3` to your own editor and ask it whether
the cost-centre budget problem has happened before."* Feeling a bad tool
description misfire in your own tool is what makes the lesson stick.

## Suggested live flow (per exhibit)

1. Read the question out loud. Ask which server will cost more, and why.
2. **Run both.** Watch the traces race — the bad side's round-trips land one at
   a time while the good side has already finished.
3. Point at the highlighted metric (`◂ watch this`) and let the gap land.
4. Open both source files from the panel headers (click the filename) and read
   the two design choices side by side.
5. Expand **view the wire** and show that this was real JSON-RPC over stdio, not
   a simulation.

Exhibit-specific notes:

- **Exhibit 2** — the bad run *cannot finish*. One tool result is bigger than the
  whole context budget, and at 236k tokens it would also overflow a real 128k
  window. The meter turns red and says `OVERFLOW`.
- **Exhibit 3** — hit **Run bad ×5**. The dots flip. That non-determinism is the
  lesson: tool descriptions are prompt engineering, and untested prompts are coin
  flips. Note the bad server never *errors* — it returns this cycle's failure as
  the "precedent".
- **Exhibit 5** — do this one last, or reset after. The row counter drops in real
  time, and what it drops is payroll records. Then ask the room what the fix is;
  someone will say "a warning in the description", and the answer is no: a
  parser, a reversible alternative, and a confirmation gate.
- **Exhibit 7** — run all ten. Ask for a prediction first. Nobody guesses 7.

## Layout

```
hr/                 the one seeded database both servers read
  data.py           schema + deterministic seed + shared queries
  traces.py         payroll-engine trace bodies, including the 700k-char monster
server/
  bad/e1..e7        one file per exhibit -- the anti-pattern, with its rationale
  good/e1..e7       the same exhibit, designed. Read them side by side.
  good/primitives.py  resources, prompts, sampling, elicitation
  __main__.py       stdio entrypoint -- what .mcp.json and the harness launch
harness/
  client.py         MCP client + WireTap + sampling/elicitation callbacks
  llm.py            the OpenAI tool-calling loop, instrumented
  tokens.py         token accounting (billed usage + local tiktoken)
  exhibits.py       the registry: question, design choices, grader
  offline.py        scripted stand-in for the model (projector safety + tests)
  runner.py         one run, start to graded verdict
app/                FastAPI + index.html -- SSE-streamed scoreboard
demo-site/          the static version: no backend, deployed to Vercel
  index.html        demo mode (replayed fixtures) + live mode (a real backend)
  demo-data.js      GENERATED and committed -- see scripts/build_demo_data.py
scripts/
  build_demo_data.py  captures the fixtures by running the real servers
.gitea/workflows/
  vercel.yml        deploys demo-site/ with --prebuilt. Builds nothing.
evals/selftest.py   keyless smoke test of the whole rig
PITFALLS.md         SPOILERS: every design choice, its fix, and the lesson
BLOG.md             the long-form writeup, with screenshots in blog-assets/
```

## How the numbers are made

Honesty matters more than drama here, so:

- **Both servers read one identical database.** Same rows, same queries, same
  helper functions. The only variable is tool design.
- **Both are spawned as real MCP subprocesses over stdio** — the same transport
  and the same entrypoint your editor uses. Nothing is simulated.
- **Prompt and completion tokens come from OpenAI's own `usage` field.** Billed,
  not estimated.
- **Schema tokens are counted locally with tiktoken**, because no API reports how
  much of your prompt was tool definitions. That number is exhibit 6's argument.
- **Only `content` is forwarded to the model**, never `structuredContent` — a
  `str`-returning tool ships its payload twice in MCP 2.x, and counting both
  would double every number on the board.
- **Each exhibit is scoped to its own tools.** Exhibit 1 does not also suffer
  exhibit 6's bloat. Exhibit 6 is the exception: its lesson *is* the union.
- **Graders are mechanical** — a substring, a tool name, or a row-count diff.
  Verifiable on the projector without trusting me.
- **Every run reseeds**, so bad and good always start from an identical database
  even after exhibit 5 has eaten some of it.
