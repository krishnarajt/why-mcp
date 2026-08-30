# SPOILERS — every design choice, its fix, and the lesson

For the instructor and for AI coding agents asked to "fix the bad server".
**Keep it off the projector — let the audience guess which number moves.**

Every anti-pattern here is intentional. When fixing one, change ONLY what the
exhibit is about; the rest is deliberately plain and should stay that way.

**Exhibit 7 ships no fix, on purpose.** If asked to "fix" it, don't — the demo
depends on the flakiness staying in. The fix is described at the bottom so you
can *talk* about it.

The domain is an ordinary HR database — `employees`, `departments`,
`paychecks`, `org_changes`, `hr_cases` — chosen because everyone can guess what
a question means without being told. See [hr/data.py](hr/data.py) for the seed.

---

## 1. Endpoint-shaped tools

- **Bad:** [server/bad/e1_endpoint_shaped.py](server/bad/e1_endpoint_shaped.py)
  registers 19 tools that mirror the REST API — `list_employees`, `get_employee`,
  `list_paychecks`, `get_paycheck`, `get_paycheck_trace`, `list_org_changes`,
  `get_org_change`, `get_paycheck_error_code`… Each is a thin wrapper over one
  query returning raw JSON.
- **Why anyone builds it:** you already have routes, so you expose routes. It
  feels complete — every field is reachable — and it passes review because each
  tool is obviously correct.
- **What it costs:** answering "why did Priya Raman's paycheck fail last cycle?"
  needs `list_employees` → `list_paychecks` → `get_paycheck` →
  `get_paycheck_trace` → `list_org_changes`. Five round-trips, and each one
  re-bills the whole conversation so far. The bad server usually still gets the
  error right, but rarely connects **Reorg 4.2** — by then it has stopped looking.
- **Good:** [server/good/e1_task_shaped.py](server/good/e1_task_shaped.py) —
  `diagnose_payroll_failure(employee_name)` runs all four queries server-side and
  returns a briefing: error lines, org changes in the preceding 72h, matching
  closed cases.
- **Lesson:** the test for a tool is not "does it expose the data", it is
  **"does one call finish a thought?"** Three tools that finish thoughts beat
  nineteen that expose tables.

## 2. Unbounded output

- **Bad:** [server/bad/e2_no_truncation.py](server/bad/e2_no_truncation.py) —
  `get_paycheck_trace(paycheck_id)` returns the whole trace. Paycheck 9002
  belongs to Marcus Bell, a commission-heavy sales rep, so its trace prices
  thousands of deals one line at a time: 700,532 chars ≈ 235,912 tokens. There is
  no argument that would let the model ask for less.
- **Why anyone builds it:** it is faithful, and it works perfectly in testing
  where your fixture traces are 40 lines.
- **What it costs:** the run cannot complete. One tool result exceeds the entire
  context budget — and at 236k tokens it also overflows a real 128k window.
- **Good:** [server/good/e2_truncated.py](server/good/e2_truncated.py) — three
  rules, in priority order:
  1. **Cap the output.** `tail=80`, hard max 400. The abort is at the end anyway.
  2. **Say what you truncated.** The header states the true size and that this
     is a slice. A model that doesn't know it got a slice will confidently
     reason about a trace it never read.
  3. **Give it a next move.** The header names `grep_paycheck_trace`.
- **Lesson:** the good tool is not a weaker version of the bad one — it is
  *strictly more capable*, because grep can find a needle at line 3,000 that a
  full dump would have buried.

## 3. Vague descriptions

- **Bad:** [server/bad/e3_vague_descriptions.py](server/bad/e3_vague_descriptions.py)
  — `search(q)` documented as *"Search."* covers **payroll traces, last 12
  months** (they are purged after that); `find(q)` documented as *"Find things."*
  covers **closed HR case files, years of history**. Both names are plausible.
  Neither description says which.
- **What it costs:** the model picks by vibes, and *picking wrong does not
  error*. `search` cheerfully returns this cycle's failure (paycheck 9001), so
  the model reports the current problem as its own precedent. A silent wrong
  answer is the expensive kind. Run it five times and the choice flips.
