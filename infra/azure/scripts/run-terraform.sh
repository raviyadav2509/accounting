#!/usr/bin/env bash
set -euo pipefail

# AzureCLI@2 supplies these only for a workload identity service connection.
required=(servicePrincipalId tenantId idToken TF_ACTION TF_PLAN_PATH
  TF_STATE_RESOURCE_GROUP TF_STATE_STORAGE_ACCOUNT TF_STATE_CONTAINER TF_STATE_KEY
  TF_VAR_qbo_client_id TF_VAR_qbo_client_secret TF_VAR_openai_api_key)
for name in "${required[@]}"; do
  value="${!name:-}"
  if [[ -z "$value" || "$value" == '$('* ]]; then
    echo "Missing required pipeline setting: $name" >&2
    exit 1
  fi
done
case "$TF_ACTION" in
  plan|apply) ;;
  *) echo "TF_ACTION must be plan or apply" >&2; exit 1 ;;
esac

export ARM_CLIENT_ID="$servicePrincipalId"
export ARM_TENANT_ID="$tenantId"
export ARM_OIDC_TOKEN="$idToken"
export ARM_USE_OIDC=true
export ARM_USE_AZUREAD=true
export ARM_USE_CLI=false
ARM_SUBSCRIPTION_ID="$(az account show --query id --output tsv)"
export ARM_SUBSCRIPTION_ID
export TF_VAR_subscription_id="$ARM_SUBSCRIPTION_ID"
trap 'rm -f -- "$TF_PLAN_PATH"' EXIT

terraform fmt -check -recursive
terraform init -input=false -lockfile=readonly \
  -backend-config="resource_group_name=$TF_STATE_RESOURCE_GROUP" \
  -backend-config="storage_account_name=$TF_STATE_STORAGE_ACCOUNT" \
  -backend-config="container_name=$TF_STATE_CONTAINER" \
  -backend-config="key=$TF_STATE_KEY"
terraform validate -no-color
terraform plan -input=false -no-color -lock-timeout=5m -out="$TF_PLAN_PATH"
if [[ "$TF_ACTION" == apply ]]; then
  # Apply exactly the plan generated in this job; never publish secret-bearing plans.
  terraform apply -input=false -no-color -lock-timeout=5m "$TF_PLAN_PATH"
  terraform output -raw application_url
  printf '\n'
else
  echo "Plan completed. Run this pipeline with action=apply to generate and apply a new plan."
fi
