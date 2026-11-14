"""Bind a saved Terraform plan to its pipeline run, commit and Azure backend."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

CONTEXT_KEYS = (
    "TF_RUN_ID", "TF_SOURCE_VERSION", "TERRAFORM_VERSION",
    "ARM_SUBSCRIPTION_ID", "ARM_TENANT_ID", "ARM_CLIENT_ID",
    "TF_STATE_RESOURCE_GROUP", "TF_STATE_STORAGE_ACCOUNT",
    "TF_STATE_CONTAINER", "TF_STATE_KEY",
    "TF_DEPLOYMENT_ENVIRONMENT", "TF_VAR_deployment_environment",
    "TF_VAR_resource_group_name", "TF_VAR_name_prefix",
)


def process(action, directory):
    directory = Path(directory)
    plan = directory / "deployment.tfplan"
    manifest = directory / "context.json"
    context = {key: os.environ[key] for key in CONTEXT_KEYS}
    if any(not value or value.startswith("$(") for value in context.values()):
        raise ValueError("Plan context contains missing pipeline settings.")
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    if commit != context["TF_SOURCE_VERSION"]:
        raise ValueError("Checkout does not match this run's source commit.")
    context["plan_sha256"] = hashlib.sha256(plan.read_bytes()).hexdigest()
    if action == "save":
        manifest.write_text(json.dumps(context, sort_keys=True, indent=2) + "\n")
    elif action == "verify":
        if json.loads(manifest.read_text()) != context:
            raise ValueError(
                "Saved plan checksum or run/commit/Azure/backend context changed. "
                "Reject this run and create a new plan."
            )
    else:
        raise ValueError("Expected save or verify.")


if __name__ == "__main__":
    try:
        process(sys.argv[1], sys.argv[2])
    except (OSError, ValueError, KeyError, IndexError, subprocess.CalledProcessError) as exc:
        print(f"Plan verification failed: {exc}", file=sys.stderr)
        sys.exit(1)
