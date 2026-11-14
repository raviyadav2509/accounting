"""Summarise a saved Terraform plan for review in Azure DevOps.

Usage: terraform show -json <plan> | plan-summary.py <environment> <markdown-path>

Prints a plain-text report to the pipeline log with one collapsible section per
resource, and writes a markdown version for the run's Extensions tab. Values
Terraform marks as sensitive, and values whose attribute names look like
secrets, are always masked.
"""
import json
import re
import sys

# Display order: the most disruptive changes first.
ACTIONS = (
    ("delete", "-", "destroy", "Destroy"),
    ("replace", "-/+", "replace", "Replace"),
    ("forget", ".", "forget", "Forget (stop managing, not deleted)"),
    ("create", "+", "create", "Create"),
    ("update", "~", "update", "Update in place"),
    ("move", ">", "move", "Move address only"),
    ("import", "<", "import", "Import"),
)
SYMBOL = {key: symbol for key, symbol, _, _ in ACTIONS}
VERB = {key: verb for key, _, verb, _ in ACTIONS}
LABEL = {key: label for key, _, _, label in ACTIONS}

SENSITIVE = "(sensitive)"
UNKNOWN = "(known after apply)"
ABSENT = "(none)"
MISSING = (ABSENT, None)
SENSITIVE_CHANGED = "(sensitive, changed)"
ACTION_REASONS = {
    "delete_because_no_resource_config": "removed from configuration",
    "delete_because_wrong_repetition": "count/for_each changed",
    "delete_because_count_index": "count reduced",
    "delete_because_each_key": "for_each key removed",
    "delete_because_no_module": "module removed",
    "delete_because_no_move_target": "move target missing",
    "replace_because_tainted": "tainted",
    "replace_by_request": "replacement requested (-replace)",
    "replace_by_triggers": "replace_triggered_by",
}
SECRET_NAME = re.compile(
    r"secret|password|passwd|token|key|credential|connection_?string|(^|_)sas(_|$)", re.I
)


def classify(change):
    actions = change.get("actions", [])
    if sorted(actions) == ["create", "delete"]:
        return "replace"
    if actions in (["delete"], ["forget"], ["create"], ["update"]):
        return actions[0]
    if change.get("importing"):
        return "import"
    return None


def _child(container, key):
    if isinstance(container, dict):
        return container.get(key)
    if isinstance(container, list) and isinstance(key, int) and key < len(container):
        return container[key]
    return None


def flatten(value, unknown=None, sensitive=None, path=()):
    """Map attribute paths to (display, raw) pairs; display masks secrets."""
    if sensitive is True or (path and SECRET_NAME.search(str(path[-1]))):
        if value is None and unknown is not True:
            return {}
        return {path: (SENSITIVE, json.dumps(value, sort_keys=True))}
    if unknown is True:
        return {path: (UNKNOWN, UNKNOWN)}
    if isinstance(value, dict) or isinstance(unknown, dict):
        keys = set(value or {}) | set(unknown if isinstance(unknown, dict) else {})
        items = ((key, _child(value, key)) for key in sorted(keys, key=str))
    elif isinstance(value, list) or isinstance(unknown, list):
        length = max(len(value or []), len(unknown if isinstance(unknown, list) else []))
        items = ((index, _child(value, index)) for index in range(length))
    else:
        return {} if value is None else {path: (json.dumps(value), json.dumps(value))}
    flat = {}
    for key, child in items:
        flat.update(flatten(
            child, _child(unknown, key), _child(sensitive, key), path + (key,)
        ))
    return flat


def path_text(path):
    text = ""
    for part in path:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text


def resource_rows(change, action):
    """Return (path, before, after, forces_replacement) for attributes that matter."""
    before = flatten(change.get("before"), None, change.get("before_sensitive"))
    after = flatten(
        change.get("after"), change.get("after_unknown"), change.get("after_sensitive")
    )
    forcing = [tuple(path) for path in change.get("replace_paths") or []]
    rows = []
    for path in sorted(set(before) | set(after), key=lambda p: [str(x) for x in p]):
        (old, old_raw), (new, new_raw) = before.get(path, MISSING), after.get(path, MISSING)
        if action == "delete":
            new = None
        elif action == "create":
            old = None
        elif old_raw == new_raw:
            continue
        elif old == new == SENSITIVE:
            new = SENSITIVE_CHANGED
        forces = any(path[:len(prefix)] == prefix for prefix in forcing)
        rows.append((path_text(path), old, new, forces))
    return rows


def display_name(change):
    """Azure resource name, e.g. 'old -> new' when a replacement renames it."""
    names = [
        (change.get(side) or {}).get("name")
        for side in ("before", "after")
        if isinstance(change.get(side), dict)
    ]
    names = [name for name in names if isinstance(name, str)]
    if len(names) == 2 and names[0] != names[1]:
        return f"{names[0]} -> {names[1]}"
    return names[0] if names else ""


def summarise(plan):
    resources = []
    for resource in plan.get("resource_changes", []):
        if resource.get("mode") == "data":
            continue
        change = resource.get("change", {})
        action = classify(change)
        address = resource["address"]
        previous = resource.get("previous_address")
        moved = previous if previous and previous != address else None
        if action is None:
            if not moved:
                continue
            action = "move"
        rows = [] if action in ("forget", "move") else resource_rows(change, action)
        resources.append({
            "action": action,
            "address": address,
            "moved_from": moved,
            "name": display_name(change),
            "rows": rows,
            "why": ACTION_REASONS.get(resource.get("action_reason"), ""),
        })
    order = [key for key, *_ in ACTIONS]
    resources.sort(key=lambda r: (order.index(r["action"]), r["address"]))

    outputs = []
    for name, change in sorted((plan.get("output_changes") or {}).items()):
        if change.get("actions") == ["no-op"]:
            continue
        key = (name,)  # Lets flatten() mask outputs with secret-like names.
        old = flatten(change.get("before"), None, change.get("before_sensitive"), key)
        new = flatten(
            change.get("after"), change.get("after_unknown"), change.get("after_sensitive"), key
        )
        outputs.append((name, old.get(key, MISSING)[0], new.get(key, MISSING)[0]))
    return resources, outputs


