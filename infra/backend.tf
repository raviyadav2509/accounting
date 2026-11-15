terraform {
  # Supply the storage coordinates through terraform init -backend-config.
  backend "azurerm" {
    use_azuread_auth = true
  }
}
