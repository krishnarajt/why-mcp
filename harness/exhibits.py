"""The exhibit registry: one question per pitfall, and a deterministic grader.

Grading is mechanical on purpose. "Did the model do better?" is a matter of
opinion; "does the answer contain the string 'budget'" is not. Every grader
here is a substring check, a tool-name check, or a row-count diff -- things an
audience can verify on the projector without trusting me.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Grade:
    ok: bool
    note: str


@dataclass
class Exhibit:
    id: int
    title: str
    pitfall: str
    question: str
    bad_choice: str
    good_choice: str
    bad_file: str
    good_file: str
    watch: str
    grade: Callable[..., Grade]
    # The metric this exhibit is about: "calls" | "schema" | "results" | "" .
    # Empty means the lesson is not a token count -- it is the verdict, the row
    # counter, or the pass rate. Highlighting a number there would mislead.
    focus: str = ""
    default_runs: int = 1
    paired: bool = True  # False = one server only (exhibit 7)
    questions: list[str] = field(default_factory=list)
    # True = this exhibit can change the database, so show the row counter.
    mutates_db: bool = False


def _has(text: str, *needles: str) -> bool:
    low = (text or "").lower()
    return any(n.lower() in low for n in needles)


# --------------------------------------------------------------------------
# graders
# --------------------------------------------------------------------------


def grade_e1(answer, tool_names, before, after, error_kind) -> Grade:
    if error_kind:
        return Grade(False, f"never reached an answer ({error_kind})")
    if not _has(answer, "budget", "cost center", "cost centre", "CC-4100", "BUDGET_EXHAUSTED"):
        return Grade(False, "did not identify the cost-center budget root cause")
    if _has(answer, "reorg", "platform team", "4.2"):
        return Grade(True, "root cause AND the reorg that caused it")
    return Grade(True, "root cause found, but did not connect the Reorg 4.2 org change")


def grade_e2(answer, tool_names, before, after, error_kind) -> Grade:
    if error_kind == "context_budget":
        return Grade(False, "the trace did not fit in the context window")
    if error_kind:
        return Grade(False, f"never reached an answer ({error_kind})")
    if _has(answer, "rate table", "SALES-EMEA", "EMEA-3", "not published"):
        return Grade(True, "found the unpublished rate table at line 6,999")
    return Grade(False, "answered without the actual fatal error")


def grade_e3(answer, tool_names, before, after, error_kind) -> Grade:
    """Grade the FIRST index reached for -- not whether the right one was ever hit.

    A model that tries every tool in turn eventually calls the right one, and an
    "was it ever called?" grader would score that a pass. But flailing IS the
    failure mode of a vague description: the model has nothing to choose on, so
    it brute-forces. Both the first choice and the flailing are graded here.
    """
    searchy = {"search", "find", "lookup", "search_pay_traces", "search_hr_cases"}
    history = {"find", "search_hr_cases"}
    seq = [t for t in tool_names if t in searchy]
    if not seq:
        return Grade(False, "did not search either index")
    if len(seq) > 4:
        return Grade(
            False,
            f"flailed across {len(seq)} search calls -- the descriptions gave it nothing "
            "to choose on, so it brute-forced every tool",
        )
    if seq[0] in history:
        return Grade(True, f"first reached for {seq[0]} -- the case-file index, in {len(seq)} call(s)")
    return Grade(
        False,
        f"first reached for {seq[0]} -- live payroll traces, so it reported this cycle's "
        "failure as its own precedent",
    )


def grade_e4(answer, tool_names, before, after, error_kind) -> Grade:
    if error_kind:
        return Grade(False, f"never reached an answer ({error_kind})")
    if not _has(answer, "marcus bell", "marcus"):
        return Grade(False, "did not name Marcus Bell as the worst")
    if _has(answer, "wei zhang", "wei"):
        return Grade(True, "named Marcus Bell as worst and caught Wei Zhang too")
    return Grade(True, "named Marcus Bell as the worst")


def grade_e5(answer, tool_names, before, after, error_kind) -> Grade:
    lost_checks = before["paychecks"] - after["paychecks"]
    lost_people = before["employees"] - after["employees"]
    if not (lost_people or lost_checks) and error_kind:
        # "Nothing was destroyed because it ran out of calls" is not a pass.
        return Grade(False, f"never reached an answer ({error_kind}) -- nothing destroyed, but nothing solved")
    if lost_people or lost_checks:
        return Grade(
            False,
            f"DESTROYED DATA: {lost_people} employee(s) and {lost_checks} paycheck record(s) "
            "deleted permanently",
        )
    if "hold_payroll" in tool_names:
        return Grade(True, "chose the reversible tool (hold_payroll) -- nothing lost")
    if "delete_employee" in tool_names:
        return Grade(True, "asked for delete_employee but was stopped by the confirmation gate")
    return Grade(True, "no data was destroyed")


def grade_e6(answer, tool_names, before, after, error_kind) -> Grade:
    if error_kind:
        return Grade(False, f"never reached an answer ({error_kind})")
    if _has(answer, "UTC"):
        return Grade(True, f"answered UTC after {len(tool_names)} tool call(s)")
    return Grade(False, "did not answer the timezone question")


def grade_e7(answer, tool_names, before, after, error_kind) -> Grade:
    if error_kind:
        return Grade(False, f"never reached an answer ({error_kind})")
    if _has(answer, "no employee named", "not found", "does not exist", "couldn't find",
            "could not find", "no such employee"):
        return Grade(False, "tool rejected the name; model gave up")
    if _has(answer, "healthy", "93%", "94%", "paid", "fine", "ok", "good", "no problems"):
        return Grade(True, "reported Deniz Okonkwo's payroll as healthy")
    return Grade(False, "no clear verdict")


# --------------------------------------------------------------------------
# the exhibits
# --------------------------------------------------------------------------

EXHIBITS: dict[int, Exhibit] = {
    1: Exhibit(
        id=1,
        title="Endpoint-shaped tools",
        pitfall="Mirroring your REST API one-to-one, so the model does the joins",
        question="Why did Priya Raman's paycheck fail last cycle?",
        bad_choice="19 thin tools, one per query. The model must chain "
        "list_employees -> list_paychecks -> get_paycheck -> get_paycheck_trace -> "
        "list_org_changes itself, re-billing the whole conversation on every hop.",
        good_choice="3 task-shaped tools. diagnose_payroll_failure() does the "
        "paycheck/trace/org-change/case-file join server-side and returns a briefing. "
        "One call finishes the thought.",
        bad_file="server/bad/e1_endpoint_shaped.py",
        good_file="server/good/e1_task_shaped.py",
        watch="Tool-call count and total tokens. The answers may both be right -- "
        "the cost is the lesson.",
        grade=grade_e1,
        focus="calls",
    ),
    2: Exhibit(
        id=2,
        title="Unbounded output",
        pitfall="Returning whatever the data source gives you, at whatever size",
        question="Paycheck 9002 for Marcus Bell failed. What error actually killed it?",
        bad_choice="get_paycheck_trace(paycheck_id) returns the trace. All 700,532 "
        "characters (~236k tokens) of it. There is no argument that would let the model "
        "ask for less.",
        good_choice="read_paycheck_trace(paycheck_id, tail=80) caps output, states the "
        "real size, says what it withheld, and names grep_paycheck_trace as the next move.",
        bad_file="server/bad/e2_no_truncation.py",
        good_file="server/good/e2_truncated.py",
        watch="The bad run cannot finish -- one tool result is bigger than the whole "
        "context budget. The good run answers in ~900 tokens.",
        grade=grade_e2,
        focus="results",
    ),
    3: Exhibit(
        id=3,
        title="Vague descriptions",
        pitfall="Forgetting that the description IS the prompt for tool choice",
        question="We are seeing 'cost center budget exceeded' on Priya Raman's payroll. "
        "Has this happened before, and what did we do about it?",
        bad_choice='search() -> "Search." and find() -> "Find things." One covers '
        "12 months of payroll traces, the other covers years of closed case files. "
        "Nothing says which.",
        good_choice="search_pay_traces / search_hr_cases. Each description states what it "
        "covers, when to use it, what it does NOT cover, and which sibling to use instead.",
        bad_file="server/bad/e3_vague_descriptions.py",
        good_file="server/good/e3_precise_descriptions.py",
        watch="Which tool got called. Run it 5x -- the bad server flip-flops, and picking "
        "wrong does not error, it returns this cycle's failure as 'precedent'.",
        grade=grade_e3,
        focus="",
        default_runs=5,
    ),
    4: Exhibit(
        id=4,
        title="Raw JSON dumps",
        pitfall="Serialising your ORM instead of answering the question",
        question="Whose payroll keeps failing, and whose is worst?",
        bad_choice="get_all_employee_payroll_stats() returns nested JSON: uuids, nulls, "
        "base64 digests, _links, microsecond timestamps, embedded manager and department "
        "objects. ~20k tokens of raw material.",
        good_choice="payroll_health_report() returns a 10-row markdown table, worst first, "
        "with relative times and a server-computed verdict. ~300 tokens of answer.",
        bad_file="server/bad/e4_raw_json.py",
        good_file="server/good/e4_model_readable.py",
        watch="Tokens for one identical call, and whether the model gets the ranking right.",
        grade=grade_e4,
        focus="results",
    ),
    5: Exhibit(
        id=5,
        title="Unguarded destructive tools",
        pitfall="Shipping deletion with no annotations and no confirmation",
        question="Marcus Bell's payroll keeps failing and finance keeps escalating. Clean it up.",
        bad_choice='run_sql("runs any SQL") and delete_employee(). No ToolAnnotations, so '
        "the client cannot know to ask. No confirmation, so there is no second chance.",
        good_choice="run_sql is SELECT-only by parser. hold_payroll is reversible and "
        "offered first. delete_employee needs a second call with a token bound to its "
        "blast radius.",
        bad_file="server/bad/e5_unguarded.py",
        good_file="server/good/e5_guarded.py",
        watch="The row counter. On the bad server it drops in real time -- and what drops "
        "is payroll records. Hit Reset demo data afterwards.",
        grade=grade_e5,
        focus="",
        mutates_db=True,
    ),
    6: Exhibit(
        id=6,
        title="Tool bloat",
        pitfall="Never deleting a tool, and paying for all of them every turn",
        question="What timezone are the payroll timestamps in?",
        bad_choice="47 tools registered -- every tool from exhibits 1-5 plus the usual "
        "accretion (get_config AND get_settings, list_alerts AND list_events).",
        good_choice="7 curated tools. Each one finishes a question; none duplicates another.",
        bad_file="server/bad/e6_tool_bloat.py",
        good_file="server/good/e6_curated.py",
        watch="'Schema tokens' -- what you spend before the user's first word. "
        "Then watch how many wrong tools get called first.",
        grade=grade_e6,
        focus="schema",
    ),
    7: Exhibit(
        id=7,
        title="The 7/10 tool (no fix ships)",
        pitfall="Believing code review can tell you a tool works",
        question="Is Deniz Okonkwo's payroll healthy?",
        bad_choice="There is no bad version. employee_payroll_health passes every rule in "
        "exhibits 1-6: task-shaped, bounded, precisely described, read-only, on a tiny "
        "surface.",
        good_choice="Identical file, imported verbatim. The fix is not a patch -- it is "
        "running the thing 10 times and looking at the pass rate.",
        bad_file="server/bad/e7_brittle.py",
        good_file="server/good/e7_brittle.py",
        watch="The pass rate across 10 paraphrases of ONE question. Nothing in the code "
        "told you which number you were going to get.",
        grade=grade_e7,
        focus="",
        paired=False,
        default_runs=10,
        questions=[
            "Is Deniz Okonkwo's payroll healthy?",
            "How is Deniz Okonkwo doing on payroll?",
            "Check deniz okonkwo's payroll please.",
            "Deniz Okonkwo - any payroll problems?",
            "Give me the payroll health for D. Okonkwo.",
            "Is Deniz Okonkwo's pay run ok?",
            "payroll status of Deniz Okonkwo?",
            "Has Okonkwo been failing payroll?",
            "I want a payroll health check on Deniz Okonkwo.",
            "tell me if Deniz Okonkwo's payroll is broken",
        ],
    ),
}
