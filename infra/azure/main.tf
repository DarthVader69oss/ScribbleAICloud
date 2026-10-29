terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

variable "subscription_id" {
  type = string
}
variable "location" {
  type    = string
  default = "centralindia"
}
variable "image_tag" {
  type    = string
  default = "v1"
}
variable "project" {
  type    = string
  default = "scribbleai"
}

resource "random_string" "suffix" {
  length = 6
  special = false
  upper = false
}

resource "azurerm_resource_group" "app" {
  name     = "${var.project}-${random_string.suffix.result}-rg"
  location = var.location
}

resource "azurerm_container_registry" "app" {
  name                = "${replace(var.project, "-", "")}acr${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  sku                 = "Basic"
  admin_enabled       = false
}

resource "azurerm_log_analytics_workspace" "app" {
  name                = "${var.project}-${random_string.suffix.result}-logs"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_app_environment" "app" {
  name                       = "${var.project}-${random_string.suffix.result}-env"
  resource_group_name        = azurerm_resource_group.app.name
  location                   = azurerm_resource_group.app.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.app.id
}

resource "azurerm_user_assigned_identity" "app" {
  name                = "${var.project}-${random_string.suffix.result}-pull"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
}

resource "azurerm_role_assignment" "pull" {
  scope                = azurerm_container_registry.app.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_container_app" "app" {
  name                         = "${var.project}-${random_string.suffix.result}-app"
  resource_group_name          = azurerm_resource_group.app.name
  container_app_environment_id = azurerm_container_app_environment.app.id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.app.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = 1
    max_replicas = 1
    container {
      name   = "scribbleai"
      image  = "${azurerm_container_registry.app.login_server}/scribbleai:${var.image_tag}"
      cpu    = 1.0
      memory = "2Gi"

      env {
        name  = "MODEL_IDS"
        value = "finetuned"
      }
      env {
        name  = "DEFAULT_MODEL"
        value = "finetuned"
      }
      env {
        name  = "AWS_EXECUTION_ENV"
        value = "azure-container-apps"
      }
      env {
        name  = "AWS_REGION"
        value = var.location
      }
      env {
        name  = "GIT_SHA"
        value = var.image_tag
      }
    }
  }

  depends_on = [azurerm_role_assignment.pull]
}

output "resource_group" {
  value = azurerm_resource_group.app.name
}
output "acr_name" {
  value = azurerm_container_registry.app.name
}
output "acr_login_server" {
  value = azurerm_container_registry.app.login_server
}
output "app_name" {
  value = azurerm_container_app.app.name
}
output "demo_url" {
  value = "https://${azurerm_container_app.app.latest_revision_fqdn}"
}
