variable "subscription_id" {
  description = "Azure subscription ID. Authenticate using az login before running Terraform."
  type        = string
}

variable "location" {
  description = "Azure region; free Linux capacity is subscription- and region-dependent."
  type        = string
  default     = "australiaeast"
}

variable "name_prefix" {
  description = "Short lowercase name; a random suffix makes the web app name globally unique."
  type        = string
  default     = "ravi-accounting"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,29}$", var.name_prefix)) && !endswith(var.name_prefix, "-")
    error_message = "Use 3-30 lowercase letters, digits or hyphens; start with a letter and do not end with a hyphen."
  }
}

variable "sku_name" {
  description = "F1 is free development hosting. B1 is paid and enables Always On."
  type        = string
  default     = "F1"

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
