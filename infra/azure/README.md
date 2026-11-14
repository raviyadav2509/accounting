# Azure hosting for QuickBooks Accounting

Terraform creates a separate resource group, Linux App Service plan and Python
3.12 web app for **Dev, Test and Prod**. Each environment uses independent state
in the existing `tfstate` container. State storage is outside application
Terraform and is expected in **`rg-tfstate-sa`**.

| Environment | Resource group | App name prefix |
| --- | --- | --- |
| Dev | `rg-quickbooks-dev` | `quickbooks-dev-` |
| Test | `rg-quickbooks-test` | `quickbooks-test-` |
| Prod | `rg-quickbooks-prod` | `quickbooks-prod-` |

## Pipeline setup

Follow [PIPELINE.md](PIPELINE.md) for the storage-account move, variable groups and
Environment approvals. One run progresses through Plan/Apply for Dev, Test and
Prod, with each Apply using its own exact saved plan and Environment gate.

Azure resource groups cannot be renamed. Move the existing state storage account
from `rg-quickbooks-accounting` into a newly created `rg-tfstate-sa` group first.
Keep its name, container and existing Dev blob name unchanged. Recheck blob data
permissions at the new scope. Do not create an empty replacement state account.

The previous managed resource group is forgotten without deletion through a
`removed` block. Existing Dev app/plan resources may still be replaced to enter
the new group. Review PlanDev before approval and preserve any SQLite data first.
Old groups are left for manual inspection; this configuration does not delete them.

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
`-reconfigure` to init. For local Test/Prod runs, set matching
`deployment_environment`, `resource_group_name` and `name_prefix` and use
`accounting-test.tfstate` or `accounting-prod.tfstate` respectively. Never reuse
Dev's backend key for another environment. No real credentials, plans or state
belong in Git; sensitive settings are still stored in state and saved plans.

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

All three environments default to **F1** for testing. B1 is a deliberate paid
choice. F1 has no Always On and regional/subscription quotas may block additional
plans. A Prod environment label does not make this SQLite development deployment
production ready. OpenAI usage and backend blob storage are billed separately.

SQLite is stored at `/home/bas-data/bas_history.db` outside code deployments.
Use one app instance/process/thread and do not enable SQLite WAL on this shared
filesystem. This is not a backup; replacing or deleting the web app loses its
associated data. Migrate to a managed relational database before production use.
Existing application authentication and security limitations still apply.

`terraform destroy` against one environment's state deletes its managed group,
web app and plan. Keep unrelated resources out of those managed application groups.
It does not manage/delete the external `rg-tfstate-sa` account or old groups
removed from state. Back up application data before destructive changes.

Provider-schema validation and live plans run on the Azure pipeline agents.
See [PIPELINE.md](PIPELINE.md) for verification status and migration details.
