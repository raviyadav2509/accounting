# Azure hosting for QuickBooks Accounting

Terraform provisions one Linux App Service plan and a Python 3.12 web app inside the existing **`rg-quickbooks-accounting`** resource group. It reads the group's location and does not create, import or manage the group itself. Defaults to **F1 (free development tier)**; `sku_name = "B1"` selects a paid plan. No VM, managed database, Key Vault, Application Insights or paid storage account is created.

This package was matched to `raviyadav2509/accounting` on GitHub. The Azure DevOps copy could not be read; if that copy differs, compare its config and entry point before deploying.

## What is included

| File | Purpose |
| --- | --- |
| `versions.tf`, `main.tf`, `variables.tf`, `outputs.tf` | Azure resources, inputs and outputs |
| `terraform.tfvars.example` | Non-secret settings to copy and edit |
| `azure_wsgi.py` | Creates the data directory and enables secure session cookies |
| `package_app.py` | Builds a deployment ZIP from your local application checkout |

The app reads `BAS_DATABASE_FILE`, so the web app uses `/home/bas-data/bas_history.db`. This is outside the deployed application files and persists across ordinary app restarts and code deployments. Existing local data is **not migrated**. Deleting the web app/resource group deletes its associated data. Persistence is not a backup.

## Azure Pipeline

Use [PIPELINE.md](PIPELINE.md) to configure `/azure-pipelines-terraform.yml` for manual Terraform plan/apply runs with an Azure workload identity service connection. Create the remote state backend first; this pipeline provisions infrastructure only.

## Switching an earlier deployment to the existing group

Run the pipeline with **action = plan first**, using the same state storage and
state key as the original deployment. The default `resource_group_name` is now
`rg-quickbooks-accounting`; no additional pipeline variable is required.

The old `azurerm_resource_group.app` address has a `removed` block with
`destroy = false`. On apply Terraform forgets the old group without deleting it.
The existing destination group is a data source, so its unrelated resources are
not adopted into this deployment or deleted by `terraform destroy`.

**This is not an in-place resource move.** Changing the group of an existing
App Service plan/web app can require replacement. Review all replacement/deletion
actions before apply. If the app already contains code or data, back up SQLite
consistently and plan a maintenance window before recreating it; the application's
`/home` storage is not carried into the replacement. For an in-place Azure move,
stop here and plan the Azure resource move plus Terraform state migration separately.

Do not delete the old group until its contents have been checked. The removed
block preserves the group itself; it does not prevent replacement of the managed
web app and plan within it. If nothing was deployed beyond the group, the next
apply can create the app resources directly in the existing group.

For local runs, replace any old `location` entry in `terraform.tfvars` with
`resource_group_name = "rg-quickbooks-accounting"`. The hosting region now follows
the existing group. Keep the backend's `stateResourceGroup` unchanged: it identifies
the group containing state storage, not the application's destination group.

## 1. Prerequisites

Install Terraform 1.7 or newer (below 2.0), Azure CLI, Git and Python 3.12. Use a recent Azure CLI that supports Entra-authenticated App Service ZIP deployment with publishing basic authentication disabled.

You need an Azure subscription and permission to read the existing application resource group and create App Service resources inside it. If required, register `Microsoft.Web` in the subscription's Resource providers page. Terraform's provider registration may require subscription-level permission.

Get your Intuit sandbox client ID/secret and OpenAI API key. Use test data. The existing app still has production gaps including CSRF protection and plaintext OAuth tokens in SQLite.

## 2. Provision resources (Windows PowerShell)

Open PowerShell in the repository's `infra/azure` folder:

```powershell
az login
az account list --output table
az account set --subscription "YOUR-SUBSCRIPTION-ID"
Copy-Item terraform.tfvars.example terraform.tfvars
notepad terraform.tfvars
```

Replace the subscription ID in `terraform.tfvars`. Keep `sku_name = "F1"` for free compute. Supply the credentials through session environment variables without displaying them:

```powershell
function Set-TerraformSecret([string]$Name) {
    $secureValue = Read-Host $Name -AsSecureString
    $plainValue = [System.Net.NetworkCredential]::new("", $secureValue).Password
    [System.Environment]::SetEnvironmentVariable("TF_VAR_$Name", $plainValue, "Process")
}
Set-TerraformSecret "qbo_client_id"
Set-TerraformSecret "qbo_client_secret"
Set-TerraformSecret "openai_api_key"

# Initialize the remote backend using the command in PIPELINE.md first.
terraform fmt -check
terraform validate
terraform plan -out=deployment.tfplan
terraform apply deployment.tfplan
```

