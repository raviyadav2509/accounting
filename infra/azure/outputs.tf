output "resource_group_name" {
  value = azurerm_resource_group.app.name
}

output "web_app_name" {
  value = azurerm_linux_web_app.app.name
}

output "application_url" {
  value = "https://${azurerm_linux_web_app.app.default_hostname}"
}

output "quickbooks_redirect_uri" {
  description = "Register this exact URL in the Intuit developer portal."
  value       = "https://${azurerm_linux_web_app.app.default_hostname}/callback"
}
