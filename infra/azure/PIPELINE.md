# Deploy Terraform with Azure Pipelines

Use the repository-root `azure-pipelines-terraform.yml` as a **separate pipeline**.
The existing `azure-pipelines.yml` continues testing the application. This pipeline
provisions infrastructure only; deploy the Python app using the README afterwards.
One manual run executes **Plan → Approval → Apply**, using the F1/sandbox Terraform defaults.

## 1. Create the Azure service connection

In Azure DevOps, open **Project settings → Service connections → New service
connection → Azure Resource Manager**. Select **Workload identity federation**,
your subscription, and name it `azure-accounting-wif`. Authorize this pipeline
to use it. A different name can be selected when running the pipeline.

Terraform uses the existing **`rg-quickbooks-accounting`** group. The identity
needs read access to that group and **Contributor** to deploy its App Service
resources. An existing subscription-level Contributor assignment also covers it.
Register required providers (including `Microsoft.Web`) beforehand if the identity
cannot register providers at subscription scope. Give the identity **Storage Blob Data
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

When upgrading from the earlier configuration that created a group, read
README's **Switching an earlier deployment to the existing group** section first.
Review any app/hosting-plan replacements in the Plan stage before approving Apply. The backend
variables above must continue pointing to the original state storage.

## 4. Create and run the pipeline

1. Open **Pipelines → New pipeline** and select the repository (GitHub or Azure Repos).
2. Choose **Existing Azure Pipelines YAML file**, branch `feature/annual-tax-return`,
   path `/azure-pipelines-terraform.yml`. If using Azure Repos, first sync the commit
   containing this YAML and `infra/azure` from GitHub.
3. Start one run. There is no longer an `action` selector. The **Plan** stage
   installs Terraform, initializes remote state, validates and saves a binary plan.
4. When **Approval** pauses, open the Plan stage logs and review the proposed
   additions, changes, replacements and deletions. Open **Review** on the pending
   manual validation and select **Resume** to approve or **Reject** to stop.
5. After approval, **Apply** downloads the plan artifact from this same run, verifies
   its checksum and run/commit/Azure/backend context, initializes with fresh workload
   identity credentials, and applies that exact file. It never generates a new plan.
6. Read the application URL in the Apply log, then follow README sections 3 and 4
   to deploy the app and configure QuickBooks.

The approval runs in an agentless server job, so no hosted agent stays occupied
while waiting. Approval times out after 24 hours and rejects rather than resuming.
Users with **Queue builds** permission can approve by default; self-approval is
explicitly enabled for this personal project. To limit approval to a particular
team, set the `approvers` input on `ManualValidation@1` to that team's users/group.
No notification email is configured; review the pending approval in Azure DevOps.
For approvals enforced independently of repository YAML, configure an Azure DevOps
Environment/service connection approval check separately.

**Saved-plan access:** Terraform binary plans include secret variable values.
This workflow publishes `deployment.tfplan` and a non-secret checksum/context
manifest as the run's private `terraform-plan` artifact to cross the approval/job
boundary. Do not share/download it casually. Restrict pipeline run/artifact viewing
permissions to trusted operators and set short run/artifact retention. Agent copies
and backend caches are removed after each job; the published artifact remains until
the run is deleted or retention removes it. Rejecting approval does not delete it.
No plaintext plan JSON or Terraform state is published.

Keep the same source commit, Terraform version, identity, subscription and backend
coordinates for both stages. Apply rejects altered artifacts or changed context.
Terraform checks saved-plan state freshness and acquires the backend lock; if the
state has changed during approval, start a new run and review a new plan instead of
forcing an old plan through. Avoid overlapping runs against the same environment.
Do not rerun only Plan after approval: reject/cancel and start a complete new run.

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

YAML stage dependencies, the agentless manual approval timeout/rejection settings
and shell syntax were checked locally. Simulated Terraform/Azure commands exercised
the separate Plan and Apply paths, applying the saved bytes without a second plan,
and rejection of missing/altered plans or changed backend/run/source context.
This staged workflow has not yet been run against Azure DevOps. Terraform provider
validation and the Azure plan run on the pipeline agent.

## References

- https://learn.microsoft.com/en-us/azure/devops/pipelines/tasks/reference/manual-validation-v1
- https://learn.microsoft.com/en-us/azure/devops/pipelines/tasks/reference/download-pipeline-artifact-v2
- https://developer.hashicorp.com/terraform/cli/commands/apply
- https://developer.hashicorp.com/terraform/language/manage-sensitive-data
