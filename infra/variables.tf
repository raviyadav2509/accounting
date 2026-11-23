variable "deployment_environment" {
  description = "Application environment; each environment must use its own backend state key."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "test", "prod"], var.deployment_environment)
    error_message = "Choose dev, test or prod."
  }
}

variable "location" {
  description = "Azure region for the environment's resource group and App Service resources."
  type        = string
  default     = "australiaeast"
}

variable "subscription_id" {
  description = "Azure subscription ID. Authenticate using az login before running Terraform."
  type        = string
}

variable "resource_group_name" {
  description = "Application resource group created for this environment. Keep state storage in a separate group."
  type        = string
  default     = "rg-quickbooks-dev"

  validation {
    condition     = length(trimspace(var.resource_group_name)) > 0
    error_message = "Supply the application resource group name."
  }
}

variable "name_prefix" {
  description = "Short lowercase name; a random suffix makes the web app name globally unique."
  type        = string
  default     = "quickbooks-dev"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,29}$", var.name_prefix)) && !endswith(var.name_prefix, "-")
    error_message = "Use 3-30 lowercase letters, digits or hyphens; start with a letter and do not end with a hyphen."
  }
}

variable "sku_name" {
  description = "F1 is free development hosting. B1 is paid and enables Always On."
  type        = string
  default     = "B1"

  validation {
    condition     = contains(["F1", "B1"], var.sku_name)
    error_message = "Choose F1 (free) or B1 (paid)."
  }
}

variable "qbo_client_id" {
  description = "Intuit app client ID, supplied via TF_VAR_qbo_client_id."
  type        = string
  sensitive   = true
  validation {
    condition     = length(trimspace(var.qbo_client_id)) > 0
    error_message = "Supply your Intuit client ID."
  }
}

variable "qbo_client_secret" {
  description = "Intuit app client secret. This value is stored in Terraform state."
  type        = string
  sensitive   = true
  validation {
    condition     = length(trimspace(var.qbo_client_secret)) > 0
    error_message = "Supply your Intuit client secret."
  }
}

variable "openai_api_key" {
  description = "OpenAI API key for AI reviews. This value is stored in Terraform state."
  type        = string
  sensitive   = true
  validation {
    condition     = length(trimspace(var.openai_api_key)) > 0
    error_message = "Supply your OpenAI API key."
  }
}

variable "qbo_environment" {
  description = "Use sandbox for development; production requires matching Intuit production credentials."
  type        = string
  default     = "sandbox"
  validation {
    condition     = contains(["sandbox", "production"], var.qbo_environment)
    error_message = "Choose sandbox or production."
  }
}

variable "qbo_wage_account_id" {
  description = "Existing application's sandbox wage-account mapping; replace for your QBO company."
  type        = string
  default     = "66"
}

variable "qbo_payg_account_id" {
  description = "Existing application's sandbox PAYG-account mapping; replace for your QBO company."
  type        = string
  default     = "49"
}

variable "default_bas_start" {
  description = "Existing app uses fixed default periods; set an appropriate period before testing."
  type        = string
  default     = "2026-09-03"
}

variable "default_bas_end" {
  type    = string
  default = "2026-09-30"
}

variable "ENABLE_MOCK_ATO_LODGEMENT" {
  description = "Enable simulated ATO lodgement for development."
  type        = string
  default     = "true"

  validation {
    condition     = contains(["true", "false"], var.ENABLE_MOCK_ATO_LODGEMENT)
    error_message = "Set ENABLE_MOCK_ATO_LODGEMENT to true or false."
  }
}

variable "EMAIL_VERIFICATION_DEBUG_LINKS" {
  description = "Show email verification links for development; do not enable on a public app."
  type        = string
  default     = "true"

  validation {
    condition     = contains(["true", "false"], var.EMAIL_VERIFICATION_DEBUG_LINKS)
    error_message = "Set EMAIL_VERIFICATION_DEBUG_LINKS to true or false."
  }
}

variable "PASSWORD_RESET_DEBUG_LINKS" {
  description = "Show password reset links for development; do not enable on a public app."
  type        = string
  default     = "true"

  validation {
    condition     = contains(["true", "false"], var.PASSWORD_RESET_DEBUG_LINKS)
    error_message = "Set PASSWORD_RESET_DEBUG_LINKS to true or false."
  }
}