- **Good:** [server/good/e3_precise_descriptions.py](server/good/e3_precise_descriptions.py)
  — same queries, same data, different words, following a formula:
  - WHAT it covers — *"payroll traces from the last 12 months ONLY"*
  - WHEN to reach for it — *"use for 'whose pay is failing right now'"*
  - WHAT IT DOES NOT — *"traces are purged after 12 months"*
  - WHERE TO GO INSTEAD — *"for historical precedent, use search_hr_cases"*
- **Lesson:** the description **is** the prompt for tool choice — the only
  control surface you have. That last line is the one everybody skips and the
  one that does the most work: a tool that names its sibling makes the wrong
  choice self-correcting. Also note both good tools say so in their *empty
  results* too.
- **Why the precedent is genuinely out of reach:** the SEV2 that explains
  everything is 417 days old, and trace retention is 365 days. The bad tool
  cannot find it even in principle — it is not that the model searched badly.

## 4. Raw JSON dumps

- **Bad:** [server/bad/e4_raw_json.py](server/bad/e4_raw_json.py) —
  `get_all_employee_payroll_stats()` serialises the ORM: nested `manager` objects
  with their own nested preferences, a nested `department` with a nested budget,
  `employee_uuid`, `terminated_at: null`, `deleted_at: null`, base64
  `trace_digest`, `_links`, microsecond timestamps. ~19,800 tokens.
- **What it costs:** the model must do arithmetic and ranking on raw material.
  Nulls invite hallucinated field names; microsecond timestamps invite date
  errors; the ids get quoted back at the user. It usually names the wrong worst
  employee.
- **Good:** [server/good/e4_model_readable.py](server/good/e4_model_readable.py)
  — ~342 tokens. Four moves:
  - **Dropped** ids, uuids, nulls, digests, `_links`, the nested manager and
    department objects. Noise is what gets hallucinated back.
  - **Converted** timestamps to `"8d ago"`. Models do date arithmetic badly.
  - **Precomputed** the rate *and a verdict word* (BLOCKED / UNSTABLE /
    healthy). "What counts as unhealthy" is a policy decision, and policy
    belongs on your server where it is testable.
  - **Sorted** worst-first. Ordering is free information: "whose is worst" is
    answered by row 1 before any reasoning happens.
- **Lesson:** if a human would not want to read your tool's output, the model is
  not enjoying it either.
- **Note on the size:** the bad payload is capped at 10 paychecks per employee so
  it lands at ~19,800 tokens — under the 24,000 context budget on purpose. If it
  overflowed, exhibit 4 would fail for exhibit 2's reason and teach the wrong
  lesson. It must reach a *wrong answer*, not no answer.

## 5. Unguarded destructive tools ⚠️

- **Bad:** [server/bad/e5_unguarded.py](server/bad/e5_unguarded.py) —
  `run_sql` (*"Runs any SQL"*), `delete_employee`, `delete_paychecks`. No
  `ToolAnnotations`, so the client has no reason to stop and ask. No
  confirmation, so there is no second chance.
- **What it costs:** asked to "clean it up so finance stops escalating", a
  helpful model runs `DELETE FROM paychecks WHERE status = 'failed'` — 26 rows
  across every employee, not just the one it was asked about. Those are payroll
  records, which most jurisdictions require you to retain for years. It is not
  malfunctioning. It is doing what the tools advertised.