Review the plan before apply. If F1 is unavailable due to region capacity or subscription quotas, request the quota or deliberately select an existing group in another supported region. Changing to B1 incurs charges; it is not an automatic fallback. Do not use `terraform init -upgrade` routinely; retain and commit `.terraform.lock.hcl` once generated.

**Secret handling:** `sensitive = true` hides normal Terraform output but does not encrypt state. The QBO/OpenAI credentials and generated Flask signing key are stored in state and the saved plan. Keep `.tfstate`, `.tfplan`, credentials and `.terraform/` out of Git. The configuration requires an Azure Storage backend with Entra authentication and restricted RBAC. Create it and initialize Terraform as described in PIPELINE.md before the first apply. Migrate existing local state before using the pipeline. The included `.gitignore` applies when this folder is committed as a unit.

## 3. Deploy your application code

Terraform provisions infrastructure; it does not deploy the application. Clone your Azure DevOps repository using your normal Git authentication if you have not already done so. Do not embed a PAT in a URL or script. Point `--source` below at that repository's root:

```powershell
py package_app.py --source "../.." --output app-deploy.zip
$resourceGroup = terraform output -raw resource_group_name
$webApp = terraform output -raw web_app_name
az webapp deploy --resource-group $resourceGroup --name $webApp --src-path app-deploy.zip --type zip
terraform output -raw application_url
```

The ZIP contains the app at its root, not inside an extra folder. The packager adds Gunicorn to the deployment requirements and includes `azure_wsgi.py`; it does not change your checkout. `.env`, databases, token files, Terraform files and Git history are excluded. Review the archive before deployment if you have added sensitive files to `static/` or `templates/`.

App Service's Oryx build installs the requirements. Startup uses one Gunicorn worker and one thread to limit SQLite write contention. Initial deployment/build can take a few minutes. The separate Terraform pipeline is described in PIPELINE.md; it does not deploy this application ZIP.

## 4. Configure QuickBooks

```powershell
terraform output -raw quickbooks_redirect_uri
```

Register this exact HTTPS `/callback` URL in your Intuit application's redirect URI list for the selected environment. In Azure Portal, check that the web app's `QBO_REDIRECT_URI` matches this output (Azure normally assigns the `<name>.azurewebsites.net` hostname used in the configuration). If your subscription applies a different hostname policy, update the Terraform redirect setting to the assigned hostname before connecting QuickBooks.

Then open the application URL, sign up, add a test client, connect the corresponding QuickBooks sandbox company, and test its BAS dashboard. `QBO_WAGE_ACCOUNT_ID` and `QBO_PAYG_ACCOUNT_ID` default to the existing sandbox mappings and must be checked against the company. The original fixed BAS date defaults remain configurable; adjust them for your test transactions.

Clear the secret environment variables when finished:

```powershell
Remove-Item Env:TF_VAR_qbo_client_id
Remove-Item Env:TF_VAR_qbo_client_secret
Remove-Item Env:TF_VAR_openai_api_key
```

## Cost and development limits

- F1 has a daily 60 CPU-minute quota, 1 GB storage and no Always On. It is for development/testing; availability and regional quotas vary. Idle starts and quota limits can interrupt requests and OAuth callbacks.
- B1 is paid even when the app is idle. Stopping the web app does not stop plan billing.
- OpenAI usage is billed separately. Check Azure pricing and subscription quotas before apply.
- The app is internet-reachable over HTTPS and relies on its existing login; signup is available. This package does not provide private-network access or restrict signup.
- SQLite on App Service's shared filesystem is a development compromise. Use one app instance, avoid concurrent deployments and do not enable SQLite WAL here. Network filesystem locking/latency can cause issues; migrate to a managed relational database before production or scaling.
- No automatic database backup is configured. For test data you need to retain, stop writes and use SQLite's backup API to make a consistent copy before destructive changes; do not copy a live database file while writes are running.

## Checks performed and remaining

Inputs, setting names and `/callback` were checked against the GitHub source. App Service attributes and persistent `/home` behavior were checked against provider/Microsoft documentation. The packager was checked with a representative app layout and excluded credentials/databases. See `VALIDATION.md` for the validation actually performed in this environment.

Run `terraform init`, `terraform validate` and `terraform plan` in your authenticated Azure environment. No Azure resources have been deployed by creating this package.

## Cleanup

`terraform destroy` deletes the managed hosting plan, web app and its SQLite data, but leaves the existing resource group and other resources alone. Back up anything needed first. It does not delete resources managed outside this Terraform configuration.

## References

- https://learn.microsoft.com/en-us/azure/app-service/configure-language-python
- https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/linux_web_app
- https://azure.microsoft.com/en-us/pricing/details/app-service/linux/

