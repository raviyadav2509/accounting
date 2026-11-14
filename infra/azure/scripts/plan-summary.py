"""Summarise a saved Terraform plan without printing any attribute values.

Reads `terraform show -json <plan>` from stdin. Values are deliberately omitted
because the plan contains secrets; only addresses, actions and changed
attribute names are reported.
"""
import json
import sys

# Display order: the most disruptive changes first.
ACTIONS = (
    ("delete", "Destroy"),
    ("replace", "Replace"),
    ("forget", "Forget (stop managing, not deleted)"),
    ("create", "Create"),
    ("update", "Update in place"),
    ("move", "Move address only"),
    ("import", "Import"),
)


def classify(change):
    actions = change.get("actions", [])
    if sorted(actions) == ["create", "delete"]:
        return "replace"
    if actions == ["delete"]:
        return "delete"
    if actions == ["forget"]:
        return "forget"
    if actions == ["create"]:
        return "create"
    if actions == ["update"]:
        return "update"
    if change.get("importing"):
        return "import"
    return None


def changed_attributes(change):
    before = change.get("before") or {}
    after = change.get("after") or {}
    unknown = change.get("after_unknown") or {}
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    keys = set(before) | set(after) | set(unknown)
    return sorted(
        key for key in keys
        if before.get(key) != after.get(key) or unknown.get(key) is True
    )


def summarise(plan):
    groups = {key: [] for key, _ in ACTIONS}
    for resource in plan.get("resource_changes", []):
        if resource.get("mode") == "data":
            continue
        change = resource.get("change", {})
        action = classify(change)
        address = resource["address"]
        previous = resource.get("previous_address")
        if action is None:
            if previous and previous != address:
                groups["move"].append(f"`{previous}` -> `{address}`")
            continue
        detail = f"`{address}`"
        if previous and previous != address:
            detail += f" (moved from `{previous}`)"
        if action == "replace":
            paths = sorted({
                ".".join(str(part) for part in path)
                for path in change.get("replace_paths") or []
            })
            if paths:
                detail += f" (forced by: {', '.join(paths)})"
        elif action == "update":
            names = changed_attributes(change)
            if names:
                detail += f" (changes: {', '.join(names)})"
        groups[action].append(detail)

    outputs = sorted(
        name for name, change in (plan.get("output_changes") or {}).items()
        if change.get("actions") != ["no-op"]
    )
    return groups, outputs


def render(groups, outputs, environment):
    counts = {key: len(items) for key, items in groups.items()}
    lines = [f"## Terraform plan summary: {environment}", ""]
    if not any(counts.values()):
        lines.append("**No infrastructure changes.**")
    else:
        lines += ["| Action | Count |", "| --- | ---: |"]
        lines += [
            f"| {label} | {counts[key]} |"
            for key, label in ACTIONS if counts[key]
        ]
        for key, label in ACTIONS:
            if groups[key]:
                lines += ["", f"### {label}", ""]
                lines += [f"- {item}" for item in groups[key]]
    if outputs:
        lines += ["", f"Outputs changing: {', '.join(outputs)}"]
    if counts["delete"] or counts["replace"]:
        lines += [
            "",
            "> **Warning:** this plan destroys or replaces resources. "
            "Back up data before approving Apply.",
        ]
    return "\n".join(lines) + "\n"


def main():
    environment, summary_path = sys.argv[1], sys.argv[2]
    groups, outputs = summarise(json.load(sys.stdin))
    summary = render(groups, outputs, environment)
    with open(summary_path, "w", encoding="utf-8") as handle:
        handle.write(summary)
    print(summary)
    destructive = len(groups["delete"]) + len(groups["replace"])
    if destructive:
        # Surfaces on the run summary page as a warning annotation.
        print(
            f"##vso[task.logissue type=warning]Terraform plan destroys or "
            f"replaces {destructive} resource(s). Review the plan summary."
        )


if __name__ == "__main__":
    main()
