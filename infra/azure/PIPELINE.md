# Deploy Terraform with Azure Pipelines

Use the repository-root `azure-pipelines-terraform.yml` as a **separate pipeline**.
The existing `azure-pipelines.yml` continues testing the application. This pipeline
provisions infrastructure only; deploy the Python app using the README afterwards.
It runs manually, defaults to `plan`, and uses the F1/sandbox Terraform defaults.

## 1. Create the Azure service connection

In Azure DevOps, open **Project settings → Service connections → New service
connection → Azure Resource Manager**. Select **Workload identity federation**,
your subscription, and name it `azure-accounting-wif`. Authorize this pipeline
to use it. A different name can be selected when running the pipeline.

Because Terraform creates a resource group, the identity needs **Contributor**
at subscription scope. Register `Microsoft.Web` beforehand, or ensure the
identity can register providers. Give the identity **Storage Blob Data
Contributor** on the state container/account separately. Contributor alone does
not grant blob data access. The pipeline does not create role assignments.

## 2. Create state storage once

Use Azure Cloud Shell (Bash), signed in as an administrator allowed to assign
roles. Replace the subscription, globally unique storage name and service
connection identity's **principal/object ID** (not its application/client ID).
Find the identity in the service connection's managed identity/app registration.

```bash
az account set --subscription '<subscription-id>'
state_rg='rg-accounting-tfstate'
state_account='<unique-lowercase-storage-name>'
pipeline_object_id='<service-connection-principal-object-id>'
az group create --name "$state_rg" --location australiaeast
az storage account create --name "$state_account" --resource-group "$state_rg" \
  --location australiaeast --sku Standard_LRS --kind StorageV2 \
  --https-only true --min-tls-version TLS1_2 \
  --allow-blob-public-access false --allow-shared-key-access false
state_scope=$(az storage account show --name "$state_account" \
  --resource-group "$state_rg" --query id --output tsv)
az role assignment create --assignee-object-id "$pipeline_object_id" \
  --assignee-principal-type ServicePrincipal \
  --role 'Storage Blob Data Contributor' --scope "$state_scope"
az storage account blob-service-properties update --account-name "$state_account" \
  --resource-group "$state_rg" --enable-versioning true \
  --enable-delete-retention true --delete-retention-days 7
```

Give your Cloud Shell user **Storage Blob Data Contributor** on this account too,
then create a private container after role assignments have propagated:

```bash
az storage container create --name tfstate --account-name "$state_account" \
  --auth-mode login --public-access off
```

Keep the state account separate from the application resource group. Blob storage,
versions and retained deleted blobs incur a small usage charge even with F1 hosting.
State contains application secrets; restrict access to the account and container.
The hosted agent must be able to reach the storage endpoint. A private/firewalled
account requires an appropriately connected self-hosted agent.

**Existing deployment:** if Terraform was already applied with local state, migrate
that state into this backend before running the pipeline. Use `terraform init
-migrate-state` with the four backend arguments below from the original working
directory containing the state. Do not point an empty backend at existing resources.

## 3. Add pipeline variables

In **Pipelines → Library**, create the variable group `accounting-terraform` and
authorize only the new pipeline. Add:

| Variable | Example / value | Secret |
| --- | --- | --- |
| `stateResourceGroup` | `rg-accounting-tfstate` | No |
| `stateStorageAccount` | Your storage account name | No |
| `stateContainer` | `tfstate` | No |
| `stateKey` | `accounting-dev.tfstate` | No |
| `qboClientId` | Intuit sandbox client ID | Yes |
| `qboClientSecret` | Intuit sandbox client secret | Yes |
| `openaiApiKey` | OpenAI API key | Yes |

The subscription ID is taken from the service connection. Do not commit
`terraform.tfvars`, state, plan files or real keys. Keep the same state key for
this environment across branches and runs. A different environment needs separate
state and a distinct app name prefix. To override defaults, add explicit `TF_VAR_*`
environment mappings to the YAML; Azure secret variables are not exported implicitly.

## 4. Create and run the pipeline

1. Open **Pipelines → New pipeline** and select the repository (GitHub or Azure Repos).
2. Choose **Existing Azure Pipelines YAML file**, branch `feature/annual-tax-return`,
   path `/azure-pipelines-terraform.yml`. If using Azure Repos, first sync the commit
   containing this YAML and `infra/azure` from GitHub.
3. Run with `action: plan`. The job installs checksum-verified Terraform 1.9.8,
   initializes remote state, checks formatting, validates and prints the plan.
4. Review the plan. Run again with `action: apply` to generate a **new plan** and
   apply that saved plan in the same job. It does not apply the earlier run's plan.
5. Read the application URL in the output, then follow README section 3 to deploy
   the app, and section 4 to register the QuickBooks callback.

Only authorized operators should run `apply`. This YAML has no environment approval
gate. Configure service connection approvals/checks in Azure DevOps if your team
requires one. Terraform uses blob leases to lock state and waits up to five minutes
for another run's lock. Avoid overlapping apply runs against the same environment.
Do not force-unlock a live run. Plan files stay on the agent, are deleted on exit,
and are never published as pipeline artifacts.

The committed `infra/azure/.terraform.lock.hcl` fixes provider versions and checksums.
The pipeline initializes with `-lockfile=readonly`. For deliberate provider upgrades,
run `terraform init -upgrade` locally, validate, and commit the updated lock file.

## Local init with this backend

After `az login` and selecting the subscription, run from `infra/azure`:

```powershell
terraform init `
  -backend-config="resource_group_name=rg-accounting-tfstate" `
  -backend-config="storage_account_name=YOUR-STORAGE-ACCOUNT" `
  -backend-config="container_name=tfstate" `
  -backend-config="key=accounting-dev.tfstate"
```

Your signed-in identity also needs blob data access. For an existing local state,
add `-migrate-state` and review Terraform's migration prompt. Do not use
`-reconfigure` as a substitute for state migration.

## Validation

The YAML parses successfully, all Bash steps pass syntax checks, and simulated
Azure/Terraform commands verified plan-only behavior, saved-plan apply, cleanup
and rejection of missing secrets. Terraform 1.9.8 formatting and backend-disabled
provider initialization were checked locally. No Azure resources were provisioned
and no authenticated pipeline run has been performed. Provider-schema validation
was attempted but this execution environment blocks the Unix sockets needed by
Terraform plugins (`socket: operation not permitted`); it must complete on the
pipeline agent. HCL syntax parsing passed for all Terraform files.

## References

- https://learn.microsoft.com/en-us/azure/devops/pipelines/tasks/reference/azure-cli-v2
- https://learn.microsoft.com/en-us/azure/devops/pipelines/library/connect-to-azure
- https://developer.hashicorp.com/terraform/language/backend/azurerm
