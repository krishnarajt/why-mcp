"""The teaching content rendered into the UI.

Kept out of `exhibits.py` on purpose: that file is harness logic (questions,
graders, metrics) and this one is prose. They change for different reasons.

Two markup conventions, both expanded by the front-end:
  `backticks`            -> inline code
  [[path/to/file.py]]    -> a link that opens that file's source in the page

Code is never pasted in here. `Snippet` names a file and a symbol, and the
server extracts that symbol's real source with `ast` at request time -- so the
page cannot drift out of sync with the code it is teaching.

`ToolDemo` is the same idea for output: it calls a real tool on a real server
over stdio and shows exactly what the model received. Only the demos declared
here can be invoked from the browser, which matters because the bad exhibit-5
server has `delete_employee` on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Snippet:
    label: str
    path: str
    symbol: str
    note: str = ""


@dataclass
class ToolDemo:
    label: str
    exhibit: int
    variant: str
    tool: str
    args: dict
    note: str = ""


@dataclass
class Lesson:
    headline: str
    what_happens: str
    why_tempting: str
    what_it_costs: str
    rule: str
    snippets: list[Snippet] = field(default_factory=list)
    demos: list[ToolDemo] = field(default_factory=list)
    read_more: list[tuple[str, str]] = field(default_factory=list)


# --------------------------------------------------------------------------
# The primer on the Overview tab
# --------------------------------------------------------------------------

PRIMER = {
    "title": "MCP in about ninety seconds",
    "blocks": [
        {
            "h": "It is JSON-RPC over a pipe",
            "p": "An MCP server is a program that speaks JSON-RPC 2.0, usually over "
            "<b>stdio</b> — the client launches your server as a subprocess and they talk "
            "over stdin/stdout. (The other transport is streamable HTTP, for remote "
            "servers.) That is the whole protocol. Everything else is convention. "
            "The servers in this demo are launched exactly the way your editor would "
            "launch them: `python -m server good --exhibit 1`. Open the "
            "<b>view the wire</b> panel under any run to watch the actual frames.",
        },
        {
            "h": "The conversation loop, and why it costs what it costs",
            "p": "This is the part that explains almost every number on this page. One "
            "question runs a loop:<br><br>"
            "<b>1.</b> The client calls `tools/list` and serialises every tool's name, "
            "description and JSON schema into the request it sends the model.<br>"
            "<b>2.</b> The model replies either with an answer, or with a request to call "
            "a tool.<br>"
            "<b>3.</b> The client calls `tools/call`, gets text back, and appends it to the "
            "conversation as a `tool` message.<br>"
            "<b>4.</b> Go to 1 — <i>with the whole conversation so far re-sent.</i><br><br>"
            "So a tool call is not a cheap function call. It is a full round trip, and "
            "every previous tool result is re-billed as input tokens on every "
            "subsequent turn. Five round trips do not cost five times one — they cost "
            "more. That is why exhibit 1 is about call <i>count</i>.",
        },
        {
            "h": "The model only ever sees text you wrote",
            "p": "The model cannot inspect your database, read your source, or try a tool "
            "to see what happens. Its entire basis for choosing a tool is the "
            "<b>name</b>, the <b>description</b>, and the <b>parameter names</b> — text you "
            "wrote. Your docstrings are not documentation sitting beside the system; they "
            "<i>are</i> the prompt. Exhibit 3 is the whole argument.",
        },
        {
            "h": "Tools are one quarter of it",
            "p": "<b>Tools</b> are model-decided actions. <b>Resources</b> are context the "
            "client attaches by URI, so the model never spends a turn deciding to fetch "
            "them. <b>Prompts</b> are user-invoked templates — these are what become slash "
            "commands. And two that invert the direction: <b>sampling</b> lets your server "
            "ask the client's model for a completion (your server gets an LLM without an "
            "API key), and <b>elicitation</b> lets your server ask the human a question "
            "mid-call. The Primitives tab fires each one and shows you the frames.",
        },
        {
            "h": "The one mental model to keep",
            "p": "MCP is <b>not</b> a way to hand an LLM your REST API. Endpoint-shaped "
            "tools are the single most common mistake, and it is the most reasonable one. "
            "Context is your scarce resource, so a good tool is <b>task-shaped</b>: named "
            "for a question a person actually asks, doing its joins server-side, and "
            "returning terse prose rather than raw JSON. The test is not "
            "<i>“does this expose the data?”</i> It is <i>“does one call finish a thought?”</i>",
        },
        {
            "h": "What you are looking at",
            "p": "The data is an ordinary HR database: ten <b>employees</b> in four "
            "<b>departments</b>, the semi-monthly <b>paychecks</b> each of them is issued, "
            "the <b>org changes</b> that keep breaking payroll, and the closed "
            "<b>HR case files</b> that record what happened the last time. Both servers "
            "read the same rows. Open the <b>Database</b> tab to see them, then come back "
            "and watch two tool designs answer the same question at very different prices.",
        },
    ],
}


# --------------------------------------------------------------------------
# Per-exhibit lessons
# --------------------------------------------------------------------------

LESSONS: dict[int, Lesson] = {
    1: Lesson(
        headline="Name tools after questions, not after tables.",
        what_happens="Every tool call is a full round trip — model, client, server, and "
        "back — and each turn re-sends the entire conversation so far as input tokens. "
        "So the cost of a five-call answer is not five units, it grows with every hop. "
        "When your tools are one-per-query, the model has to act as your query planner: "
        "it must work out on its own that <i>“why did Priya Raman's paycheck fail”</i> "
        "means join paychecks, then the payroll trace, then org changes, then closed case "
        "files. It does not know your schema, so it guesses, and it usually stops "
        "guessing early.",
        why_tempting="You already have a REST API. Exposing it one-to-one feels complete "
        "— every field is reachable — and each tool passes review in isolation because "
        "each one is obviously correct. Nothing about `get_paycheck_status` looks like a "
        "mistake.",
        what_it_costs="Watch the tool-call count. The bad server usually still finds the "
        "error, but it rarely connects the <b>Reorg 4.2</b> org change that caused it: by "
        "the time it has chained four calls it has spent its effort on navigation instead "
        "of reasoning. The good server does the same four queries in one call, "
        "server-side, where they cost microseconds.",
        rule="One call should finish a thought. Three tools that finish thoughts beat "
        "nineteen that expose tables.",
        snippets=[
            Snippet(
                "The bad server, nineteen times over",
                "server/bad/e1_endpoint_shaped.py",
                "get_paycheck_status",
                "Correct, tiny, and useless on its own. There are eighteen more like it, "
                "and answering one real question needs five of them in the right order.",
            ),
            Snippet(
                "The good server: one call, four queries",
                "server/good/e1_task_shaped.py",
                "diagnose_payroll_failure",
                "Read the docstring first — it tells the model this is the FIRST call for "
                "any 'why did X's pay fail' question and that it need not fetch paychecks, "
                "traces, org changes or case files separately. Then note the body does all "
                "four joins itself and returns a briefing.",
            ),
        ],
        demos=[
            ToolDemo(
                "What the model gets back from one good call",
                1, "good", "diagnose_payroll_failure", {"employee_name": "Priya Raman"},
                "The error lines, the reorg in the preceding window, and the matching "
                "case file — in about 400 tokens. The bad server needs five calls to "
                "assemble a worse version of this.",
            ),
        ],
        read_more=[
            ("the whole bad server", "server/bad/e1_endpoint_shaped.py"),
            ("the whole good server", "server/good/e1_task_shaped.py"),
        ],
    ),
    2: Lesson(
        headline="A tool that can return unbounded text is a tool that will.",
        what_happens="A tool result is inserted into the conversation verbatim, as a "
        "`tool` message. There is no streaming, no pagination, and no mechanism by which "
        "the model reads “part of” it. Whatever your function returns becomes input "
        "tokens on that turn and every turn after it. Paycheck 9002 belongs to a "
        "commission-heavy sales rep, so its payroll trace prices thousands of deals one "
        "line at a time: 700,532 characters, about 236,000 tokens. That is not merely "
        "expensive; it exceeds any context window in production, so the request cannot be "
        "made at all.",
        why_tempting="Returning the whole trace is <i>faithful</i>. It is also completely "
        "fine in testing, where your fixture traces are forty lines. The failure only "
        "appears against real data — a salesperson with a big quarter — and when it "
        "appears it is total rather than gradual.",
        what_it_costs="The bad run cannot complete — one tool result is bigger than the "
        "entire context budget, so the meter turns red and says OVERFLOW. Note what the "
        "bad tool's signature makes impossible: there is no argument the model could "
        "pass to ask for less. It has no way out.",
        rule="Cap the output. Say what you truncated. Name the tool that finds the rest. "
        "Do all three or you have done none of them.",
        snippets=[
            Snippet(
                "Four lines that cannot work",
                "server/bad/e2_no_truncation.py",
                "get_paycheck_trace",
                "There is no bug here. It does exactly what it says. The bug is the "
                "signature: one parameter, no way to bound the result.",
            ),
            Snippet(
                "The good version, and the three rules in order",
                "server/good/e2_truncated.py",
                "read_paycheck_trace",
                "1. `tail` caps it, hard-max 400. 2. The header states the trace's TRUE "
                "size and that this is a slice — a model that does not know it got a slice "
                "will confidently reason about a trace it never read. 3. The header names "
                "`grep_paycheck_trace`, so truncation is not data loss.",
            ),
            Snippet(
                "Why the good server ends up more capable, not less",
                "server/good/e2_truncated.py",
                "grep_paycheck_trace",
                "This is the part people miss. `grep_paycheck_trace` can find a line at "
                "index 3,000 that a full dump would have buried in noise even if it had "
                "fitted. Bounding output forced a better tool into existence.",
            ),
        ],
        demos=[
            ToolDemo(
                "The good tool's header — note what it discloses",
                2, "good", "read_paycheck_trace", {"paycheck_id": 9002, "tail": 12},
                "“7,000 lines, 700,532 chars. Showing the last 12. 6,988 earlier lines NOT "
                "shown — use grep_paycheck_trace(...) to search them.” That sentence is "
                "doing more work than the trace tail underneath it.",
            ),
            ToolDemo(
                "Searching the 6,988 lines you did not read",
                2, "good", "grep_paycheck_trace",
                {"paycheck_id": 9002, "pattern": "FATAL|rate table"},
                "Line numbers, context, and a cap with instructions for when you hit it.",
            ),
        ],
        read_more=[
            ("the bad server", "server/bad/e2_no_truncation.py"),
            ("the good server", "server/good/e2_truncated.py"),
        ],
    ),
    3: Lesson(
        headline="Your tool description is not documentation. It is the prompt.",
        what_happens="When the model decides which tool to call, it is working from "
        "exactly three things: the tool's <b>name</b>, its <b>description</b>, and its "
        "<b>parameter names</b>. That is the entire input to the decision. It cannot try a "
        "tool to see what comes back, cannot read your source, and cannot know that "
        "`search` covers twelve months of live payroll traces while `find` covers years of "
        "closed HR case files. Whatever you typed in that docstring got serialised into "
        "the request and became prompt engineering, whether you were thinking of it that "
        "way or not.",
        why_tempting="A docstring feels like documentation — something for humans, "
        "written later, nice to have. `\"\"\"Search.\"\"\"` looks adequate because the "
        "function name already says it. And crucially: both of these tools work "
        "perfectly. Neither has a bug.",
        what_it_costs="The model picks by vibes, and — this is the expensive part — "
        "<b>picking wrong does not error</b>. `search` cheerfully returns this cycle's "
        "failure, so the model reports the current problem as its own precedent. A "
        "confident wrong answer costs far more than a crash. Run the bad side five times "
        "and watch the dots flip; that non-determinism is what untested prompts look like.",
        rule="Four lines in every description: what it covers, when to reach for it, what "
        "it does NOT cover, and which tool to use instead. The last one is the one "
        "everybody skips and the one that does the most work.",
        snippets=[
            Snippet(
                'The bad pair: "Search." and "Find things."',
                "server/bad/e3_vague_descriptions.py",
                "register",
                "Read all three tools together. Every name is plausible, every description "
                "is true, and nothing tells the model that these search completely "
                "different corpora with different time horizons.",
            ),
            Snippet(
                "The same query, described properly",
                "server/good/e3_precise_descriptions.py",
                "search_pay_traces",
                "Same underlying query as `search`. Count the four moves: covers payroll "
                "traces LAST 12 MONTHS ONLY / use for whose-pay-is-failing-now / does NOT "
                "contain older history / for precedent use search_hr_cases instead. That "
                "final sentence makes a wrong choice self-correcting.",
            ),
            Snippet(
                "Its sibling names it right back",
                "server/good/e3_precise_descriptions.py",
                "search_hr_cases",
                "Note the pair points at each other in both directions, and that the "
                "<i>empty-result</i> messages do it too — the moment a model is most likely "
                "to be lost is when it got nothing back.",
            ),
        ],
        demos=[
            ToolDemo(
                "The trap, live: what the WRONG index returns",
                3, "bad", "search", {"q": "cost center budget exceeded"},
                "It does not fail. It returns paycheck 9001 — <b>this cycle's</b> failure — "
                "so a model asked “has this happened before?” answers “yes, last cycle”. "
                "Technically true, completely useless, and indistinguishable from a real "
                "answer.",
            ),
            ToolDemo(
                "What the right index returns",
                3, "good", "search_hr_cases", {"query": "cost center budget"},
                "The 14-month-old SEV2, with the write-up, the fix, and the action item "
                "nobody completed.",
            ),
        ],
        read_more=[
            ("the bad server", "server/bad/e3_vague_descriptions.py"),
            ("the good server", "server/good/e3_precise_descriptions.py"),
        ],
    ),
    4: Lesson(
        headline="Answer the question. Do not hand over the raw material and hope.",
        what_happens="The model reads your tool's output as text — the same way it reads "
        "everything. Every key name, every `null`, every uuid and base64 digest is tokens "
        "it pays for and attention it spends. It is not parsing your JSON into a "
        "structure and querying it; it is reading it, then doing arithmetic and ranking "
        "in its head. Nulls invite hallucinated field names. Microsecond timestamps "
        "invite date-arithmetic errors. Surrogate ids get quoted back to your user.",
        why_tempting="Serialising the ORM is “complete” and “machine readable”, and both "
        "of those sound like virtues. The model is a machine, so machine-readable must be "
        "right — except the sense in which it is a machine is not the sense you mean.",
        what_it_costs="Around 20,000 tokens versus 300 for the identical question, and "
        "the bad server routinely names the wrong worst employee. It is not being stupid: "
        "you asked it to divide 13 by 15 across ten nested objects and then apply a "
        "definition of “unhealthy” you never told it.",
        rule="Drop what the answer does not need, convert timestamps to “8d ago”, "
        "precompute the verdict, and sort worst-first. If a human would not want to read "
        "your tool's output, the model is not enjoying it either.",
        snippets=[
            Snippet(
                "The good version, in full",
                "server/good/e4_model_readable.py",
                "payroll_health_report",
                "Four deliberate moves. DROPPED ids, uuids, nulls, digests, _links, the "
                "nested manager and department objects. CONVERTED timestamps to relative "
                "time. PRECOMPUTED the rate <i>and a verdict word</i> — “what counts as "
                "unhealthy” is a policy decision, and policy belongs on your server where "
                "it is testable. SORTED worst-first, because ordering answers “whose is "
                "worst” before any reasoning happens.",
            ),
            Snippet(
                "The bad version builds this on purpose",
                "server/bad/e4_raw_json.py",
                "register",
                "`employee_uuid`, `terminated_at: null`, `deleted_at: null`, a nested "
                "`manager` with its own nested `preferences`, a nested `department` with a "
                "nested `budget`, a base64 `trace_digest`, `_links`. Every one of these is "
                "defensible in an HTTP API and pure cost here.",
            ),
        ],
        demos=[
            ToolDemo(
                "What the model actually receives — the good server",
                4, "good", "payroll_health_report", {},
                "Ten rows, worst first, verdict included. The answer to “whose is worst” is "
                "row one.",
            ),
            ToolDemo(
                "…and the bad server, same question",
                4, "bad", "get_all_employee_payroll_stats", {},
                "Same data. Scroll it. This is what ~20,000 tokens looks like, and the "
                "answer is in there somewhere.",
            ),
        ],
        read_more=[
            ("the bad server", "server/bad/e4_raw_json.py"),
            ("the good server", "server/good/e4_model_readable.py"),
        ],
    ),
    5: Lesson(
        headline="Capability is a design decision, and you made it when you wrote the tool.",
        what_happens="MCP has a mechanism for exactly this: `ToolAnnotations` — "
        "`readOnlyHint`, `destructiveHint`, `idempotentHint` — travel with each tool in "
        "`tools/list`, and the client uses them to decide what to auto-approve and what "
        "to stop and ask a human about. An unannotated destructive tool is not "
        "“undecided”. You have silently told every client to treat it as safe. Meanwhile "
        "the model is not reasoning about consequences; it is matching your description "
        "against the user's request. `\"Runs any SQL\"` plus “clean it up” is a "
        "well-formed match.",
        why_tempting="`run_sql` is maximally flexible and saves you writing ten tools. "
        "And you would never run a DELETE without meaning to — but you are not the one "
        "holding the tool.",
        what_it_costs="Asked to “clean it up so finance stops escalating”, the model runs "
        "`DELETE FROM paychecks WHERE status = 'failed'` — across <i>every</i> employee, "
        "not just the one named. Watch the row counter drop while it explains how helpful "
        "it has been. Those are payroll records, which most jurisdictions require you to "
        "retain for years. It is not malfunctioning. It did what the tools advertised.",
        rule="A parser, not a plea. A reversible tool that actually solves the stated "
        "problem. Honest annotations. And two steps for anything you cannot undo.",
        snippets=[
            Snippet(
                "Read-only by construction, not by instruction",
                "server/good/e5_guarded.py",
                "run_sql",
                "It does not <i>ask</i> the model to avoid writes. It rejects anything that "
                "is not a single SELECT, refuses stacked statements and comments, and "
                "injects a LIMIT. Asking nicely in a docstring is not a security boundary; "
                "a parser is. Note also that each refusal names the accurate alternative — "
                "a refusal message is a prompt too.",
            ),
            Snippet(
                "The most effective guard is a better option",
                "server/good/e5_guarded.py",
                "hold_payroll",
                "This is the highest-leverage line in the exhibit. The user's actual goal "
                "is “stop the escalations”, and this achieves it while losing nothing. "
                "Offering a reversible tool that genuinely solves the request is the best "
                "way to keep a model away from an irreversible one.",
            ),
            Snippet(
                "Two steps for the irreversible",
                "server/good/e5_guarded.py",
                "delete_employee",
                "The first call cannot delete. It returns an impact statement — “the "
                "employee record AND their 15 paycheck records” — plus a token, and "
                "re-suggests `hold_payroll`. The impact statement is what a human needs in "
                "order to say no.",
            ),
            Snippet(
                "The token is bound to the blast radius",
                "server/good/e5_guarded.py",
                "_confirm_token",
                "Hashing the paycheck count in means a token issued for “deletes 15 "
                "paychecks” stops being valid the moment the number changes. Confirmation "
                "of a stale fact is not confirmation.",
            ),
            Snippet(
                "And the whole bad server, for contrast",
                "server/bad/e5_unguarded.py",
                "register",
                "No annotations anywhere, `\"\"\"Deletes an employee.\"\"\"` as a complete "
                "description, and a cascade delete of every paycheck.",
            ),
        ],
        demos=[
            ToolDemo(
                "The guard refusing a write",
                5, "good", "run_sql", {"query": "DELETE FROM paychecks WHERE status = 'failed'"},
                "Refused by the parser, and pointed at the two tools that <i>can</i> change "
                "data — one reversible, one gated.",
            ),
            ToolDemo(
                "The confirmation gate (nothing is deleted)",
                5, "good", "delete_employee", {"employee_name": "Marcus Bell"},
                "First call, no token: an impact statement, a nudge toward `hold_payroll`, "
                "and a token to echo back. This call is safe to run — it changes nothing.",
            ),
        ],
        read_more=[
            ("the bad server", "server/bad/e5_unguarded.py"),
            ("the good server", "server/good/e5_guarded.py"),
        ],
    ),
    6: Lesson(
        headline="Your tool list is a budget, not a catalogue.",
        what_happens="`tools/list` is serialised into <b>every single request</b> you send "
        "the model — name, description and full JSON schema for every registered tool, "
        "whether or not it gets called. That is a fixed tax paid before the user's first "
        "word is read. Forty-seven tools here cost about 3,000 tokens of pure overhead "
        "per turn; seven cost about 1,000.",
        why_tempting="Nobody ever deletes a tool, because removing one might break "
        "someone. Each addition is individually harmless, and the cost is invisible in "
        "code review — you cannot see it by reading any single file.",
        what_it_costs="The tokens are the smaller half. The bigger half is that tool "
        "choice degrades: with near-synonyms in the list (`get_config` <i>and</i> "
        "`get_settings`, `list_alerts` <i>and</i> `list_events`) the model has to guess, "
        "and guesses cost round trips. There is a subtler cost too — this server "
        "registers `get_paycheck_trace` twice, from two different modules, and the second "
        "one silently loses. You cannot tell from any one file which tools you actually "
        "have.",
        rule="For each tool ask: which question does this finish? If two finish the same "
        "question, delete one. If one finishes no question by itself, it belongs inside "
        "another tool, not beside it.",
        snippets=[
            Snippet(
                "Curation is a registration decision",
                "server/good/e6_curated.py",
                "register",
                "Seven tools, composed from the other good modules rather than redefined — "
                "so the whole surface is legible in one short file you can read top to "
                "bottom. That legibility is the point.",
            ),
            Snippet(
                "The accretion, and the near-synonyms",
                "server/bad/e6_tool_bloat.py",
                "register",
                "It loads every bad module from exhibits 1–5 and then adds the usual pile. "
                "Find `get_settings` and `get_config` — identical bodies, different names. "
                "The model has no way to choose between them.",
            ),
        ],
        demos=[
            ToolDemo(
                "The one tool that answers the question",
                6, "good", "describe_schema", {},
                "About 200 tokens. On the bad server the same tool exists and the same "
                "answer is one call away — you just paid 3,000 tokens for the privilege of "
                "having 46 other options in front of it.",
            ),
        ],
        read_more=[
            ("the bad server", "server/bad/e6_tool_bloat.py"),
            ("the good server", "server/good/e6_curated.py"),
        ],
    ),
    7: Lesson(
        headline="Nothing in the code tells you which of your tools is the 7-out-of-10 one.",
        what_happens="This tool obeys every rule from exhibits 1 through 6. It is "
        "task-shaped, its output is bounded and model-readable, its description is "
        "precise, it is annotated read-only and idempotent, and it sits alone on a "
        "two-tool surface. Then you ask it the same question ten different ways and it "
        "answers seven. The failure is banal: it takes an exact `employee_name`, so "
        "“Deniz”, “D. Okonkwo”, “Okonkwo” and “deniz okonkwo” all miss — and given a flat "
        "refusal with no recovery path, the model concludes the person does not exist. "
        "Human names are where this bites hardest: nobody types a colleague's full legal "
        "name the same way twice.",
        why_tempting="It passes review. It passes <i>your</i> review, right now, reading "
        "it below. That is the entire exhibit.",
        what_it_costs="Three questions in ten get a confidently wrong “that employee does "
        "not exist”. In production those are the three you never hear about.",
        rule="An eval harness that runs N paraphrases and reports a pass rate is not a "
        "nice-to-have. It is the only instrument that can see this class of bug.",
        snippets=[
            Snippet(
                "The tool. Find the bug by reading it.",
                "server/bad/e7_brittle.py",
                "employee_payroll_health",
                "You will not, and that is not a failure of attention — there is no bug in "
                "here. The defect is in the space between this code and the way people "
                "write each other's names.",
            ),
            Snippet(
                "The good server does not fix it",
                "server/good/e7_brittle.py",
                "register",
                "One import. Fixing it would give you a 10/10 tool and no way of knowing "
                "that either. PITFALLS.md describes what the fix would be — normalise the "
                "argument, fuzzy-match, and above all <b>put the valid names in the error "
                "message</b>, because an error that teaches the model how to retry is worth "
                "more than one that is merely correct.",
            ),
            Snippet(
                "The smallest eval harness that would have caught it",
                "evals/selftest.py",
                "run_one",
                "Run the same tool against a list of paraphrases, grade each mechanically, "
                "report the rate. That is all an eval is.",
            ),
        ],
        demos=[
            ToolDemo(
                "The name it accepts",
                7, "bad", "employee_payroll_health", {"employee_name": "Deniz Okonkwo"},
                "A clean, useful, well-formatted answer.",
            ),
            ToolDemo(
                "The name a person would type",
                7, "bad", "employee_payroll_health", {"employee_name": "Okonkwo"},
                "A surname. A dead end with no hint of what to try instead — so the model "
                "reports that the employee does not exist.",
            ),
        ],
        read_more=[
            ("the tool", "server/bad/e7_brittle.py"),
            ("the eval harness", "evals/selftest.py"),
        ],
    ),
}


# --------------------------------------------------------------------------
# The Primitives tab
# --------------------------------------------------------------------------

PRIMITIVES = {
    "title": "Tools are one quarter of MCP",
    "blocks": [
        {
            "h": "Resources: context without spending a turn",
            "p": "A resource is data addressed by <b>URI</b> — `hr://employees`, "
            "`hr://paycheck/9001/trace`. The crucial difference from a tool is "
            "<i>who decides</i>: the client or the user attaches a resource, so it arrives "
            "in context without the model spending a turn choosing to fetch it. A tool "
            "call costs a round trip and a decision; a resource costs neither. Resources "
            "can also be <b>templates</b> — `hr://paycheck/{paycheck_id}/trace` is not "
            "listed under `resources/list` at all, it appears under "
            "`resources/templates/list`, and nothing is fetched until someone fills in the "
            "id. If a human already knows which data is relevant, do not make the model "
            "guess: hand it over.",
        },
        {
            "h": "Prompts: this is what a slash command is",
            "p": "A prompt is a server-provided template the <b>user</b> invokes, with "
            "arguments. In a client like Claude Code these surface as slash commands. "
            "That is the whole mechanism behind `/payroll_triage` below — the server owns "
            "the checklist, so improving your triage procedure means editing your server, "
            "not retraining anybody. Note the `payroll_triage` prompt names the exact "
            "tools to call in order: a prompt is a good place to encode workflow that "
            "would bloat every individual tool description.",
        },
        {
            "h": "Sampling: your server borrows the client's model",
            "p": "Normally requests flow client → server. <b>Sampling</b> reverses it: your "
            "server sends `sampling/createMessage` <i>to the client</i> and the client's "
            "model answers. Watch for the `S→C` frame in the wire panel — it is the only "
            "place in this demo where a request travels that direction. The consequence is "
            "worth sitting with: your server gets an LLM with <b>no API key and no bill</b>, "
            "because the inference is the client's. It also means a server can quietly "
            "spend your tokens, which is why clients gate this and many do not implement "
            "it at all.",
        },
        {
            "h": "Elicitation: your server asks the human",
            "p": "A tool can stop mid-execution and ask the user a question, sending a "
            "<b>schema</b> that describes what it wants back. The user's answer comes back "
            "as `accept`, `decline`, or `cancel`. This is the protocol-native way to do "
            "confirmation — and yet exhibit 5 guards deletion with a hand-rolled "
            "confirmation token instead. That is deliberate: client support for "
            "elicitation is uneven, and a token works in every client that can call a tool "
            "at all. Use the protocol feature when you control the client; use the token "
            "when you do not.",
        },
        {
            "h": "Why this demo can show you sampling and elicitation at all",
            "p": "Both require the <b>client</b> to implement a callback — most clients "
            "skip them, which is exactly why they feel obscure. "
            "[[harness/client.py]] implements both: `_sampling_callback` forwards the "
            "server's request to OpenAI, and `_elicitation_callback` auto-accepts with "
            "canned values so the frame is visible without a human in the loop. Reading "
            "those two functions is the fastest way to understand what your client is "
            "doing on your behalf.",
        },
    ],
    "snippets": [
        {"label": "A resource, and a resource template",
         "path": "server/good/primitives.py", "symbol": "paycheck_trace_resource",
         "note": "The `{paycheck_id}` in the URI makes this a template. It is advertised "
                 "under `resources/templates/list`, not `resources/list`, and nothing is "
                 "read until a client fills in the id."},
        {"label": "A prompt — the thing that becomes /payroll_triage",
         "path": "server/good/primitives.py", "symbol": "payroll_triage_prompt",
         "note": "Returns a string. The client turns it into a user message. Note it names "
                 "the tools to call and the order to call them in."},
        {"label": "Sampling: the server calling the client's model",
         "path": "server/good/primitives.py", "symbol": "summarise_case",
         "note": "`ctx.session.create_message(...)` is the inversion. This server has no "
                 "API key; the completion is billed to whoever is running the client."},
        {"label": "Elicitation: the server asking the user",
         "path": "server/good/primitives.py", "symbol": "change_cost_center_budget",
         "note": "A tool with no arguments that stops to ask for them, passing a pydantic "
                 "model as the schema. Check `result.action` before trusting `result.data` "
                 "— the user is allowed to say no."},
        {"label": "The client side of both callbacks",
         "path": "harness/client.py", "symbol": "_sampling_callback",
         "note": "This is what your editor does for you, in about fifteen lines."},
    ],
}
