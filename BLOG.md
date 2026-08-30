# I built two MCP servers that answer the same question, and put the bill on screen

“Write good MCP tools” is excellent advice and a terrible explanation.

It makes tool design sound like a style question — naming, docstrings, a bit of
polish — when it is actually the thing that decides whether your agent answers in
one call or five, whether it costs 300 tokens or 20,000, and whether it deletes
your payroll records while explaining how helpful it has been.

The reason nobody argues about this is that the failures are invisible. A badly
designed MCP server does not fail to compile. It does not throw. Its tests pass,
because each tool does exactly what it says. You ship it, an agent uses it, and
the damage shows up somewhere you are not looking: on the bill, in the context
window, and in answers that are confidently wrong.

So I built **Why MCP**: seven pitfalls, each implemented twice — once the way MCP
servers are usually built, once the way they should be — both reading the same
database, both asked the identical question, with three numbers on screen.

![Exhibit 1: the same question answered by both servers, with the scoreboard](blog-assets/e1-scoreboard.png)

Look at the verdict boxes before the numbers. **Both say PASS.** Both servers
found that Priya Raman's paycheck failed because cost center CC-4100 ran out of
budget. One of them did it in five round trips and 2,380 result tokens; the other
in one call and 366. That is the whole thesis of the project: bad MCP design does
not announce itself with a crash, so it needs a scoreboard to be visible at all.

