$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-RequiredSetting {
    param([Parameter(Mandatory = $true)][string]$Name)

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value) -or $value -like '$(*') {
        throw "Missing required pipeline setting: $Name"
    }
    return $value
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable exited with code $LASTEXITCODE."
    }
}

try {
    $required = @(
        'servicePrincipalId', 'tenantId', 'idToken', 'TF_ACTION',
        'TF_PLAN_DIRECTORY', 'TF_RUN_ID', 'TF_SOURCE_VERSION',
        'TERRAFORM_VERSION', 'TF_DEPLOYMENT_ENVIRONMENT',
        'TF_VAR_deployment_environment', 'TF_VAR_resource_group_name',
        'TF_VAR_name_prefix', 'TF_STATE_RESOURCE_GROUP',
        'TF_STATE_STORAGE_ACCOUNT', 'TF_STATE_CONTAINER', 'TF_STATE_KEY'
    )

    if ($env:TF_ACTION -eq 'plan') {
        $required += @(
            'TF_VAR_qbo_client_id', 'TF_VAR_qbo_client_secret',
            'TF_VAR_openai_api_key', 'TF_VAR_qbo_environment'
        )
    }
    elseif ($env:TF_ACTION -eq 'apply') {
        $required += 'TF_SOURCE_BRANCH'
    }
    else {
        throw 'TF_ACTION must be plan or apply.'
    }

    foreach ($name in $required) {
        $null = Get-RequiredSetting -Name $name
    }

    if ($env:TF_ACTION -eq 'apply' -and $env:TF_SOURCE_BRANCH -ne 'refs/heads/main') {
        throw "Apply is only allowed from main (this run is from $env:TF_SOURCE_BRANCH)."
    }
    if ($env:TF_DEPLOYMENT_ENVIRONMENT -ne $env:TF_VAR_deployment_environment) {
        throw 'Pipeline and Terraform environment must match.'
    }

    $env:ARM_CLIENT_ID = $env:servicePrincipalId
    $env:ARM_TENANT_ID = $env:tenantId
    $env:ARM_OIDC_TOKEN = $env:idToken
    $env:ARM_USE_OIDC = 'true'
    $env:ARM_USE_AZUREAD = 'true'
    $env:ARM_USE_CLI = 'false'
    $subscriptionId = & az account show --query id --output tsv
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($subscriptionId -join '').Trim())) {
        throw 'Unable to determine the active Azure subscription.'
    }
    $env:ARM_SUBSCRIPTION_ID = ($subscriptionId -join '').Trim()
    $env:TF_VAR_subscription_id = $env:ARM_SUBSCRIPTION_ID

    $planDirectory = $env:TF_PLAN_DIRECTORY
    $planPath = Join-Path $planDirectory 'deployment.tfplan'
    $contextScript = Join-Path $PSScriptRoot 'plan-context.py'
    $summaryScript = Join-Path $PSScriptRoot 'plan-summary.py'

    if ($env:TF_ACTION -eq 'apply') {
        Invoke-CheckedCommand -Executable 'python3' -Arguments @(
            $contextScript, 'verify', $planDirectory
        )
    }

    Invoke-CheckedCommand -Executable 'az' -Arguments @(
        'storage', 'account', 'show',
        '--resource-group', $env:TF_STATE_RESOURCE_GROUP,
        '--name', $env:TF_STATE_STORAGE_ACCOUNT,
        '--query', 'id', '--output', 'tsv'
    )

    Invoke-CheckedCommand -Executable 'terraform' -Arguments @(
        'fmt', '-check', '-recursive'
    )
    Invoke-CheckedCommand -Executable 'terraform' -Arguments @(
        'init', '-input=false', '-lockfile=readonly',
        "-backend-config=resource_group_name=$($env:TF_STATE_RESOURCE_GROUP)",
        "-backend-config=storage_account_name=$($env:TF_STATE_STORAGE_ACCOUNT)",
        "-backend-config=container_name=$($env:TF_STATE_CONTAINER)",
        "-backend-config=key=$($env:TF_STATE_KEY)"
    )
    Invoke-CheckedCommand -Executable 'terraform' -Arguments @(
        'validate', '-no-color'
    )

    if ($env:TF_ACTION -eq 'plan') {
        New-Item -ItemType Directory -Path $planDirectory -Force | Out-Null
        Write-Host '##[group]Full Terraform plan'
        Invoke-CheckedCommand -Executable 'terraform' -Arguments @(
            'plan', '-input=false', '-no-color', '-lock-timeout=5m',
            "-out=$planPath"
        )
        Write-Host '##[endgroup]'
        Invoke-CheckedCommand -Executable 'python3' -Arguments @(
            $contextScript, 'save', $planDirectory
        )

        $summaryDirectory = $env:AGENT_TEMPDIRECTORY
        if ([string]::IsNullOrWhiteSpace($summaryDirectory)) {
            $summaryDirectory = $planDirectory
        }
        New-Item -ItemType Directory -Path $summaryDirectory -Force | Out-Null
        $summaryPath = Join-Path $summaryDirectory (
            "terraform-plan-summary-$($env:TF_DEPLOYMENT_ENVIRONMENT).md"
        )
        $planJsonPath = Join-Path $summaryDirectory (
            "terraform-plan-$($env:TF_RUN_ID).json"
        )

        try {
            Write-Host '##[section]Terraform plan summary'
            & terraform show -json $planPath > $planJsonPath
            if ($LASTEXITCODE -ne 0) {
                throw "terraform show exited with code $LASTEXITCODE."
            }
            Invoke-CheckedCommand -Executable 'python3' -Arguments @(
                $summaryScript, $env:TF_DEPLOYMENT_ENVIRONMENT,
                $summaryPath, $planJsonPath
            )
            Write-Host "##vso[task.uploadsummary]$summaryPath"
        }
        finally {
            if (Test-Path -LiteralPath $planJsonPath) {
                Remove-Item -LiteralPath $planJsonPath -Force
            }
        }

        Write-Host "Plan saved. Apply will use this environment's saved artifact after its Environment checks."
    }
    else {
        Invoke-CheckedCommand -Executable 'terraform' -Arguments @(
            'apply', '-input=false', '-no-color', '-lock-timeout=5m', $planPath
        )
        Invoke-CheckedCommand -Executable 'terraform' -Arguments @(
            'output', '-raw', 'application_url'
        )
    }
}
catch {
    Write-Error $_
    exit 1
}
