# Dev, Test and Prod Terraform pipeline

One manual run uses the same commit throughout:

**PlanDev → ApplyDev → PlanTest → ApplyTest → PlanProd → ApplyProd**

Each Apply deployment is controlled by its Azure DevOps Environment's approvals
and checks. Apply consumes the exact saved plan from the corresponding Plan stage;
it does not run Terraform plan again.

| Target | New managed resource group | Azure DevOps Environment | State blob |
| --- | --- | --- | --- |
| Dev | `rg-quickbooks-dev` | `Terraform-Dev-Env` | Existing `stateKey` value, normally `accounting-dev.tfstate` |
| Test | `rg-quickbooks-test` | `Terraform-Test-Env` | `accounting-test.tfstate` |
| Prod | `rg-quickbooks-prod` | `Terraform-Prod-Env` | `accounting-prod.tfstate` |

All blobs use the existing storage account and `tfstate` container, in the
separate **`rg-tfstate-sa`** resource group. Each state manages its own application
group, plan, web app and generated values. App names have distinct
`quickbooks-dev-`, `quickbooks-test-` and `quickbooks-prod-` prefixes.

## 1. Move existing state storage first

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

## 2. Service connection and backend variables

Use the existing workload identity service connection `azure-accounting-wif`.
Because Terraform now creates three resource groups, the identity needs
**Contributor at subscription scope**, plus the blob role on moved state storage.
Authorize this pipeline to use the connection.

Keep the existing `accounting-terraform` Library variable group for shared settings:

| Variable | Value |
| --- | --- |
| `stateResourceGroup` | `rg-tfstate-sa` (also explicitly set in YAML) |
| `stateStorageAccount` | The existing storage account's exact name |
| `stateContainer` | `tfstate` |
| `stateKey` | Preserve the exact existing Dev blob name |

Do not set `stateKey` to a Test/Prod filename. Test/Prod keys are fixed separately
in YAML. Do not copy Dev state into Test or Prod. Terraform creates those state
blobs during their first apply. If an old Dev deployment exists, losing/changing
its key would make Terraform lose track of those existing resources.

## 3. Environment-specific secrets

Create and authorize these three Library variable groups:

- `accounting-terraform-dev`
- `accounting-terraform-test`
- `accounting-terraform-prod`

Each must contain:

| Variable | Secret | Value |
| --- | --- | --- |
| `qboClientId` | Yes | This environment's Intuit client ID |
| `qboClientSecret` | Yes | This environment's Intuit client secret |
| `openaiApiKey` | Yes | This environment's OpenAI key |
| `qboEnvironment` | No | `sandbox` or `production` |

You can initially copy the current test credentials into the Dev/Test groups.
Only use `production` with matching Intuit production credentials. The Prod group
may stay on `sandbox` while validating this application; its name does not force
live QuickBooks access. Avoid adding shared backend keys to these secret groups.

All hosting tiers remain **F1** unless deliberately changed in Terraform.
An environment named Prod is not automatically production-ready hosting. F1
quotas/capacity may limit deploying all three free plans. No paid fallback is
automatic. Application deployment and Intuit callback registration remain separate
per web app; this pipeline provisions infrastructure only.

## 4. Configure all three Environment gates

For each environment listed in the table:

1. Open **Pipelines → Environments → [environment] → Approvals and checks**.
2. Add an **Approval**, choose approvers and timeout, and allow self-approval if
   the requester must approve their own run.
3. Authorize this pipeline under the environment's pipeline permissions.
4. Review that environment's Plan logs before approving Apply.

The environments alone do not cause a pause. Without checks, their Apply stages
start automatically. The YAML has no ManualValidation task or approval stage.

## 5. Run and review

Use `/azure-pipelines-terraform.yml` from `feature/annual-tax-return` in GitHub.
Start one run. Review PlanDev and approve ApplyDev on `Terraform-Dev-Env`;
then review/approve Test and Prod on their own Environments. A rejected/failed
deployment stops downstream environments. Environment checks run before the
deployment job starts; no agent is occupied during the approval wait.

The previous resource group address `azurerm_resource_group.app` is retained in a
`removed` block with `destroy = false`. The new managed group uses a different
address, `azurerm_resource_group.environment`. This avoids Terraform deleting the
old group when switching configuration. Existing Dev web app/plan resources may
still require **replacement** to enter the new group and naming scheme. Back up
any app data and review the destructive actions before approving. This change
does not perform an in-place Azure move of application resources.

Artifacts are named `terraform-plan-dev`, `terraform-plan-test` and
`terraform-plan-prod`. Each contains a secret-bearing binary plan plus a
non-secret checksum/context manifest. Restrict run/artifact access and retention.
Local copies are cleaned after each job; published artifacts remain for the run's
retention period. Apply verifies the run, commit, identity, subscription, backend,
environment, resource group, app prefix and plan checksum. State is never
published. If state changes during approval, start a new run instead of forcing
a stale plan through.

## Validation and limitations

YAML/template expansion, environment gate bindings, stage order, state/artifact
isolation, shell/Python syntax and simulated saved-plan execution are checked
locally. The new multi-environment workflow and storage move still require
execution/verification in your Azure account. No cloud resources were changed
while writing this configuration.

## References

- https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/frequently-asked-questions
- https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/move-resource-group-and-subscription
- https://learn.microsoft.com/en-us/azure/devops/pipelines/process/environments
- https://developer.hashicorp.com/terraform/language/backend/azurerm
