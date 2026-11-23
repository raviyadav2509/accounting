mock_provider "azurerm" {
  mock_resource "azurerm_service_plan" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-quickbooks-dev/providers/Microsoft.Web/serverFarms/test-plan"
    }
  }

  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-quickbooks-dev/providers/Microsoft.OperationalInsights/workspaces/test-workspace"
    }
  }

  mock_resource "azurerm_application_insights" {
    defaults = {
      instrumentation_key = "test-instrumentation-key"
      connection_string   = "InstrumentationKey=test-instrumentation-key"
    }
  }
}
mock_provider "random" {}

variables {
  subscription_id        = "00000000-0000-0000-0000-000000000000"
  qbo_client_id          = "test"
  qbo_client_secret      = "test"
  openai_api_key         = "test"
  allowed_client_ip_cidr = "192.0.2.10/32"
  db_file_name           = "bas-reset.db"
}

run "restrict_main_site" {
  command = plan

  assert {
    condition     = azurerm_linux_web_app.app.site_config[0].ip_restriction_default_action == "Deny" && one(azurerm_linux_web_app.app.site_config[0].ip_restriction).ip_address == "192.0.2.10/32" && one(azurerm_linux_web_app.app.site_config[0].ip_restriction).action == "Allow"
    error_message = "The main site must deny other addresses and allow the configured address."
  }

  assert {
    condition     = nonsensitive(azurerm_linux_web_app.app.app_settings["BAS_DATABASE_FILE"]) == "/home/bas-data/bas-reset.db"
    error_message = "The current development database path must be preserved."
  }
}

run "use_configured_database_filename" {
  command = plan

  variables {
    db_file_name = "another-test.sqlite"
  }

  assert {
    condition     = nonsensitive(azurerm_linux_web_app.app.app_settings["BAS_DATABASE_FILE"]) == "/home/bas-data/another-test.sqlite"
    error_message = "The application must use the configured database filename."
  }
}

run "use_configured_development_settings" {
  command = plan

  variables {
    MOCK_ATO_LODGEMENT                  = "false"
    MOCK_EMAIL_VERIFICATION_DEBUG_LINKS = "true"
    MOCK_PASSWORD_RESET_DEBUG_LINKS     = "false"
  }

  assert {
    condition     = nonsensitive(azurerm_linux_web_app.app.app_settings["ENABLE_MOCK_ATO_LODGEMENT"]) == "false" && nonsensitive(azurerm_linux_web_app.app.app_settings["EMAIL_VERIFICATION_DEBUG_LINKS"]) == "true" && nonsensitive(azurerm_linux_web_app.app.app_settings["PASSWORD_RESET_DEBUG_LINKS"]) == "false"
    error_message = "App settings must match the configured development flags."
  }
}

run "connect_application_insights" {
  command = apply

  assert {
    condition     = nonsensitive(azurerm_linux_web_app.app.app_settings["APPLICATIONINSIGHTS_CONNECTION_STRING"]) == "InstrumentationKey=test-instrumentation-key" && nonsensitive(azurerm_linux_web_app.app.app_settings["APPINSIGHTS_INSTRUMENTATIONKEY"]) == "test-instrumentation-key" && nonsensitive(azurerm_linux_web_app.app.app_settings["ApplicationInsightsAgent_EXTENSION_VERSION"]) == "~3"
    error_message = "The app must use the managed Application Insights connection and Linux Python agent."
  }

  assert {
    condition     = azurerm_application_insights.app.workspace_id == azurerm_log_analytics_workspace.app.id && azurerm_application_insights.app.resource_group_name == azurerm_resource_group.environment.name && azurerm_log_analytics_workspace.app.resource_group_name == azurerm_resource_group.environment.name
    error_message = "Application Insights must use the managed workspace in the application resource group."
  }

  assert {
    condition     = contains(azurerm_linux_web_app.app.sticky_settings[0].app_setting_names, "APPLICATIONINSIGHTS_CONNECTION_STRING") && contains(azurerm_linux_web_app.app.sticky_settings[0].app_setting_names, "ApplicationInsightsAgent_EXTENSION_VERSION") && contains(azurerm_linux_web_app.app.sticky_settings[0].app_setting_names, "APPLICATIONINSIGHTS_CONNECTION_STRING ")
    error_message = "The monitoring settings and existing sticky names must remain slot-specific."
  }
}

run "reject_invalid_development_setting" {
  command = plan

  variables {
    MOCK_EMAIL_VERIFICATION_DEBUG_LINKS = "yes"
  }

  expect_failures = [var.MOCK_EMAIL_VERIFICATION_DEBUG_LINKS]
}

run "reject_database_path" {
  command = plan

  variables {
    db_file_name = "../outside.db"
  }

  expect_failures = [var.db_file_name]
}

run "reject_empty_database_filename" {
  command = plan

  variables {
    db_file_name = ""
  }

  expect_failures = [var.db_file_name]
}

run "reject_broad_network" {
  command = plan

  variables {
    allowed_client_ip_cidr = "0.0.0.0/0"
  }

  expect_failures = [var.allowed_client_ip_cidr]
}

run "reject_invalid_address" {
  command = plan

  variables {
    allowed_client_ip_cidr = "999.1.1.1/32"
  }

  expect_failures = [var.allowed_client_ip_cidr]
}

run "reject_ipv6" {
  command = plan

  variables {
    allowed_client_ip_cidr = "2001:db8::1/32"
  }

  expect_failures = [var.allowed_client_ip_cidr]
}