def counts(resources):
    totals = {key: 0 for key, *_ in ACTIONS}
    for resource in resources:
        totals[resource["action"]] += 1
    return totals


def headline(totals):
    parts = [f"{totals[key]} to {VERB[key]}" for key, *_ in ACTIONS if totals[key]]
    return "Plan: " + ", ".join(parts) + "." if parts else "No infrastructure changes."


def reason(resource):
    """One-line explanation used in the overview and markdown tables."""
    rows = resource["rows"]
    if resource["why"]:
        return resource["why"]
    if resource["action"] == "replace":
        forced = [path for path, _, _, forces in rows if forces]
        return "forced by: " + ", ".join(forced) if forced else "replacement required"
    if resource["action"] == "update":
        return "changes: " + ", ".join(path for path, *_ in rows)
    if resource["moved_from"]:
        return f"moved from {resource['moved_from']}"
    return ""


def render_log(resources, outputs, environment):
    totals = counts(resources)
    lines = [f"##[section]Terraform plan summary: {environment}", headline(totals)]
    if not resources:
        return lines
    width = max(len(r["address"]) for r in resources)
    lines += ["", "Overview:"]
    for r in resources:
        name = f"  name: {r['name']}" if r["name"] else ""
        why = f"  [{reason(r)}]" if reason(r) else ""
        lines.append(f"  {SYMBOL[r['action']]:>3} {VERB[r['action']]:<8} {r['address']:<{width}}{name}{why}")
    lines += ["", "Details (expand a resource below to see its attribute changes):"]
    for r in resources:
        title = f"{SYMBOL[r['action']]} {VERB[r['action']]}: {r['address']}"
        if r["name"]:
            title += f" ({r['name']})"
        lines.append(f"##[group]{title}")
        if r["moved_from"]:
            lines.append(f"    moved from: {r['moved_from']}")
        if r["action"] == "forget":
            lines.append("    Removed from Terraform state only; the Azure resource is kept.")
        path_width = max((len(row[0]) for row in r["rows"]), default=0)
        for path, old, new, forces in r["rows"]:
            if old is None:
                text = f"+ {path:<{path_width}} = {new}"
            elif new is None:
                text = f"- {path:<{path_width}} = {old}"
            else:
                text = f"~ {path:<{path_width}} : {old} -> {new}"
            lines.append(f"    {text}{'   # forces replacement' if forces else ''}")
        lines.append("##[endgroup]")
    if outputs:
        lines.append(f"##[group]Outputs changing ({len(outputs)})")
        lines += [f"    ~ {name} : {old} -> {new}" for name, old, new in outputs]
        lines.append("##[endgroup]")
    if totals["delete"] or totals["replace"]:
        lines.append(
            "##[warning]This plan destroys or replaces resources. "
            "Back up any data they hold before approving Apply."
        )
    return lines


def md_cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_markdown(resources, outputs, environment):
    totals = counts(resources)
    lines = [f"## Terraform plan: {environment}", "", f"**{headline(totals)}**"]
    if not resources:
        return "\n".join(lines) + "\n"
    if totals["delete"] or totals["replace"]:
        lines += [
            "",
            "> **Warning:** this plan destroys or replaces resources. "
            "Back up any data they hold before approving Apply.",
        ]
    lines += ["", "| Action | Resource | Azure name | Why |", "| --- | --- | --- | --- |"]
    for r in resources:
        lines.append(
            f"| {LABEL[r['action']]} | `{r['address']}` | "
            f"{md_cell(r['name'])} | {md_cell(reason(r))} |"
        )
    changed = [r for r in resources if r["action"] in ("replace", "update") and r["rows"]]
    for r in changed:
        lines += [
            "", f"#### {LABEL[r['action']]}: `{r['address']}`", "",
            "| Attribute | Before | After | Forces replacement |",
            "| --- | --- | --- | :---: |",
        ]
        lines += [
            f"| `{path}` | {md_cell(old)} | {md_cell(new)} | {'yes' if forces else ''} |"
            for path, old, new, forces in r["rows"]
        ]
    if outputs:
        lines += ["", "#### Outputs", "", "| Output | Before | After |", "| --- | --- | --- |"]
        lines += [f"| `{n}` | {md_cell(o)} | {md_cell(a)} |" for n, o, a in outputs]
    lines += ["", "Full attribute lists for every resource are in the Plan step log."]
    return "\n".join(lines) + "\n"


def main():
    environment, summary_path = sys.argv[1], sys.argv[2]
    resources, outputs = summarise(json.load(sys.stdin))
    with open(summary_path, "w", encoding="utf-8") as handle:
        handle.write(render_markdown(resources, outputs, environment))
    print("\n".join(render_log(resources, outputs, environment)))
    totals = counts(resources)
    destructive = totals["delete"] + totals["replace"]
    if destructive:
        # Surfaces on the run summary page as a warning annotation.
        print(
            f"##vso[task.logissue type=warning]Terraform plan destroys or "
            f"replaces {destructive} resource(s). Review the plan summary."
        )


if __name__ == "__main__":
    main()
