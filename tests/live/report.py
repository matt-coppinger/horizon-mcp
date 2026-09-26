"""Optional HTML report of a live run (HZ_LIVE_REPORT=path). Rows are already redacted."""
from __future__ import annotations

import html
import json

# Tools the suite never calls, and why.
NEVER_CALLED = {
    "trigger_connection_server_backup": "Starts a real Connection Server backup",
    "end_remote_application": "Kills a user's running application",
    "get_remote_assistance_ticket": "Issues a live remote-control credential for a user session",
    "create_desktop_pool": "Provisions VMs",
    "update_desktop_pool": "Changes pool config",
    "delete_desktop_pool": "Destructive",
    "desktop_pool_action": "Changes pool state",
    "machine_action": "Restarts/resets machines",
    "assign_machine_users": "Changes machine assignments",
    "disconnect_sessions": "Disconnects real users",
    "logoff_sessions": "Logs off real users",
    "reset_or_restart_sessions": "Resets real users' machines",
    "send_message_to_sessions": "Messages real users",
}
OPT_IN = {
    **dict.fromkeys(("rdsh_farm_action", "update_rdsh_farm", "create_application_pool", "update_application_pool",
                     "delete_application_pool", "set_pool_entitlements", "update_global_policies",
                     "update_settings"), "Opt-in write test (HZ_LIVE_WRITES=1) — not run or not reached"),
    **dict.fromkeys(("create_rdsh_farm", "delete_rdsh_farm"),
                    "Opt-in destructive test (HZ_LIVE_DESTRUCTIVE=1) — not run or not reached"),
}

_CSS = """
:root{--bg:#f7f7f5;--card:#fff;--fg:#1c1c1a;--mut:#6b6b66;--line:#e4e4df;--code:#f1f1ed;
--pass:#1f7a4d;--pass-bg:#e3f3ea;--empty:#5b6b7a;--empty-bg:#e8edf2;--warn:#8a5a00;--warn-bg:#fbefd6;
--fail:#b3261e;--fail-bg:#fbe4e2;--skip:#6b6b66;--skip-bg:#ececE8}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1d1d1b;--fg:#ececE8;--mut:#9a9a94;--line:#2e2e2b;
--code:#262624;--pass:#6fd19c;--pass-bg:#173626;--empty:#a9b8c6;--empty-bg:#232c34;--warn:#f0c46a;--warn-bg:#3a2e12;
--fail:#ff8a80;--fail-bg:#3d1b18;--skip:#9a9a94;--skip-bg:#262624}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:32px 16px 64px}h1{margin:0 0 4px;font-size:24px}
.meta{color:var(--mut);margin-bottom:24px}h2{font-size:16px;margin:32px 0 8px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-bottom:8px}
.tile{border:1px solid var(--line);background:var(--card);border-radius:10px;padding:12px;text-align:left;cursor:pointer;color:inherit;font:inherit}
.tile b{display:block;font-size:26px}.tile span{color:var(--mut)}.tile.active{outline:2px solid var(--fg)}
.tile.pass b{color:var(--pass)}.tile.empty b{color:var(--empty)}.tile.warn b{color:var(--warn)}.tile.fail b{color:var(--fail)}.tile.skip b{color:var(--skip)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{font-size:12px;color:var(--mut);font-weight:600}
tr:last-child td{border-bottom:0}.num{text-align:right;white-space:nowrap;color:var(--mut)}.sum{color:var(--mut);word-break:break-word}
.badge{font-size:11px;font-weight:700;padding:2px 8px;border-radius:99px;white-space:nowrap}
.badge.pass{color:var(--pass);background:var(--pass-bg)}.badge.empty{color:var(--empty);background:var(--empty-bg)}
.badge.warn{color:var(--warn);background:var(--warn-bg)}.badge.fail{color:var(--fail);background:var(--fail-bg)}.badge.skip{color:var(--skip);background:var(--skip-bg)}
summary{cursor:pointer}code{font-family:ui-monospace,Menlo,monospace;font-size:13px}
pre{background:var(--code);padding:10px;border-radius:6px;overflow:auto;max-height:420px;font-size:12px;white-space:pre-wrap;word-break:break-word}
h4{margin:10px 0 4px;font-size:12px;color:var(--mut)}td:nth-child(2){max-width:520px}
@media (max-width:640px){td:nth-child(3),th:nth-child(3){display:none}}
"""

