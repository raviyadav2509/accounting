$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$resourceGroup = 'rg-quickbooks-dev'
$package = $env:APP_PACKAGE
if ([string]::IsNullOrWhiteSpace($package)) {
    throw 'APP_PACKAGE must point to the application ZIP.'
}
if (-not (Test-Path -LiteralPath $package -PathType Leaf)) {
    throw "Application package does not exist: $package"
}

$query = "[?tags.application=='quickbooks-accounting' && tags.environment=='dev' && tags.managed_by=='terraform' && starts_with(name, 'quickbooks-dev-')].name"
$appOutput = @(& az webapp list --resource-group $resourceGroup --query $query --output tsv)
if ($LASTEXITCODE -ne 0) {
    throw "Azure CLI could not list Web Apps in $resourceGroup (exit code $LASTEXITCODE)."
}

$apps = @($appOutput | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
if ($apps.Count -eq 0) {
    throw "No Terraform-managed Dev Web App found in $resourceGroup."
}
if ($apps.Count -ne 1) {
    throw "Expected exactly one Terraform-managed Dev Web App in $resourceGroup; found $($apps.Count)."
}

$appName = [string]$apps[0]
Write-Host "Deploying the tested package to $appName in $resourceGroup."
& az webapp deploy --resource-group $resourceGroup --name $appName `
    --src-path $package --type zip --output none
if ($LASTEXITCODE -ne 0) {
    throw "Azure CLI deployment failed for $appName (exit code $LASTEXITCODE)."
}
Write-Host "Deployment completed for $appName."
