# Dev Terraform pipeline

One manual run uses the same commit throughout:

**PlanDev → ApplyDev**

Apply is controlled by approvals and checks on **`Terraform-Dev-Env`**.
It consumes the exact saved plan from PlanDev;
it does not run Terraform plan again.

| Target | New managed resource group | Azure DevOps Environment | State blob |
| --- | --- | --- | --- |
| Dev | `rg-quickbooks-dev` | `Terraform-Dev-Env` | Existing `stateKey` value, normally `accounting-dev.tfstate` |

The Dev blob uses the existing storage account and `tfstate` container in the
separate **`rg-tfstate-sa`** resource group. Its state manages the Dev application
group, plan, web app and generated values. App names use the `quickbooks-dev-`
prefix. There are no Test/Prod stages or dependencies.

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

## 3. Dev secrets

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
remain separate; this pipeline provisions infrastructure only.

## 4. Configure the Dev Environment gate

1. Open **Pipelines → Environments → Terraform-Dev-Env → Approvals and checks**.
2. Add an **Approval**, choose approvers and timeout, and allow self-approval if
   the requester must approve their own run.
3. Authorize this pipeline under the environment's pipeline permissions.
4. Review that environment's plan summary (see below) before approving Apply.

The environment alone does not cause a pause. Without checks, ApplyDev starts
automatically. The YAML has no ManualValidation task or approval stage.

## 5. Run and review

Use `/Pipelines/azure-pipelines-terraform.yml` from `feature/annual-tax-return` in GitHub.
Start one run. Review PlanDev and approve ApplyDev on `Terraform-Dev-Env`.

PlanDev publishes a short **Terraform plan summary** on the run's summary page
(the **Extensions** tab). It lists destroyed, replaced, created and updated
resources, most disruptive first, with the attribute names that changed or forced
a replacement. Values are never shown because the plan contains secrets. A
warning annotation appears when anything is destroyed or replaced. The full plan
is still in the step log, collapsed under **Full Terraform plan**.
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

YAML/template expansion, environment gate bindings, stage order, state/artifact
consistency, shell/Python syntax and simulated saved-plan execution are checked
locally. The Dev-only workflow and storage move still require
execution/verification in your Azure account. No cloud resources were changed
while writing this configuration.

## References

- https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/frequently-asked-questions
- https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/move-resource-group-and-subscription
- https://learn.microsoft.com/en-us/azure/devops/pipelines/process/environments
- https://developer.hashicorp.com/terraform/language/backend/azurerm
