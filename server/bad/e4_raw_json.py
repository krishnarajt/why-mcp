"""EXHIBIT 4 (bad) -- raw JSON, every field, nothing shaped for a reader.

DESIGN CHOICE: serialise the ORM. Nested manager objects, surrogate ids, nulls,
ISO-8601 timestamps with microseconds, a base64 `trace_digest` nobody asked
for, and `_links` for good measure.

Why it feels right: it is "complete" and "machine readable". Why it is wrong:
the model is not a machine in the sense you mean. It reads this like prose, at
roughly 20,000 tokens, and then has to do arithmetic on it to answer "whose
payroll is worst". Nulls invite hallucinated field names; microsecond
timestamps invite date arithmetic errors; the ids are pure noise the model will
helpfully quote back at the user.

The good version answers the same question in a 12-line table and ~300 tokens.
"""

from __future__ import annotations

import base64
import hashlib

from hr import data
from server.common import dumps


def register(mcp) -> None:
    @mcp.tool()
    def get_all_employee_payroll_stats() -> str:
        """Returns payroll statistics for all employees."""
        out = []
        for emp in data.all_employees():
            stats = data.payroll_stats(emp["id"])
            checks = data.paychecks_for_employee(emp["id"], limit=10)
            dept = data.q("SELECT * FROM departments WHERE id = ?", (emp["department_id"],))[0]
            mgr_rows = data.q("SELECT * FROM employees WHERE id = ?", (emp["manager_id"],))
            mgr = mgr_rows[0] if mgr_rows else None
            out.append(
                {
                    "employee_id": emp["id"],
                    "employee_uuid": f"emp_{emp['id']:08x}-0000-4000-8000-{emp['id']:012x}",
                    "name": emp["name"],
                    "email": emp["email"],
                    "title": emp["title"],
                    "employment_status": emp["status"],
                    "payroll_hold": bool(emp["payroll_hold"]),
                    "hired_at": emp["hired_at"],
                    "terminated_at": None,
                    "deleted_at": None,
                    "department": {
                        "department_id": dept["id"],
                        "name": dept["name"],
                        "cost_center": dept["cost_center"],
                        "location": dept["location"],
                        "head": dept["head"],
                        "budget": {"monthly_limit_usd": 500000, "committed_usd": None},
                    },
                    "manager": None
                    if mgr is None
                    else {
                        "employee_id": mgr["id"],
                        "name": mgr["name"],
                        "email": mgr["email"],
                        "title": mgr["title"],
                        "avatar_url": None,
                        "preferences": {"notify_email": True, "notify_slack": None},
                    },
                    "compensation": {
                        "annual_salary_usd": emp["salary"],
                        "currency": "USD",
                        "pay_frequency": "semi-monthly",
                        "band": None,
                    },
                    "statistics_window_days": data.STATS_DAYS,
                    "statistics": {
                        "paychecks_total": stats["total"],
                        "paychecks_paid": stats["paid"],
                        "paychecks_failed": stats["failed"],
                        "success_ratio": stats["rate"],
                        "success_ratio_pct_str": f"{stats['rate'] * 100:.4f}%",
                        "p50_settle_ms": None,
                        "p95_settle_ms": None,
                    },
                    "paychecks": [
                        {
                            "paycheck_id": c["id"],
                            "period": c["period"],
                            "status": c["status"],
                            "error_code": c["error_code"],
                            "net_pay_usd": c["net_pay"],
                            "issued_at": c["issued_at"].replace("Z", ".000000+00:00"),
                            "settled_at": c["settled_at"].replace("Z", ".000000+00:00"),
                            "trace_digest": base64.b64encode(
                                hashlib.sha256(str(c["id"]).encode()).digest()
                            ).decode(),
                            "reissue_of": None,
                            "attachments": [],
                        }
                        for c in checks
                    ],
                    "_links": {
                        "self": f"/api/v1/employees/{emp['id']}",
                        "paychecks": f"/api/v1/employees/{emp['id']}/paychecks",
                        "department": f"/api/v1/departments/{emp['department_id']}",
                    },
                }
            )
        return dumps({"object": "list", "count": len(out), "has_more": False, "data": out})
