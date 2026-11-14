#!/usr/bin/env bash
set -euo pipefail

# Each stage gets fresh AzureCLI@2 workload identity credentials.
required=(servicePrincipalId tenantId idToken TF_ACTION TF_PLAN_DIRECTORY
  TF_RUN_ID TF_SOURCE_VERSION TERRAFORM_VERSION TF_DEPLOYMENT_ENVIRONMENT
  TF_VAR_deployment_environment TF_VAR_resource_group_name TF_VAR_name_prefix
  TF_STATE_RESOURCE_GROUP TF_STATE_STORAGE_ACCOUNT TF_STATE_CONTAINER TF_STATE_KEY)
case "${TF_ACTION:-}" in
  plan) required+=(TF_VAR_qbo_client_id TF_VAR_qbo_client_secret TF_VAR_openai_api_key TF_VAR_qbo_environment) ;;
  apply) required+=(TF_SOURCE_BRANCH) ;;
  *) echo "TF_ACTION must be plan or apply" >&2; exit 1 ;;
esac
for name in "${required[@]}"; do
  value="${!name:-}"
  if [[ -z "$value" || "$value" == '$('* ]]; then
    echo "Missing required pipeline setting: $name" >&2
    exit 1
  fi
done

# Backstop for the Apply stage condition, in case the YAML is edited on a branch.
if [[ "$TF_ACTION" == apply && "$TF_SOURCE_BRANCH" != refs/heads/main ]]; then
  echo "Apply is only allowed from main (this run is from $TF_SOURCE_BRANCH)" >&2
  exit 1
fi

if [[ "$TF_DEPLOYMENT_ENVIRONMENT" != "$TF_VAR_deployment_environment" ]]; then
  echo "Pipeline and Terraform environment must match" >&2
  exit 1
fi

export ARM_CLIENT_ID="$servicePrincipalId"
export ARM_TENANT_ID="$tenantId"
export ARM_OIDC_TOKEN="$idToken"
export ARM_USE_OIDC=true
export ARM_USE_AZUREAD=true
export ARM_USE_CLI=false
ARM_SUBSCRIPTION_ID="$(az account show --query id --output tsv)"
export ARM_SUBSCRIPTION_ID
export TF_VAR_subscription_id="$ARM_SUBSCRIPTION_ID"
plan_path="$TF_PLAN_DIRECTORY/deployment.tfplan"
context_script="$(dirname "${BASH_SOURCE[0]}")/plan-context.py"
summary_script="$(dirname "${BASH_SOURCE[0]}")/plan-summary.py"

# Fail before accessing state if the downloaded plan belongs to another context.
if [[ "$TF_ACTION" == apply ]]; then
  python3 "$context_script" verify "$TF_PLAN_DIRECTORY"
fi

# Confirm the storage account has actually been moved to the configured group.
# Entra-authenticated blob access alone may not detect an outdated ARM group name.
az storage account show --resource-group "$TF_STATE_RESOURCE_GROUP" \
  --name "$TF_STATE_STORAGE_ACCOUNT" --query id --output tsv >/dev/null

terraform fmt -check -recursive
terraform init -input=false -lockfile=readonly \
  -backend-config="resource_group_name=$TF_STATE_RESOURCE_GROUP" \
  -backend-config="storage_account_name=$TF_STATE_STORAGE_ACCOUNT" \
  -backend-config="container_name=$TF_STATE_CONTAINER" \
  -backend-config="key=$TF_STATE_KEY"
terraform validate -no-color

if [[ "$TF_ACTION" == plan ]]; then
  mkdir -p "$TF_PLAN_DIRECTORY"
  # Collapse the verbose plan in the log; the summary below is the review aid.
  echo "##[group]Full Terraform plan"
  terraform plan -input=false -no-color -lock-timeout=5m -out="$plan_path"
  echo "##[endgroup]"
  python3 "$context_script" save "$TF_PLAN_DIRECTORY"

  # Kept outside the plan artifact directory so the artifact is unchanged.
  summary_path="${AGENT_TEMPDIRECTORY:-$TF_PLAN_DIRECTORY}/terraform-plan-summary-$TF_DEPLOYMENT_ENVIRONMENT.md"
  echo "##[section]Terraform plan summary"
  terraform show -json "$plan_path" \
    | python3 "$summary_script" "$TF_DEPLOYMENT_ENVIRONMENT" "$summary_path"
  echo "##vso[task.uploadsummary]$summary_path"
  echo "Plan saved. Apply will use this environment's saved artifact after its Environment checks."
else
  # Do not run terraform plan here. Use exactly the reviewed artifact.
  terraform apply -input=false -no-color -lock-timeout=5m "$plan_path"
  terraform output -raw application_url
  printf '\n'
fi