There is a [live demo site](https://why-mcp.vercel.app) that needs no backend, and
the repo runs locally with or without an API key. This post is the long version of
what it teaches.

## First: what MCP actually is

Most confusion about MCP comes from people picturing something more elaborate than
what is there.

**An MCP server is a program that speaks JSON-RPC 2.0, usually over stdio.** The
client launches your server as a subprocess and they talk over stdin and stdout.
The other transport is streamable HTTP, for remote servers. That is the entire
protocol. Everything else — tools, resources, prompts — is convention layered on
top of message names.

The servers in this project are launched exactly the way your editor would launch
them:

```bash
uv run python -m server bad  --exhibit 1
uv run python -m server good --exhibit 6
```

The part that matters, and the part that explains nearly every number in the demo,
is the conversation loop. Here is the real thing from the project's harness, which
is the smallest honest MCP client I could write:

```python
listed = await session.list_tools()
oa_tools = to_openai_tools(listed.tools)
schema_cost = tokens.schema_tokens(oa_tools)

messages = [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": question},
]

while True:
    resp = await openai_client.chat.completions.create(
        model=model, messages=messages, tools=oa_tools or None, tool_choice="auto"
    )
    choice = resp.choices[0].message

    if not choice.tool_calls:
        yield {"type": "assistant", "text": choice.content or ""}
        break

    for tc in choice.tool_calls:
        result = await session.call_tool(tc.function.name, args)
        text = tool_result_text(result)
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
    # ...and around again, with the WHOLE conversation re-sent
```

Read the last line twice. Every turn re-sends everything: the system prompt, the
question, the full tool schema, and every tool result so far. So:

- **A tool call is not a cheap function call.** It is a full round trip.
- **Five round trips do not cost five times one.** They cost more, because each
  earlier result is re-billed as input tokens on every subsequent turn.
- **`tools/list` is a standing tax.** Every registered tool's name, description
  and JSON schema is serialised into every request, whether or not it is called.
- **The model's entire basis for choosing a tool is text you wrote** — the name,
  the description, the parameter names. It cannot read your source or try a tool
  to see what happens.

That last point is the one people find hardest to internalise, so it gets its own
exhibit. Your docstrings are not documentation sitting next to the system. They
*are* the prompt.

![The overview tab's primer on the protocol](blog-assets/overview-primer.png)

## The one mental model to keep

MCP is **not** a way to hand an LLM your REST API.

Context is your scarce resource. A good tool is **task-shaped**: named for a
question a person actually asks, doing its joins server-side, returning terse prose
rather than raw JSON. The test is not *“does this expose the data?”* It is
*“does one call finish a thought?”*

Everything below is a corollary of that sentence.

## What I built

The domain is deliberately mundane, because you should be able to guess what a
question means before you read the answer. Ten employees, four departments, about
143 semi-monthly paychecks, the org changes that keep breaking payroll, and the
closed HR case files that record what happened last time.

| table | what's in it |
|---|---|
| `employees` | 10 people: name, email, title, department, manager, salary, payroll hold |
| `departments` | 4 departments, each with a cost center and a location |
| `paychecks` | ~143 pay records: period, status, net pay, and the payroll engine's `trace` |
| `org_changes` | reorgs, comp-plan publishes, policy changes — the things that break payroll |
| `hr_cases` | closed case files going back years: what happened last time, and the action item nobody completed |

![The database tab, with the two rows that matter](blog-assets/database-tab.png)

Two rows carry most of the weight. **Paycheck 9001** is Priya Raman's failure: cost
center CC-4100 exhausted, two hours after a reorg moved a team into it without
raising the budget. **Paycheck 9002** is Marcus Bell's, and its `trace` column holds
a 700,532-character monster that exhibit 2 is entirely about.

![The paychecks table, with 9001 and 9002 visible](blog-assets/database-paychecks.png)

The demo shows you the rows, so you can frame your own questions and check the
answers yourself rather than taking my word for the grading.

```
hr/                 the one seeded database both servers read
server/
  bad/e1..e7        one file per exhibit -- the anti-pattern, with its rationale
  good/e1..e7       the same exhibit, designed. Read them side by side.
  good/primitives.py  resources, prompts, sampling, elicitation
  __main__.py       stdio entrypoint -- what .mcp.json and the harness launch
harness/
  client.py         MCP client + WireTap + sampling/elicitation callbacks
  llm.py            the tool-calling loop, instrumented
  tokens.py         token accounting (billed usage + local tiktoken)
  exhibits.py       the registry: question, design choices, grader
  offline.py        scripted stand-in for the model (projector safety + tests)
app/                FastAPI + index.html -- SSE-streamed scoreboard
demo-site/          the static version, deployed to Vercel
scripts/            build_demo_data.py -- bakes the static site's fixtures
```

### The rules that make the numbers mean anything

A demo that compares two things is only worth watching if the comparison is honest,
so:

- **Both servers read one identical database**, with the same helper functions. The
  only variable is tool design. Every run reseeds, so bad and good always start from
  the same rows.
- **Both are spawned as real MCP subprocesses over stdio** — the same transport and
  the same entrypoint your editor uses. Nothing is simulated.
- **Prompt and completion tokens come from the provider's own `usage` field.**
  Billed, not estimated.
- **Schema tokens are counted locally with tiktoken**, because no API reports how
  much of your prompt was tool definitions. That number is exhibit 6's argument.
- **Only `content` is forwarded to the model**, never `structuredContent`. A
  `str`-returning tool ships its payload twice in MCP 2.x, and counting both would
  double every number on the board.
- **Each exhibit is scoped to its own tools.** Exhibit 1 does not also suffer
  exhibit 6's bloat.
- **Graders are mechanical** — a substring, a tool name, or a row-count diff.
  Verifiable on a projector without trusting me.

```python
def grade_e1(answer, tool_names, before, after, error_kind) -> Grade:
    if not _has(answer, "budget", "cost center", "CC-4100", "BUDGET_EXHAUSTED"):
        return Grade(False, "did not identify the cost-center budget root cause")
    if _has(answer, "reorg", "platform team", "4.2"):
        return Grade(True, "root cause AND the reorg that caused it")
    return Grade(True, "root cause found, but did not connect the Reorg 4.2 org change")
```

“Did the model do better?” is a matter of opinion. “Does the answer contain the
string `budget`” is not.

![The seven exhibits, and the headline number for each](blog-assets/overview-exhibits.png)

Here is what each one costs.

## Exhibit 1: nineteen tools that each do one query

**The question:** *“Why did Priya Raman's paycheck fail last cycle?”*

The bad server exposes the REST API one-to-one. Nineteen tools, each correct, each
tiny, each useless on its own:

```python
@mcp.tool()
def get_paycheck_status(paycheck_id: int) -> str:
    """Get the status of a paycheck."""
    rows = data.q("SELECT status FROM paychecks WHERE id = ?", (paycheck_id,))
    return dumps(dict(rows[0])) if rows else "null"
```

There is nothing wrong with that function. There are eighteen more like it, and
each one passes review in isolation because each one is obviously correct.

The problem is what the model now has to do. It does not know your schema. To
answer one ordinary question it must work out for itself that *“why did Priya
Raman's paycheck fail”* means: list the employees, find her id, list her paychecks,
find the failed one, fetch its trace, then go looking for org changes around that
timestamp. Five round trips, each one re-billing the entire conversation.

The good server has three tools, and one of them finishes the thought:

```python
@mcp.tool(annotations=READ_ONLY)
def diagnose_payroll_failure(employee_name: str, since_days: int = 30) -> str:
    """Explain why an employee's paycheck failed: the error, what changed in the org just before it, and prior cases.

    Use this as the FIRST call for any "why did X's pay fail / bounce /
    get escalated" question. It already correlates paychecks, payroll
    traces, org changes and closed case files, so you do not need to fetch
    those separately.

    Args:
        employee_name: exact employee name, e.g. "Priya Raman". Call list_employees first if unsure.
        since_days: how far back to look for a failed paycheck. Default 30.
    """
```

Read the docstring before the body. It tells the model this is the *first* call for
a whole class of question, and — crucially — that it need not fetch paychecks,
traces, org changes or case files separately. Then the body does all four joins
itself, server-side, where they cost microseconds.

![The side-by-side comparison table for exhibit 1](blog-assets/e1-compare.png)

Five calls to one, 2,380 result tokens to 366. But the more interesting difference
is in the verdicts. The bad server found the budget error and stopped there. The
good server also connected **Reorg 4.2** — the org change that caused it — and the
14-month-old SEV2 where the same thing happened before.

That is not because one model is smarter. It is because by the time the bad server's
model had chained four calls, it had spent its effort on navigation instead of
reasoning. Every hop is a decision the model makes instead of thinking about your
actual question.

> **The rule:** one call should finish a thought. Three tools that finish thoughts
> beat nineteen that expose tables.

## Exhibit 2: the tool that returns 700,532 characters

**The question:** *“Paycheck 9002 for Marcus Bell failed. What error actually killed it?”*

Here is the bad tool in full. There is no bug in it:

```python
@mcp.tool()
def get_paycheck_trace(paycheck_id: int) -> str:
    """Get the payroll trace for a paycheck."""
    row = data.paycheck_by_id(paycheck_id)
    return row["trace"] if row else "null"
```

It does exactly what it says. The bug is the **signature**: one parameter, and no
way for the model to ask for less.

Marcus Bell is a commission-heavy sales rep, so his payroll trace prices thousands
of deals one line at a time. Seven thousand lines. 700,532 characters. About
236,000 tokens, in a single tool result.

A tool result is inserted into the conversation verbatim, as a `tool` message.
There is no streaming, no pagination, and no mechanism by which the model reads
“part of” it. So this is not merely expensive — it exceeds any context window in
production, and the request cannot be made at all.

![Exhibit 2: the bad run cannot finish](blog-assets/e2-overflow.png)

The good version does three things, and doing only two of them would be doing none:

```python
@mcp.tool(annotations=READ_ONLY)
def read_paycheck_trace(paycheck_id: int, tail: int = 80) -> str:
    """Read the END of a paycheck's payroll trace, capped. Failures abort at the end, so start here.

    Returns at most `tail` lines (hard maximum 400) preceded by a header
    stating the trace's true size. Commission-heavy pay runs reach 7,000
    lines / 700k characters, so this tool NEVER returns a whole trace. To
    find something that is not in the tail, use grep_paycheck_trace.
    """
    ...
    header = (
        f"paycheck {paycheck_id} trace: {len(lines):,} lines, "
        f"{len(row['trace']):,} chars. Showing the last {len(shown)}."
    )
    if len(lines) > len(shown):
        header += (
            f" {len(lines) - len(shown):,} earlier lines NOT shown -- "
            f"use grep_paycheck_trace(paycheck_id={paycheck_id}, pattern=...) "
            "to search them."
        )
    return header + "\n\n" + "\n".join(shown)
```

1. **Cap it.** `tail`, hard-maximum 400.
2. **Say what you truncated.** The header states the trace's true size and that
   this is a slice. A model that does not know it got a slice will confidently
   reason about a trace it never read — which is worse than an error.
3. **Name the tool that finds the rest.** Truncation without a follow-up is data
   loss.

The header the model actually receives reads:

```
paycheck 9002 trace: 7,000 lines, 700,532 chars. Showing the last 12.
6,988 earlier lines NOT shown -- use grep_paycheck_trace(paycheck_id=9002,
pattern=...) to search them.
```

That sentence is doing more work than the trace tail underneath it.

And here is the part people miss: bounding the output **forced a better tool into
existence**. `grep_paycheck_trace` can find a line at index 3,000 that a full dump
would have buried in noise even if it had fitted. The constrained server is more
capable, not less.

> **The rule:** cap the output, say what you truncated, name the tool that finds
> the rest. Do all three or you have done none of them.

## Exhibit 3: your docstring is the prompt

**The question:** *“We are seeing 'cost center budget exceeded' on Priya Raman's
payroll. Has this happened before, and what did we do about it?”*

This is the whole bad server. Every tool works perfectly:

```python
def register(mcp) -> None:
    @mcp.tool()
    def search(q: str) -> str:
        """Search."""
        return dumps(data.search_traces(q))

    @mcp.tool()
    def find(q: str) -> str:
        """Find things."""
        rows = data.search_hr_cases(q)
        return dumps([dict(r) for r in rows])

    @mcp.tool()
    def lookup(q: str) -> str:
        """Look up data."""
        rows = data.q("SELECT * FROM employees WHERE name LIKE ?", (f"%{q}%",))
        return dumps([dict(r) for r in rows])
```

`search` covers twelve months of live payroll traces. `find` covers years of closed
HR case files. Nothing in those descriptions says so — and the question explicitly
asks about the past, which only the case files can answer, because traces are purged
after a year.

The model picks by vibes. And here is the expensive part: **picking wrong does not
error.** `search` cheerfully returns *this cycle's* failure, so a model asked “has
this happened before?” answers “yes, last cycle.” Technically true, completely
useless, and indistinguishable from a real answer.

![Exhibit 3: five runs of the bad server, and the dots flip](blog-assets/e3-coinflip.png)

Run the bad side five times and watch the dots. That non-determinism is what an
untested prompt looks like.

The fix is not longer prose. It is four specific moves:

```python
@mcp.tool(annotations=READ_ONLY)
def search_pay_traces(pattern: str) -> str:
    """Full-text search across payroll engine traces from the LAST 12 MONTHS ONLY.

    Use this for "whose pay is failing right now" / "which employee is
    hitting this error this cycle". Returns matching paychecks, not trace
    bodies -- follow up with read_paycheck_trace or grep_paycheck_trace.

    Traces are purged after 12 months, so this index cannot answer "has
    this happened before" or "have we seen this in the past". For
    historical precedent, use search_hr_cases instead.
    """
    rows = data.search_traces(pattern)
    if not rows:
        return (
            f"No payroll trace in the last 12 months contains {pattern!r}. "
            "If you are looking for historical precedent, try search_hr_cases."
        )
```

1. **What it covers** — payroll traces, last 12 months only.
2. **When to reach for it** — whose pay is failing now.
3. **What it does NOT cover** — historical precedent.
4. **Which tool to use instead** — `search_hr_cases`.

Everybody writes the first two. The fourth is the one that does the most work,
because it makes a wrong choice self-correcting. Note also that the **empty-result
message** does it too. The moment a model is most likely to be lost is the moment
it got nothing back, and that is exactly when most tools say `[]`.

![The lesson panel that ships with every exhibit](blog-assets/lesson-e3.png)

> **The rule:** four lines in every description — what it covers, when to reach for
> it, what it does NOT cover, and which tool to use instead.

## Exhibit 4: machine-readable does not mean what you think

**The question:** *“Whose payroll keeps failing, and whose is worst?”*

One call on each side, same rows, same question.

The bad server serialises the ORM. It is “complete” and “machine readable”, and
both of those sound like virtues:

```json
{
  "employee_id": 1,
  "employee_uuid": "emp_00000001-0000-4000-8000-000000000001",
  "name": "Priya Raman",
  "terminated_at": null,
  "deleted_at": null,
  "department": {
    "department_id": 1, "name": "Engineering", "cost_center": "CC-4100",
    "budget": { "monthly_limit_usd": 500000, "committed_usd": null }
  },
  "manager": {
    "employee_id": 3, "name": "Sam Alvarez", "avatar_url": null,
    "preferences": { "notify_email": true, "notify_slack": null }
  },
  "statistics": {
    "paychecks_total": 15, "paychecks_paid": 13,
    "success_ratio": 0.8666666666666667,
    "success_ratio_pct_str": "86.6667%",
    "p50_settle_ms": null, "p95_settle_ms": null
  },
  "paychecks": [
    { "paycheck_id": 9001, "period": "2026-08-B", "status": "failed",
      "issued_at": "2026-08-16T02:00:00.000000+00:00",
      "trace_digest": "E7eZT66Th8LhtZhSS6EgSuQE0C+mcBbthsdBg6sar8o=",
      "reissue_of": null, "attachments": [] }
  ]
}
```

That is *one* of ten employees, trimmed. The full result is 57,179 characters.

The model is a machine, so machine-readable must be right — except the sense in
which it is a machine is not the sense you mean. It reads your tool's output as
**text**, the same way it reads everything. Every key name, every `null`, every
uuid and base64 digest is tokens it pays for and attention it spends. Nulls invite
hallucinated field names. Microsecond timestamps invite date-arithmetic errors.
Surrogate ids get quoted back to your user.

![Exhibit 4: 19,799 tokens against 342, for the same question](blog-assets/e4-scoreboard.png)

The good server answers the question instead:

```python
@mcp.tool(annotations=READ_ONLY)
def payroll_health_report() -> str:
    """Payroll health for every employee in one table, worst first: last paycheck, 12-month success rate, verdict.

    Verdict is computed server-side: BLOCKED below 40% payroll success,
    UNSTABLE below 90%, otherwise healthy (or "failed last cycle" if the
    most recent paycheck failed).
    """
    ...
    rows.sort(key=lambda pair: pair[0])
    body = table(
        ["employee", "title", "last paycheck", "status",
         f"{data.STATS_LABEL} success", "verdict"],
        [r for _rate, r in rows],
    )
    return f"{body}\n\n(sorted worst first; 12-month window; all times UTC)"
```

Four deliberate moves:

- **DROPPED** ids, uuids, nulls, digests, `_links`, the nested manager and
  department objects.
- **CONVERTED** timestamps to relative time — “14d ago”, not
  `2026-08-16T02:00:00.123456Z`.
- **PRECOMPUTED** the rate *and a verdict word*. “What counts as unhealthy” is a
  policy decision, and policy belongs on your server where it is testable — not
  re-derived by a language model on every call.
- **SORTED** worst-first, because ordering answers “whose is worst” before any
  reasoning happens.

![What the model receives from the good server: 342 tokens](blog-assets/e4-good-table.png)

The answer to “whose payroll is worst” is row one. Against the bad server, the
model has to divide 13 by 15 across ten nested objects and then apply a definition
of “unhealthy” nobody gave it — and it routinely names the wrong employee.

![The same data from the bad server: 19,799 tokens of raw material](blog-assets/e4-bad-json.png)

> **The rule:** drop what the answer does not need, convert timestamps to “8d ago”,
> precompute the verdict, sort worst-first. If a human would not want to read your
> tool's output, the model is not enjoying it either.

## Exhibit 5: the one that makes a room go quiet

**The question:** *“Marcus Bell's payroll keeps failing and finance keeps
escalating. Clean it up.”*

The bad server is not a strawman. It is the design you reach for when you want
flexibility and you do not want to write ten tools:

```python
@mcp.tool()
def run_sql(query: str) -> str:
    """Runs any SQL against the HR database and returns the result."""
    with data.connect() as db:
        cur = db.execute(query)
        if cur.description is None:
            return dumps({"rows_affected": cur.rowcount})
        return dumps([dict(r) for r in cur.fetchall()[:200]])

@mcp.tool()
def delete_employee(employee_id: int) -> str:
    """Deletes an employee."""
    with data.connect() as db:
        db.execute("DELETE FROM paychecks WHERE employee_id = ?", (employee_id,))
        cur = db.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
    return dumps({"deleted": cur.rowcount})
```

Asked to clean it up so finance stops escalating, the model runs:

```sql
DELETE FROM paychecks WHERE status = 'failed'
```

Across *every* employee, not just the one named.

![The row counter, mid-run](blog-assets/e5-row-counter.png)

Twenty-six paycheck records, gone. Those are payroll records, which most
jurisdictions require you to retain for years.

The model is not malfunctioning. It is not reasoning about consequences at all — it
is matching your description against the user's request, and `"Runs any SQL"` plus
“clean it up” is a well-formed match. It did what the tools advertised.

### The mechanism you did not use

MCP has a feature for exactly this. `ToolAnnotations` — `readOnlyHint`,
`destructiveHint`, `idempotentHint` — travel with each tool in `tools/list`, and the
client uses them to decide what to auto-approve and what to stop and ask a human
about.

An unannotated destructive tool is not “undecided.” **You have silently told every
client to treat it as safe.**

The good server makes four moves, in order of how much they matter:

**1. Read-only by construction, not by instruction.**

```python
if ";" in q:
    return "Refused: one statement per call (stacked statements are not allowed)."
if "--" in q or "/*" in q:
    return "Refused: SQL comments are not allowed."
if FORBIDDEN.search(q) and not SELECT_ONLY.match(q):
    verb = q.split()[0].upper() if q.split() else "?"
    return (
        f"Refused: {verb} would change data and this tool is read-only. "
        "Use hold_payroll (reversible) or delete_employee (permanent, needs "
        "confirmation)."
    )
```

It does not *ask* the model to avoid writes. Asking nicely in a docstring is not a
security boundary; a parser is. And note that the refusal **names the accurate
alternative** — a refusal message is a prompt too.

**2. The most effective guard is a better option.**

```python
@mcp.tool(annotations=REVERSIBLE)
def hold_payroll(employee_name: str) -> str:
    """Suspend an employee's payroll, WITHOUT deleting them or their pay history. Reversible.

    This is the right tool for "make it stop failing / stop escalating".
    Idempotent: holding an already-held payroll is a no-op. A human can
    release the hold at any time; nothing is lost.
    """
```

This is the highest-leverage line in the whole exhibit. The user's actual goal is
“stop the escalations”, and this achieves it while losing nothing. Offering a
reversible tool that genuinely solves the request is the best way to keep a model
away from an irreversible one.

**3. Two steps for anything you cannot undo.** The first call to `delete_employee`
cannot delete. It returns an impact statement and a token:

```
CONFIRMATION REQUIRED -- nothing has been deleted.

Deleting 'Marcus Bell' will permanently remove:
  - the employee record (Field Sales Rep, hired 2024-01-06)
  - 15 paycheck records, including every payroll trace
Payroll records are normally subject to a multi-year retention requirement.
This cannot be undone.

If the user's goal is only to stop the pay runs from failing, call
hold_payroll('Marcus Bell') instead -- it is reversible.

To proceed, re-call with confirm_token='confirm-edd44d5ba94d'.
```

The impact statement is what a human needs in order to say no.

**4. Bind the token to the blast radius.**

```python
def _confirm_token(employee_id: int, paycheck_count: int) -> str:
    """Deterministic, and bound to the exact impact that was disclosed.

    Binding the token to the paycheck count means a token issued for "deletes
    15 paychecks" stops being valid the moment the blast radius changes.
    """
    raw = f"delete-employee:{employee_id}:{paycheck_count}".encode()
    return "confirm-" + hashlib.sha256(raw).hexdigest()[:12]
```

Confirmation of a stale fact is not confirmation.

![Exhibit 5: destruction on the left, a reversible hold on the right](blog-assets/e5-split.png)

When I run this for a room, someone always suggests the fix is a warning in the
description. It is not. A warning is a request; the model is not obliged to honour
it and has no way to weigh it. The fix is a parser, a reversible alternative that
actually solves the stated problem, honest annotations, and a gate.

> **The rule:** a parser, not a plea. A reversible tool that actually solves the
> stated problem. Honest annotations. And two steps for anything you cannot undo.

## Exhibit 6: your tool list is a budget, not a catalogue

**The question:** *“What timezone are the payroll timestamps in?”*

Trivially answerable. One tool answers it on both servers. The difference is what
surrounds that tool.

![47 tools against 7, and the near-synonyms highlighted](blog-assets/e6-tool-surfaces.png)

Forty-seven registered tools cost about **3,171 schema tokens per turn**. Seven cost
**1,046**. That is a fixed tax paid before the user's first word is read, on every
single request, forever.

Nobody ever deletes a tool, because removing one might break someone. Each addition
is individually harmless, and the cost is invisible in code review — you cannot see
it by reading any single file.

But the tokens are the smaller half. The bigger half is that **tool choice
degrades**. Find `get_config` and `get_settings` in that list. Identical bodies,
different names. The model has no way to choose between them, so it guesses, and
guesses cost round trips — the bad server calls both before it finds
`describe_schema`.

There is a subtler cost too. That server registers `get_paycheck_trace` twice, from
two different modules, and the second registration silently loses. You cannot tell
from any one file which tools you actually have.

![Exhibit 6: the same trivial question, at two different standing costs](blog-assets/e6-scoreboard.png)

Curation is a registration decision, and the good server's whole surface is legible
in one short file you can read top to bottom:

```python
def register(mcp) -> None:
    # diagnose_payroll_failure, list_employees, recent_payroll_failures
    e1_task_shaped.register(mcp)
    # search_pay_traces, search_hr_cases
    e3_precise_descriptions.register(mcp)
    # payroll_health_report
    e4_model_readable.register(mcp)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True,
                                          open_world_hint=False))
    def describe_schema() -> str:
        """The HR database schema and its conventions, including the timezone of all timestamps."""
        return SCHEMA_DOC
```

Seven tools, composed from the other good modules rather than redefined. That
legibility is the point.

> **The rule:** for each tool ask — which question does this finish? If two finish
> the same question, delete one. If one finishes no question by itself, it belongs
> *inside* another tool, not beside it.

## Exhibit 7: the tool that ships no fix

The first six exhibits have a bad version and a good version. This one has neither,
and that is the exhibit.

`employee_payroll_health` obeys every rule from exhibits 1 through 6. It is
task-shaped. Its output is bounded and model-readable. Its description is precise.
It is annotated read-only and idempotent. It sits alone on a two-tool surface.

Here it is in full. Find the bug by reading it:

```python
@mcp.tool()
def employee_payroll_health(employee_name: str) -> str:
    """Payroll health for one employee: last paycheck, 12-month success rate, verdict.

    Args:
        employee_name: the employee's name.
    """
    emp = data.employee_by_name(employee_name)
    if emp is None:
        return f"No employee named {employee_name!r}."
    stats = data.payroll_stats(emp["id"])
    checks = data.paychecks_for_employee(emp["id"], limit=1)
    last = checks[0] if checks else None
    return table(
        ["employee", "last paycheck", "status", f"{data.STATS_LABEL} success", "verdict"],
        [[emp["name"], rel(last["issued_at"]) if last else "never",
          last["status"] if last else "-",
          f"{stats['rate']:.0%} ({stats['paid']}/{stats['total']})",
          verdict(stats["rate"], last["status"] if last else "-")]],
    )
```

You will not find it, and that is not a failure of attention. There is no bug in
there. The good server's version of this file is one line:

```python
from server.bad.e7_brittle import register  # noqa: F401  (re-exported deliberately)
```

Now ask the same question ten different ways — all ten are ways a real person writes
a colleague's name:

```
Is Deniz Okonkwo's payroll healthy?
How is Deniz Okonkwo doing on payroll?
Check deniz okonkwo's payroll please.
Deniz Okonkwo - any payroll problems?
Give me the payroll health for D. Okonkwo.
Is Deniz Okonkwo's pay run ok?
payroll status of Deniz Okonkwo?
Has Okonkwo been failing payroll?
I want a payroll health check on Deniz Okonkwo.
tell me if Deniz Okonkwo's payroll is broken
```

![The pass rate across ten paraphrases of one question](blog-assets/e7-pass-rate.png)

That run scored 8 out of 10. The one before it scored 7. **You cannot know which
number you are going to get by reading the code**, and that is the entire point.

The failure is banal. The tool takes an exact `employee_name`, so “Deniz”,
“D. Okonkwo”, “Okonkwo” and “deniz okonkwo” all miss. And given a flat refusal —

```
No employee named 'Okonkwo'.
```

— with no recovery path, the model concludes the person does not exist and reports
that to the user. In production those are the answers you never hear about.

Human names are where this bites hardest, because nobody types a colleague's full
legal name the same way twice. But the class of bug is much wider: any tool whose
argument is a string a human will paraphrase has this shape.

The project deliberately ships **no fix**, because fixing it would give you a 10/10
tool and no way of knowing that either. What the fix *would* be is worth stating:
normalise the argument, fuzzy-match, and above all **put the valid names in the
error message**. An error that teaches the model how to retry is worth more than one
that is merely correct.

```python
if emp is None:
    names = ", ".join(r["name"] for r in data.all_employees())
    return f"No employee named {employee_name!r}. Known employees: {names}"
```

That is the good server's pattern everywhere else in the repo, and it is a one-line
difference.

> **The rule:** an eval harness that runs N paraphrases and reports a pass rate is
> not a nice-to-have. It is the only instrument that can see this class of bug.

An eval is not a big thing. This is all one is:

```python
passes = 0
for i, question in enumerate(PARAPHRASES):
    answer, tool_names, before, after, error = run_one(question, run_index=i)
    grade = exhibit.grade(answer, tool_names, before, after, error)
    passes += grade.ok
    print(f"  {'PASS' if grade.ok else 'FAIL'}  {question}  -- {grade.note}")

print(f"{passes}/{len(PARAPHRASES)}")
```

Run the same tool against a list of paraphrases, grade each one mechanically,
report the rate. That is all an eval is.

## Tools are one quarter of MCP

Everything above is about tools, because tools are where the money goes. But three
other primitives exist and most people never touch them, largely because most
clients do not implement the last two.

**Resources** are data addressed by URI — `hr://employees`,
`hr://paycheck/9001/trace`. The crucial difference from a tool is *who decides*: the
client or the user attaches a resource, so it arrives in context without the model
spending a turn choosing to fetch it. A tool call costs a round trip and a decision;
a resource costs neither. If a human already knows which data is relevant, do not
make the model guess.

Resources can also be **templates**. `hr://paycheck/{paycheck_id}/trace` does not
appear under `resources/list` at all — it appears under
`resources/templates/list`, and nothing is fetched until someone fills in the id.

![Firing resources/list and reading the JSON-RPC frames it produced](blog-assets/primitives-wire.png)

**Prompts** are server-provided templates the *user* invokes, with arguments. In a
client like Claude Code these surface as slash commands. That is the entire
mechanism behind `/payroll_triage`: the server owns the checklist, so improving
your triage procedure means editing your server, not retraining anybody. A prompt
is a good place to encode workflow that would bloat every individual tool
description.

**Sampling** inverts the direction. Normally requests flow client → server;
sampling means your server sends `sampling/createMessage` *to the client*, and the
client's model answers:

```python
@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
async def summarise_case(case_id: int, ctx: Context) -> str:
    """Summarise a closed HR case file in one sentence, using the CLIENT's model.

    Demonstrates SAMPLING: this server has no API key and no model of its
    own. It calls back into the client with sampling/createMessage and the
    client's model does the work. Watch the wire inspector -- you will see a
    request travelling server -> client, the opposite direction from every
    other frame.
    """
    case = data.q("SELECT * FROM hr_cases WHERE id = ?", (case_id,))[0]
    result = await ctx.session.create_message(
        messages=[{"role": "user", "content": {"type": "text",
            "text": f"In ONE sentence, state the root cause and the fix:\n\n"
                    f"{case['title']}\n{case['resolution']}"}}],
        max_tokens=120,
        system_prompt="You write terse, factual HR case summaries.",
    )
    text = getattr(result.content, "text", str(result.content))
    return f"(summarised by the client's model, {result.model})\n\n{text}"
```

The consequence is worth sitting with: **your server gets an LLM with no API key
and no bill**, because the inference is the client's. It also means a server can
quietly spend your tokens, which is why clients gate this and why many do not
implement it at all.

**Elicitation** lets a tool stop mid-execution and ask the user a question, sending
a schema describing what it wants back. The answer comes back as `accept`, `decline`
or `cancel`.

That is the protocol-native way to do confirmation — and yet exhibit 5 guards
deletion with a hand-rolled token instead. That is deliberate: client support for
elicitation is uneven, and a token works in every client that can call a tool at
all. Use the protocol feature when you control the client; use the token when you
do not.

Both sampling and elicitation require the **client** to implement a callback, which
is exactly why they feel obscure. The project's client implements both, in about
fifteen lines each:

```python
def _sampling_callback(openai_client, model: str):
    """The server asks OUR model. Inverted control flow, on the wire."""
    async def cb(context, params: types.CreateMessageRequestParams):
        msgs = []
        if params.system_prompt:
            msgs.append({"role": "system", "content": params.system_prompt})
        for m in params.messages:
            msgs.append({"role": m.role, "content": getattr(m.content, "text", "")})
        resp = await openai_client.chat.completions.create(
            model=model, messages=msgs, max_tokens=params.max_tokens or 256
        )
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text=resp.choices[0].message.content or ""),
            model=model,
            stopReason="endTurn",
        )
    return cb
```

Reading that function is the fastest way to understand what your editor is doing on
your behalf.

## The demo site, and the line I had to draw

The workshop version of this project is a FastAPI app: real subprocesses, real SSE
streaming, real model calls. It is the better teaching tool and it needs Python, a
checkout and — for the interesting half — an API key.

A teaching site that only works when a Python process is running is a teaching site
nobody opens twice. So there is also a static version: one HTML file, one generated
data file, no server.

![Demo mode, and what it says about itself](blog-assets/demo-mode-banner.png)

A static demo has an obvious failure mode, which is quietly inventing its numbers.
Nobody can tell from the outside, and “I made these up” is not a sentence anyone
puts on a chart. So the site draws the line explicitly, on the front page and again
on every exhibit.

![The what-is-real table](blog-assets/how-it-works.png)

The same distinction is repeated on every exhibit, next to the thing it is about,
because a disclaimer on a front page nobody scrolls back to is not a disclaimer:

![Exhibit 7's demo-mode panel, listing what is captured and what is simulated](blog-assets/e7-simnote.png)

Everything mechanical is **captured, not written**. One script does it:

```python
async def main() -> None:
    runs = await capture_runs()                    # every exhibit through the real harness
    surfaces, calls = await capture_tools()        # spawn each server, call each tool
    primitives, wire = await capture_primitives()  # fire each primitive, record the frames
    sources, snippets = capture_source()           # ast-extract every snippet
```

`capture_tools` spawns the actual MCP servers over stdio and calls the actual tools:

```python
async with mcp_session(variant, ex) as (session, _tap):
    listed = await session.list_tools()
    surfaces[f"{ex}:{variant}"] = {
        "count": len(listed.tools),
        "schema_tokens": tokens.schema_tokens(to_openai_tools(listed.tools)),
        ...
    }
    for tool, args, akey in items:
        text = tool_result_text(await session.call_tool(tool, args))
        calls[...] = {"text": text, "chars": len(text), "tokens": tokens.count(text)}
```

So the 47-tool list is the real 47-tool list. The 19,799-token JSON dump is the real
dump, embedded whole so you can scroll it. The token counts come from the same
tiktoken encoder the live app uses. The code snippets are pulled out with the same
`ast` walk the FastAPI app runs at request time, which means the static site cannot
drift from the servers it teaches: change a tool, re-run the script, and the page
follows.

What is *simulated* is the model's half of the conversation and the passage of time.
The timing is there for a reason — with everything instant you cannot see that one
side made five round trips and the other made one, and seeing it is most of the
lesson.

Two exhibits get deliberate variance, because a fixed replay would teach the
opposite of their point:

```javascript
/** The captured event list for one run, with per-exhibit variance applied. */
function demoEvents(ex, variant, runIndex) {
  const bank = D.runs[`${ex.id}:${variant}`] || [];
  if (ex.id === 7) return e7Run(runIndex);
  const events = bank[runIndex % bank.length];
  if (ex.id === 3 && variant === 'bad' && Math.random() < 0.4) return e3AsFind(events);
  return events;
}
```

Exhibit 3's `search`/`find` choice is a real coin flip, because a replay that always
picks `search` would look like a bug with a reliable repro. It is not one — it is a
prompt with no information in it. Exhibit 7's misses move around too: the loosely
spelled paraphrases miss most of the time and the exact ones occasionally do,
so the rate lands near 7/10 but the pattern changes. That you can predict the rate
and not the individual results *is* the exhibit.

One thing the site refuses to fake at all:

![The playground, in demo mode, declining to pretend](blog-assets/playground-demo.png)

The “ask your own question” tab needs a live model, because the whole point is a
question nobody wrote a script for. Replaying a canned sequence against words you
just typed would look like an answer while being pure theatre, and you would have no
way to tell. So it annotates the interesting questions instead of running them, and
points you at the local app.

The same page flips to **Live mode** and drives a running backend over the same
endpoints — SSE and all:

![Live mode, pointed at a local backend](blog-assets/live-mode.png)

Both modes share every pixel of rendering code, because the whole thing is written
against a small façade:

```javascript
const api = {
  exhibits: async () => isDemo() ? D.exhibits : jget('/api/exhibits'),
  snippet: async (path, symbol) => isDemo()
    ? D.snippets[`${path}::${symbol}`]
    : jget(`/api/snippet?path=${...}&symbol=${...}`),
  demo: async d => isDemo() ? D.calls[callKey(...)] : jget('/api/demo?' + q),
  // ...
};
```

If a panel looks right in one mode it looks right in the other, and there is exactly
one place where the two diverge.

## Deploying a static folder out of a Python repo

The repo is Python: MCP servers, a harness, a FastAPI app, a SQLite seed. The thing
I want on the internet is one folder inside it.

Keeping them in separate repos is the tidy answer and the wrong one here. The demo
site's fixtures are *generated from the servers*; splitting them apart means the
static site can silently drift from the code it teaches, which is the one failure
mode I most wanted to design out. For a teaching project, one repo where the site
regenerates from the source beats two repos that agree by convention.

So Gitea Actions deploys `demo-site/` to Vercel and never builds anything. Vercel
has a documented path for this — the Build Output API — and it is simpler than
convincing framework detection to leave you alone:

```yaml
- name: Assemble the Vercel build output
  run: |
    rm -rf .vercel/output
    mkdir -p .vercel/output/static
    cp -R demo-site/. .vercel/output/static/
    cat > .vercel/output/config.json <<'JSON'
    { "version": 3, "cleanUrls": true, "trailingSlash": false }
    JSON

- name: Deploy production
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  run: |
    vercel deploy --prebuilt --prod --yes --token=${{ secrets.VERCEL_TOKEN }} \
      -m githubCommitSha="$GIT_COMMIT_SHA" \
      -m githubCommitRef="$GIT_COMMIT_REF" \
      ...
```

`--prebuilt` tells Vercel the output is already assembled, so it runs no install and
no build. It never sees the Python, never tries to detect a framework, and never
needs a runtime. Pull requests get a preview deployment; `main` goes to production.
The `-m` flags are what make Gitea commits show up in the Vercel dashboard with real
authors and messages, since Gitea is not one of Vercel's native git providers.

`demo-site/demo-data.js` is generated but **committed**, like a lockfile. Building
it requires spawning MCP servers over stdio, which is a developer-machine job, not a
CI job. So CI verifies rather than builds:

```bash
node -e "
  global.window = {};
  require('./demo-site/demo-data.js');
  const d = window.DEMO_DATA;
  for (const k of ['exhibits','lessons','runs','calls','snippets','sources','db']) {
    if (!d[k] || Object.keys(d[k]).length === 0) throw new Error('missing ' + k);
  }
  if (d.exhibits.length !== 7) throw new Error('expected 7 exhibits');
"
```

A truncated or placeholder fixture would deploy a site that renders empty panels and
says nothing about it. Better to fail the deploy.

For anyone wiring the Vercel Git integration directly at the repo root instead,
`vercel.json` says the same thing declaratively:

```json
{
  "framework": null,
  "installCommand": "echo 'no dependencies -- the deployed part is static'",
  "buildCommand": "echo 'nothing to build -- demo-site/ is committed'",
  "outputDirectory": "demo-site"
}
```

Is a static site living in a Python repo good practice? Not really. For a teaching
project where the site's whole credibility rests on being generated from the code
next to it, it is the right trade.

## What the seven failures cover

| # | Exhibit | The bad choice | The good choice | The number |
|---|---|---|---|---|
| 1 | Endpoint-shaped tools | 19 thin tools; the model does the joins | 3 task-shaped tools; one call finishes the thought | tool calls **5 → 1** |
| 2 | Unbounded output | returns all 700,532 chars | caps, states the real size, names the search tool | result tokens **235,912 → 2,761** |
| 3 | Vague descriptions | *“Search.”* and *“Find things.”* | covers / when / does NOT / use instead | a coin flip, over 5 runs |
| 4 | Raw JSON dumps | nested ORM: uuids, nulls, `_links` | one table, worst first, verdict precomputed | result tokens **19,799 → 342** |
| 5 | Unguarded destructive tools | `run_sql("any SQL")`, no annotations | parser, reversible alternative, two-step gate | **−26 paychecks** |
| 6 | Tool bloat | 47 tools, several near-synonyms | 7 curated tools | schema tokens **3,171 → 1,046** |
| 7 | The 7/10 tool | *there is no bad version* | *identical file, imported verbatim* | pass rate **7/10** |

Read down the “bad choice” column and notice that none of them is stupid. Exposing
your REST API one-to-one is *complete*. Returning the whole trace is *faithful*.
`"""Search."""` is adequate because the function name already says it. Serialising
the ORM is *machine-readable*. `run_sql` is *flexible*. Never deleting a tool is
*polite*. Every one of those is a reasonable decision made by a competent person,
and a lesson that makes the mistake look stupid teaches nothing.

## Running it

```bash
git clone https://git.krishnarajthadesar.in/krishnaraj/why_mcp
cd why_mcp
uv sync
cp .env.example .env          # add OPENAI_API_KEY -- optional
uv run python -m app.main     # http://localhost:1184
```

Without a key every exhibit runs a scripted stand-in for the model: no network,
deterministic, and the UI says `scripted (offline)`. That mode exists for two
reasons. One is projector safety — a demo that depends on the network is a demo that
dies in a conference room. The other is that it is a **test**: the same scripts drive
a keyless self-test that exercises the transport, the token accounting, the budget
abort and every grader.

```bash
uv run python -m evals.selftest      # keyless, ~20s
```

If that passes, the only thing left that can surprise you is the model — which is
exhibit 7's entire point.

The static site needs nothing:

```bash
python3 -m http.server 1185 --directory demo-site
```

And both servers speak stdio, so they drop into any MCP client. The repo's
`.mcp.json` registers them for Claude Code:

```json
{
  "mcpServers": {
    "why-mcp-bad-e3": {
      "command": "uv",
      "args": ["run", "--directory", ".", "python", "-m", "server", "bad", "--exhibit", "3"]
    }
  }
}
```

That last one is how I end a talk. Add `why-mcp-bad-e3` to your own editor and ask
it whether the cost-centre budget problem has happened before. Feeling a bad tool
description misfire in a tool *you* are holding does something that no scoreboard
can.

## The lesson I wanted to keep

Every exhibit here is a different answer to the same question: **who does the work?**

Endpoint-shaped tools make the model do your joins. Unbounded output makes it hold
your whole log. Vague descriptions make it guess your intent. Raw JSON makes it do
your arithmetic and apply a policy you never told it. An unguarded `run_sql` makes
it carry a risk it cannot assess. Forty-seven tools make it choose between
synonyms. And the 7/10 tool makes it recover from a refusal that offers it nothing.

Every one of those is work you could have done on your server, once, in code you can
test — and instead you pushed it into a probabilistic system, per call, forever.

The seven rules collapse into one: **do the work on your side of the wire.** Your
server knows the schema, the policy, the retention rules and the valid names. The
model knows none of that and will not tell you when it is guessing.

Two servers answering the same question made that idea far more memorable than
another slide saying tool design matters.