_JS = """document.querySelectorAll('.tile').forEach(t=>t.onclick=()=>{const on=!t.classList.contains('active');
document.querySelectorAll('.tile').forEach(x=>x.classList.remove('active'));if(on)t.classList.add('active');
const f=on?t.dataset.filter:null;document.querySelectorAll('tr[data-status]').forEach(r=>r.style.display=!f||r.dataset.status===f?'':'none');});"""


def _esc(x) -> str:
    return html.escape(str(x))


def _detail(row: dict) -> str:
    parts = []
    if row["args"]:
        parts.append(f"<h4>Arguments</h4><pre>{_esc(json.dumps(row['args'], indent=2, default=str))}</pre>")
    if row["body"] is not None:
        body = row["body"]
        text = body if isinstance(body, str) else json.dumps(body, indent=2, default=str)
        if len(text) > 20000:
            text = text[:20000] + f"\n… truncated ({len(text):,} chars total)"
        parts.append(f"<h4>Response</h4><pre>{_esc(text)}</pre>")
    return "".join(parts)


def render(rows: list[dict], tools: list[str], prompts: list[dict], *, started: str, duration: float,
           outcomes: dict[str, int]) -> str:
    called = {r["tool"].split(" (")[0] for r in rows if r["status"] != "SKIP"}
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("PASS", "EMPTY", "WARN", "FAIL", "SKIP")}
    not_run = [(t, NEVER_CALLED.get(t) or OPT_IN.get(t) or "Not called — dependency missing (see skips)")
               for t in sorted(tools) if t not in called]
    groups = list(dict.fromkeys(r["group"] for r in rows))

    sections = []
    for g in groups:
        trs = []
        for r in (x for x in rows if x["group"] == g):
            detail = _detail(r)
            name = f"<code>{_esc(r['tool'])}</code>"
            cell = f"<details><summary>{name}</summary>{detail}</details>" if detail else name
            trs.append(f'<tr data-status="{r["status"]}"><td><span class="badge {r["status"].lower()}">{r["status"]}'
                       f'</span></td><td>{cell}</td><td class="sum">{_esc(r["summary"])}</td>'
                       f'<td class="num">{r["ms"] or "–"}</td></tr>')
        sections.append(f"<section><h2>{_esc(g)}</h2><table><thead><tr><th>Status</th><th>Tool</th><th>Result</th>"
                        f"<th class='num'>ms</th></tr></thead><tbody>{''.join(trs)}</tbody></table></section>")

    pr = "".join(f"<tr><td><span class='badge {'pass' if p['approved'] else 'fail'}'>"
                 f"{'Proceed' if p['approved'] else 'Cancel'}</span></td><td class='sum'>{_esc(p['message'])}</td></tr>"
                 for p in prompts)
    nr = "".join(f"<tr><td><code>{_esc(t)}</code></td><td class='sum'>{_esc(why)}</td></tr>" for t, why in not_run)
    tiles = "".join(f'<button class="tile {s.lower()}" data-filter="{s}"><b>{n}</b><span>{s.title()}</span></button>'
                    for s, n in counts.items())
    tests = ", ".join(f"{n} {k}" for k, n in outcomes.items() if n)

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Horizon MCP Live Report</title>
<style>{_CSS}</style></head><body><main>
<h1>Horizon MCP live test report</h1>
<div class="meta">{_esc(started)} · {len(called)} of {len(tools)} tools called · {duration:.1f}s · pytest: {_esc(tests)}
· via MCP stdio · secrets redacted</div>
<div class="tiles">{tiles}</div>
<div class="meta">Click a tile to filter. Click a tool name to see its arguments and response.</div>
{''.join(sections)}
<section><h2>Confirmation prompts ({len(prompts)})</h2><table><thead><tr><th>Answer</th><th>Prompt</th></tr></thead>
<tbody>{pr}</tbody></table></section>
<section><h2>Not called ({len(not_run)})</h2><table><thead><tr><th>Tool</th><th>Reason</th></tr></thead>
<tbody>{nr}</tbody></table></section>
</main><script>{_JS}</script></body></html>"""
