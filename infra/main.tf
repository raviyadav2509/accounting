locals {
  web_app_name = "${var.name_prefix}-${random_string.suffix.result}"
  tags = {
    application = "quickbooks-accounting"
    environment = var.deployment_environment
    managed_by  = "terraform"
  }
}

resource "random_string" "suffix" {
  length  = 8
  upper   = false
  special = false
}

resource "random_password" "flask_secret" {
  length  = 64
  special = false
}

# One managed application group per environment. State storage is external.
resource "azurerm_resource_group" "environment" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.tags
}

resource "azurerm_service_plan" "app" {
  name                = "asp-${local.web_app_name}"
  resource_group_name = azurerm_resource_group.environment.name
  location            = azurerm_resource_group.environment.location
  os_type             = "Linux"
  sku_name            = var.sku_name
  worker_count        = 1
  tags                = local.tags
}

resource "azurerm_linux_web_app" "app" {
  name                = local.web_app_name
  resource_group_name = azurerm_resource_group.environment.name
  location            = azurerm_resource_group.environment.location
  service_plan_id     = azurerm_service_plan.app.id
  https_only          = true

  # Deployment uses Azure CLI with Entra authentication, not publishing passwords.
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false

  site_config {
    always_on               = var.sku_name != "F1"
    ftps_state              = "Disabled"
    minimum_tls_version     = "1.2"
    scm_minimum_tls_version = "1.2"
    http2_enabled           = true

    # One process and one request thread for this SQLite development deployment.
    app_command_line = "python -m gunicorn --bind 0.0.0.0:8000 --workers 1 --threads 1 --timeout 180 azure_wsgi:app"

    application_stack {
      python_version = "3.12"
    }
  }

  app_settings = {
    SCM_DO_BUILD_DURING_DEPLOYMENT      = "true"
    ENABLE_ORYX_BUILD                   = "true"
    WEBSITES_ENABLE_APP_SERVICE_STORAGE = "true"
    BAS_DATABASE_FILE                   = "/home/bas-data/bas_history.db"
    FLASK_SECRET_KEY                    = random_password.flask_secret.result
    QBO_CLIENT_ID                       = var.qbo_client_id
    QBO_CLIENT_SECRET                   = var.qbo_client_secret
    QBO_REDIRECT_URI                    = "https://${local.web_app_name}.azurewebsites.net/callback"
    QBO_BASE_URL                        = var.qbo_environment == "sandbox" ? "https://sandbox-quickbooks.api.intuit.com" : "https://quickbooks.api.intuit.com"
    OPENAI_API_KEY                      = var.openai_api_key
    QBO_WAGE_ACCOUNT_ID                 = var.qbo_wage_account_id
    QBO_PAYG_ACCOUNT_ID                 = var.qbo_payg_account_id
    DEFAULT_BAS_START                   = var.default_bas_start
    DEFAULT_BAS_END                     = var.default_bas_end
  }

  tags = local.tags
}
