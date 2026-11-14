# Azure hosting for QuickBooks Accounting

Terraform creates a resource group, Linux App Service plan and Python
3.12 web app for **Dev only**, using the existing Dev state blob
in the `tfstate` container. State storage is outside application
Terraform and is expected in **`rg-tfstate-sa`**.

| Environment | Resource group | App name prefix |
| --- | --- | --- |
| Dev | `rg-quickbooks-dev` | `quickbooks-dev-` |

## Pipeline setup

Follow [PIPELINE.md](PIPELINE.md) for the storage-account move, variable groups and
Environment approval. One run executes **PlanDev → ApplyDev**. Apply uses the
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
`infra/azure`, authenticate with `az login`, select the correct subscription,
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

Terraform provisions infrastructure only. Use a checkout initialized with the
target environment's backend and variables. The packager excludes credentials,
databases and Git metadata, adds Gunicorn if absent, and includes `azure_wsgi.py`.

```powershell
py package_app.py --source "../.." --output app-deploy.zip
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
See [PIPELINE.md](PIPELINE.md) for verification status and migration details.
