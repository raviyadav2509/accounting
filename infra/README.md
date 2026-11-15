# Azure hosting for QuickBooks Accounting

Terraform creates a resource group, Linux App Service plan and Python
3.12 web app for **Dev only**, using the existing Dev state blob
in the `tfstate` container. State storage is outside application
Terraform and is expected in **`rg-tfstate-sa`**.

| Environment | Resource group | App name prefix |
| --- | --- | --- |
| Dev | `rg-quickbooks-dev` | `quickbooks-dev-` |

## Pipeline setup

See [Terraform pipeline setup and operations](#terraform-pipeline-setup-and-operations)
for the storage-account move, variable groups and Environment approval. One run executes **PlanDev → ApplyDev**. Apply uses the
exact saved plan, is controlled by checks on **`Terraform-Dev-Env`**, and only runs
from `main`; other branches stop after PlanDev.

Azure resource groups cannot be renamed. Move the existing state storage account
from `rg-quickbooks-accounting` into a newly created `rg-tfstate-sa` group first.
Keep its name, container and existing Dev blob name unchanged. Recheck blob data
permissions at the new scope. Do not create an empty replacement state account.

The previous managed resource group (`azurerm_resource_group.app`) is destroyed
when the plan is applied. Existing Dev app/plan resources are replaced in the new
group. Review PlanDev before approval and preserve any SQLite data first. Deletion
fails if the old group still contains resources Terraform does not manage.

## Local Terraform

Use Terraform 1.7 or newer (below 2.0), Azure CLI and Python 3.12. From
`infra`, authenticate with `az login`, select the correct subscription,
copy `terraform.tfvars.example` to ignored `terraform.tfvars`, and edit the ID.
Supply QBO/OpenAI credentials through session `TF_VAR_*` environment variables.

Initialize the backend using the existing Dev blob name:

```powershell
terraform init `
  -backend-config="resource_group_name=rg-tfstate-sa" `
  -backend-config="storage_account_name=YOUR-EXISTING-STORAGE-ACCOUNT" `
  -backend-config="container_name=tfstate" `
  -backend-config="key=YOUR-EXISTING-DEV-STATE-KEY"
terraform fmt -check
terraform validate
terraform plan -out=deployment.tfplan
terraform apply deployment.tfplan
```

For an initialized local checkout after moving the same storage account, add
`-reconfigure` to init. Keep `deployment_environment = "dev"` and the original
Dev backend key. No real credentials, plans or state belong in Git; sensitive
settings are still stored in state and saved plans.

## Deploy application code after infrastructure

Terraform provisions infrastructure only. The application pipeline
`Pipelines/azure-pipelines.yml` deploys the tested ZIP after CI succeeds on
`main`. Authorize its `azure-accounting-wif` service connection with deployment
permissions on `rg-quickbooks-dev`. The pipeline locates the single app with the
Terraform Dev tags and `quickbooks-dev-` prefix; it fails rather than guessing if
none or multiple match. Feature and pull-request runs only test and package.
There is no separate application-deployment approval gate.

For manual deployment, use a checkout initialized with the target environment's
backend and variables. The packager at `Pipelines/utility/package_app.py` excludes
credentials, databases and Git metadata, adds Gunicorn if absent, and includes
the App Service entry point `Pipelines/utility/azure_wsgi.py` at the deployment
ZIP root.

```powershell
py ..\Pipelines\utility\package_app.py --source .. --output app-deploy.zip
$resourceGroup = terraform output -raw resource_group_name
$webApp = terraform output -raw web_app_name
az webapp deploy --resource-group $resourceGroup --name $webApp --src-path app-deploy.zip --type zip
terraform output -raw application_url
terraform output -raw quickbooks_redirect_uri
```

Register that environment's exact HTTPS `/callback` URL in Intuit before testing
OAuth. Check account mappings and BAS period defaults against the intended company.

## Hosting and data

Dev defaults to **F1** for testing. B1 is a deliberate paid choice.
F1 has no Always On and regional/subscription quotas may block deployment.
This SQLite development deployment is not production ready. OpenAI usage and backend blob storage are billed separately.

SQLite is stored at `/home/bas-data/bas_history.db` outside code deployments.
Use one app instance/process/thread and do not enable SQLite WAL on this shared
filesystem. This is not a backup; replacing or deleting the web app loses its
associated data. Migrate to a managed relational database before production use.
Existing application authentication and security limitations still apply.

`terraform destroy` against one environment's state deletes its managed group,
web app and plan. Keep unrelated resources out of those managed application groups.
It does not manage/delete the external `rg-tfstate-sa` account. Back up application data before destructive changes.

Provider-schema validation and live plans run on the Azure pipeline agents.
See the [validation status](#validation-and-limitations) below.

## Terraform pipeline setup and operations

The Terraform and application deployment steps use PowerShell Core (`pwsh`).
The plan-context and plan-summary helpers remain Python scripts.

One manual run uses the same commit throughout:

**PlanDev → ApplyDev**

Apply is controlled by approvals and checks on **`Terraform-Dev-Env`**. It
consumes the exact saved plan from PlanDev; it does not run Terraform plan again.

ApplyDev runs only when the pipeline is run from `main`. Runs from any other
branch stop after PlanDev, so feature branches can be planned and reviewed but
never deployed. `run-terraform.ps1` also refuses to apply outside `main`. Because
a branch could edit both, add a **Branch control** check (allowed branches
`refs/heads/main`) on `Terraform-Dev-Env` to enforce this in Azure DevOps itself.

| Target | New managed resource group | Azure DevOps Environment | State blob |
| --- | --- | --- | --- |
| Dev | `rg-quickbooks-dev` | `Terraform-Dev-Env` | Existing `stateKey` value, normally `accounting-dev.tfstate` |

The Dev blob uses the existing storage account and `tfstate` container in the
separate **`rg-tfstate-sa`** resource group. Its state manages the Dev application
group, plan, web app and generated values. App names use the `quickbooks-dev-`
prefix. There are no Test/Prod stages or dependencies.

### 1. Move existing state storage first

Azure resource groups cannot be renamed. To change `rg-quickbooks-accounting`
to `rg-tfstate-sa` for storage, **move the existing storage account**, rather than
creating a replacement storage account or empty state files.

1. Finish/cancel all Terraform runs, including any pending approvals. Do not move
   storage while Terraform is running or a state blob is leased by a live run.
2. Record the current storage account name, container, exact Dev `stateKey`,
   and storage role assignments. Download a secure backup of the existing state
   blob if it exists. Do not commit or share state; it contains secrets.
3. In Azure Portal, create **`rg-tfstate-sa`** in the same QuickBooks subscription.
4. Open the existing storage account's **Overview → Move → Move to another
   resource group**. Choose `rg-tfstate-sa`, validate and complete the move.
   Move only the storage account and any dependencies Azure requires.
5. Confirm the same account still contains `tfstate` and the original Dev blob.
   The account name, blob names and content must remain unchanged.
6. Reassign/check **Storage Blob Data Contributor** for your user and the
   `azure-accounting-wif` service principal on the storage account's new scope.
   Resource-level role assignments do not move automatically; permissions inherited
   from the old group also no longer cover the account.
7. Give the pipeline identity **Reader** or broader access on the moved storage
   account for the pipeline's account/group preflight check. Its existing
   subscription-level Contributor role already satisfies this.
8. Update `stateResourceGroup` in the existing `accounting-terraform` variable group
   to `rg-tfstate-sa`. The pipeline YAML explicitly sets that value too.

Do not delete `rg-quickbooks-accounting` or the previous randomly named group
until all their contents have been checked. This pipeline does not delete or
rename those groups. It does not provision or move the backend storage account.

CI initializes from a clean checkout, using the new resource group and the same
account/container/blob: the Dev state stays at the same blob endpoint, so it does
not need to be copied to a new key. For an already initialized local checkout,
use `terraform init -reconfigure` with the updated group **only when the same
account/container/key has been retained**. Changing storage accounts or Dev keys
requires a separate deliberate state migration.

### 2. Service connection and backend variables

Use the existing workload identity service connection `azure-accounting-wif`.
Because Terraform creates the Dev resource group, the identity needs
**Contributor at subscription scope**, plus the blob role on moved state storage.
Authorize this pipeline to use the connection.

Keep the existing `accounting-terraform` Library variable group for shared settings:

| Variable | Value |
| --- | --- |
| `stateResourceGroup` | `rg-tfstate-sa` (also explicitly set in YAML) |
| `stateStorageAccount` | The existing storage account's exact name |
| `stateContainer` | `tfstate` |
| `stateKey` | Preserve the exact existing Dev blob name |

Preserve `stateKey` exactly. If an old Dev deployment exists, losing/changing its
key would make Terraform lose track of those existing resources.

### 3. Dev secrets

Keep Dev secrets in the existing **`accounting-terraform`** Library variable group
alongside the shared backend settings, and authorize this pipeline to use it.
It must also contain:

| Variable | Secret | Value |
| --- | --- | --- |
| `qboClientId` | Yes | This environment's Intuit client ID |
| `qboClientSecret` | Yes | This environment's Intuit client secret |
| `openaiApiKey` | Yes | This environment's OpenAI key |
| `qboEnvironment` | No | `sandbox` or `production` |

Use the current Intuit sandbox credentials and set `qboEnvironment` to `sandbox`
for initial testing. Preserve the existing shared backend values in this group.

Dev hosting remains **F1** unless deliberately changed in Terraform. There is no
automatic paid fallback. Application deployment and Intuit callback registration
remain separate; this pipeline provisions infrastructure only. The application
pipeline deploys on successful `main` runs as described above.

### 4. Configure the Dev Environment gate

1. Open **Pipelines → Environments → Terraform-Dev-Env → Approvals and checks**.
2. Add an **Approval**, choose approvers and timeout, and allow self-approval if
   the requester must approve their own run.
3. Authorize this pipeline under the environment's pipeline permissions.
4. Review that environment's plan summary (see below) before approving Apply.

The environment alone does not cause a pause. Without checks, ApplyDev starts
automatically. The YAML has no ManualValidation task or approval stage.

### 5. Run and review

Configure the existing Azure DevOps pipeline to use
`/infra/azure-pipelines-terraform.yml`; moving the file does not update the
pipeline definition automatically. Start a run from `main`. Review PlanDev and
approve ApplyDev on `Terraform-Dev-Env`. Other branches run Plan only.

PlanDev ends with a readable **Terraform plan summary** in the step log: a one-line
total (for example `Plan: 1 to destroy, 2 to replace, 1 to create.`), an overview
listing each resource with its Azure name and why it changes, and one collapsible
section per resource showing before -> after values (click to expand). Attributes
that force a replacement are marked. Values Terraform marks sensitive, and
attributes whose names look like secrets, are shown only as `(sensitive)`. The same
summary, as tables, is on the run's summary page (**Extensions** tab). A warning
annotation appears when anything is destroyed or replaced. The raw Terraform plan
is still in the log, collapsed under **Full Terraform plan**.
A rejected approval prevents ApplyDev from deploying. Environment checks run before the
deployment job starts; no agent is occupied during the approval wait.

The previous resource group address `azurerm_resource_group.app` is no longer in
configuration, so Terraform plans to **destroy** that group from existing state.
The new managed group uses a different address, `azurerm_resource_group.environment`.
The azurerm provider refuses to delete a group that still contains resources
Terraform does not manage; move or remove those first. Existing Dev web app/plan resources may
still require **replacement** to enter the new group and naming scheme. Back up
any app data and review the destructive actions before approving. This change
does not perform an in-place Azure move of application resources.

The `terraform-plan-dev` artifact contains a secret-bearing binary plan plus a
non-secret checksum/context manifest. Restrict run/artifact access and retention.
Local copies are cleaned after each job; published artifacts remain for the run's
retention period. Apply verifies the run, commit, identity, subscription, backend,
environment, resource group, app prefix and plan checksum. State is never
published. If state changes during approval, start a new run instead of forcing
a stale plan through.

## Validation and limitations

Validation notes recorded on 14 November 2026 (Sydney date):

- Parsed all four Terraform files and the example variable file using `python-hcl2`.
- Parsed both Python scripts using Python's AST parser.
- Ran the deployment packager against a representative application directory layout.
- Verified the ZIP has root-level application files and the Azure WSGI entry point.
- Verified `.env`, token JSON, SQLite database files and Python bytecode are excluded.
- Verified Gunicorn is added when missing, and an existing Gunicorn requirement is preserved.
- Executed the WSGI wrapper with a stub application to check data-directory creation and secure cookie settings.
- Checked configuration names and the callback route against the GitHub repository.
- Checked App Service attributes against AzureRM provider documentation and Python hosting behavior against Microsoft documentation.

Not performed:

- `terraform fmt -check`, `terraform init`, provider-schema `terraform validate`, or an Azure plan/apply. Terraform was unavailable and downloading its binary timed out. HCL parsing is syntax verification, not provider validation.
- Live application deployment, QuickBooks OAuth, OpenAI calls, Azure quota/capacity checks or a persistence test on Azure.
- Verification of the inaccessible Azure DevOps copy of the application.

Run the commands in [Local Terraform](#local-terraform) in your Azure environment
before deployment. No Azure resources were created during that validation.

### References

- https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/frequently-asked-questions
- https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/move-resource-group-and-subscription
- https://learn.microsoft.com/en-us/azure/devops/pipelines/process/environments
- https://developer.hashicorp.com/terraform/language/backend/azurerm
