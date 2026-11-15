#!/usr/bin/env bash
set -euo pipefail

resource_group="rg-quickbooks-dev"
package="${APP_PACKAGE:?APP_PACKAGE must point to the application ZIP}"
if [[ ! -f "$package" ]]; then
  echo "Application package does not exist: $package" >&2
  exit 1
fi

app_names="$(az webapp list --resource-group "$resource_group" \
  --query "[?tags.application=='quickbooks-accounting' && tags.environment=='dev' && tags.managed_by=='terraform' && starts_with(name, 'quickbooks-dev-')].name" \
  --output tsv)"
if [[ -z "$app_names" ]]; then
  echo "No Terraform-managed Dev Web App found in $resource_group." >&2
  exit 1
fi
mapfile -t apps <<< "$app_names"
if [[ "${#apps[@]}" -ne 1 ]]; then
  echo "Expected exactly one Terraform-managed Dev Web App in $resource_group; found ${#apps[@]}." >&2
  exit 1
fi

echo "Deploying the tested package to ${apps[0]} in $resource_group."
az webapp deploy --resource-group "$resource_group" --name "${apps[0]}" \
  --src-path "$package" --type zip --output none
echo "Deployment completed for ${apps[0]}."
