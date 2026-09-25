"""Shared tool annotation presets.

See the MCP spec's ToolAnnotations (readOnlyHint, destructiveHint, idempotentHint,
openWorldHint) — clients use these as hints for auto-approval / confirmation UX.
None of these Horizon tools interact with the open web, so openWorldHint is always
False here.
"""

READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}

# Creates new state or sends a one-off request (login, notifications, triggering a
# backup job) — not idempotent, not destructive.
ADDITIVE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

# Sets state to a specific value — calling again with the same arguments leaves
# things as they were (config updates, enable/disable toggles, reassignments).
IDEMPOTENT_UPDATE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

# May destroy data or access (deletes, rebuilds/resets, logoffs, force-closing apps).
DESTRUCTIVE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False}

# Overwrites existing configuration or cuts off access in a way that's reversible but
# disruptive (pool/farm config updates, disabling pools or farms, unassigning users).
# destructiveHint=True so clients prompt before running these.
DESTRUCTIVE_UPDATE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}