- **Good:** [server/good/e5_guarded.py](server/good/e5_guarded.py), four choices
  in priority order:
  1. **Read-only by construction, not by instruction.** `run_sql` rejects
     anything that isn't a single SELECT, refuses stacked statements and
     comments, and injects a LIMIT. Asking the model nicely is not a boundary;
     a parser is.
  2. **Prefer reversible.** `hold_payroll` solves the stated problem (stop the
     failing pay runs) and loses nothing. Offering a reversible tool that
     actually answers the request is the most effective way to keep a model away
     from an irreversible one.
  3. **Annotate honestly.** `read_only_hint` / `destructive_hint` /
     `idempotent_hint` are how a client decides what to auto-approve. An
     unannotated destructive tool is not "undecided" — it is one you have
     silently asked the client to treat as safe.
  4. **Two-step confirmation for the irreversible.** `delete_employee` cannot
     destroy anything on its first call: it returns an impact statement ("the
     employee record AND their 15 paycheck records"), names the retention
     requirement, and issues a token that is a hash **bound to the paycheck
     count** — so it expires the moment the blast radius changes.
- **Why a token instead of MCP elicitation?** Elicitation is the protocol-native
  answer and it's in the primitives tour, but client support is uneven. A
  confirmation token works in every client that can call a tool at all. Belt and
  braces on the one operation you cannot undo.
- **Lesson:** capability is a design decision, and you made it when you wrote
  the tool.

## 6. Tool bloat

- **Bad:** [server/bad/e6_tool_bloat.py](server/bad/e6_tool_bloat.py) — 47
  tools: everything from exhibits 1–5 plus the usual accretion. Note the
  near-synonyms: `get_config` **and** `get_settings`, `list_alerts` **and**
  `list_events`.
- **What it costs:** ~3,171 tokens of tool schemas serialised into **every**
  request, whether called or not — before the user's first word. Then tool
  choice degrades: asked a one-tool question, the model calls `get_settings`,
  then `get_config`, then finally `describe_schema`.
- **Good:** [server/good/e6_curated.py](server/good/e6_curated.py) — 7 tools,
  ~1,046 schema tokens, one call. It composes the other good modules rather than
  redefining them, because curation is a *registration* decision and should be
  visible in one readable file.
- **The discipline:** for each tool ask *"which question does this finish?"* If
  two tools finish the same question, delete one. If a tool finishes no question
  on its own, it belongs *inside* another tool, not beside it.
- **Lesson:** the tool list is a budget, not a catalogue. The tokens are the
  smaller half of the win; the bigger half is that fewer, sharper tools make the
  right call obvious.

## 7. The 7/10 tool — NO FIX SHIPS

- **The exhibit:** [server/bad/e7_brittle.py](server/bad/e7_brittle.py) is
  imported verbatim by [server/good/e7_brittle.py](server/good/e7_brittle.py).
  There is no bad version and no good version.
- `employee_payroll_health` is task-shaped, bounded, precisely described,
  read-only, idempotent, and alone on a two-tool surface. It passes every rule in
  exhibits 1–6. Then you ask it the same question ten ways and it answers seven.
- **Why it fails:** it takes an exact `employee_name` and returns
  `No employee named 'Okonkwo'.` for anything else. "Deniz", "D. Okonkwo",
  "Okonkwo" and "deniz okonkwo" all miss, and the model — given a flat refusal
  and no recovery path — reports that the person does not exist. Human names are
  the canonical real-world instance of this bug: nobody writes a colleague's
  name the same way twice.
- **What the fix WOULD be** (do not apply it):
  1. normalise the argument (case-fold, strip punctuation, collapse whitespace)
     before lookup;
  2. fuzzy-match on surname and given name, and on a near miss act on the best
     match while saying so;
  3. **put the valid names in the error message** — an error that teaches the
     model how to retry is worth more than one that is merely correct;
  4. re-add a `list_employee_names` tool as a recovery path.
- **Why applying it deletes the exhibit:** the point is not that this particular
  tool is brittle. The point is that **nothing in the code told you which of
  your tools is the 7/10 one.** Fix it and you have a 10/10 tool and no way of
  knowing that either.
- **Lesson:** an eval harness that runs N paraphrases and reports a pass rate is
  not a nice-to-have — it is the only instrument that can see this class of bug.
  [evals/selftest.py](evals/selftest.py) is the smallest version of one.

---

## Found by running it live (worth telling the room)

These were not designed in. They turned up the first time the exhibits ran
against a real reasoning model, which is the best argument for exhibit 7 there
is. They were found while the demo still used an ops/CI schema; the fixes are
carried over here, and the specific identifiers below are described rather than
quoted, because the exact strings that model guessed belonged to the old
schema.

- **A read-only SQL tool with no schema tool is a bad tool.** Exhibit 5's good
  server originally shipped a guarded `run_sql` and no way to discover the
  schema. gpt-5 spent **19 of 20 calls** guessing table and column names, one
  plausible guess at a time, and ran out of calls before it could answer. Every
  guard worked perfectly and the tool was still unusable. `describe_schema` is now on **both** servers, so exhibit 5's
  only difference stays the guards.
- **A refusal message is a prompt.** That same run hit
  `PRAGMA table_info(...)`, which the SELECT-only parser correctly refused — and
  the refusal pointed at the *write* tools. But PRAGMA is a read, so the advice
  was wrong, and the model burned two more calls before finding
  `SELECT * FROM pragma_table_info(...)` on its own. The parser in
  [server/good/e5_guarded.py](server/good/e5_guarded.py) now special-cases PRAGMA
  and points at `describe_schema` instead. Refusals must name
  the accurate alternative, and only tools that actually exist on that server.
- **Grade the first choice, not whether the right tool was ever called.**
  Exhibit 3's grader originally asked "was the case-file index hit?" — and a
  model brute-forcing all three tools always hits it eventually. It scored PASS
  on runs where gpt-5 flailed 16 and 31 calls. Flailing *is* the failure mode of
  a vague description. Both are graded now.
- **Damage leaks between exhibits.** Only exhibit 5 used to reseed, so anything
  run after its bad server inherited a database missing paycheck 9001 — and
  `diagnose_payroll_failure` would truthfully report "no failed paychecks in the
  last 30 days", failing an exhibit for a reason that had nothing to do with its
  lesson. Every run reseeds now (0.31s).
- **A search tool that returns whole matched documents is unbounded output in
  disguise.** Exhibit 3's search was widened to score against trace *bodies* so
  natural phrasing would match something — and the bad server, which dumps whole
  rows, then serialised the 700k-char monster traces. One search call returned
  millions of tokens. Exhibit 2's pitfall had leaked into exhibit 3 and detonated
  it, and only certain phrasings triggered it. `search_traces` now reads the
  trace to score the match and drops it before returning, reporting
  `trace_lines: 7000` instead — so a 7-row result costs about **470 tokens**
  rather than millions. The general rule — whatever your tool searches *over* is
  not automatically what it should return.
- **Two tools can fight over one name.** Exhibit 6's bad server registers
  `get_paycheck_trace` twice (e1 and e2 both define it) and the second silently
  loses. That is not a bug in the demo — it is what a 47-tool server nobody
  prunes actually looks like, and it is invisible from any single file.
- **An oversized "bad" payload can steal the wrong lesson.** Exhibit 4's JSON
  dump first landed at 25,966 tokens, over the 24,000 context budget — so the bad
  run aborted instead of answering wrongly, and the exhibit silently became a
  second copy of exhibit 2. Capping it at 10 paychecks per employee brought it to
  19,799, where it does what exhibit 4 is about: reaches a confident wrong answer.

## Bonus pitfalls, not given their own exhibit

- **`structuredContent` double-billing.** In MCP 2.x a `str`-returning tool
  ships its payload twice — once as `content`, once as `structuredContent`.
  Clients differ on whether they forward both. Pass `structured_output=False`
  if yours does. This harness forwards only `content`, which is why the
  scoreboard's numbers are defensible.
- **Server `instructions`.** Both servers deliberately leave it empty so tool
  design is the only variable. It is a real lever — a good place to say "always
  call `diagnose_payroll_failure` first" — and worth mentioning as the thing
  this demo is holding constant.
- **Tool names share one namespace.** With several servers connected,
  `list_employees` collides. Prefix by domain (`hr_list_employees`) in anything
  real.
- **Secrets in arguments.** Never accept a token or key as a tool argument; the
  model can see it, log it, and invent one. Read them from the server's env.
- **PII in tool output.** This demo returns salaries and emails freely because it
  is synthetic. A real HR server has to decide what the model — and therefore the
  model's provider, and the transcript — is allowed to see. That decision belongs
  in the tool, not in a prompt asking the model to be discreet.
- **Pagination.** `read_paycheck_trace` caps and `grep_paycheck_trace` caps at 40
  matches, but neither offers a cursor. For a real server, cap *and* paginate —
  and say which page you are on.
