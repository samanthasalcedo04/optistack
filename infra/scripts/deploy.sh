#!/usr/bin/env bash
set -e

# =============================================================================
# OPTISTACK - BASH DEPLOYMENT SCRIPT (AZURE CLOUD SHELL / LINUX / MACOS)
# =============================================================================

RESOURCE_GROUP="${1:-rg-optistack-brazil}"
LOCATION="${2:-brazilsouth}"
PREFIX="${3:-optistack}"
ENV_NAME="${4:-prod}"
SQL_USER="${5:-optiadmin}"
SQL_PASS="${6:-OptiStack#2026!SecureKey}"

echo "=========================================================="
echo " 🚀 DESPLIEGUE DE OPTISTACK EN AZURE CLOUD"
echo "=========================================================="

# 1. Comprobar sesión
if ! az account show > /dev/null 2>&1; then
    echo "Autenticándose en Azure..."
    az login
fi

# 2. Crear Grupo de Recursos
echo "[1/5] Creando Resource Group '$RESOURCE_GROUP' en $LOCATION..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" -o table

# 3. Desplegar Bicep
echo "[2/5] Desplegando infraestructura Bicep..."
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_NAME="optistack-deploy-$(date +%s)"

az deployment group create \
    --name "$DEPLOYMENT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$DIR/../bicep/main.bicep" \
    --parameters prefix="$PREFIX" envName="$ENV_NAME" sqlAdminUser="$SQL_USER" sqlAdminPassword="$SQL_PASS" \
    --output none

WEB_APP_URL=$(az deployment group show --name "$DEPLOYMENT_NAME" --resource-group "$RESOURCE_GROUP" --query "properties.outputs.webAppUrl.value" -o tsv)
WEB_APP_NAME=$(az deployment group show --name "$DEPLOYMENT_NAME" --resource-group "$RESOURCE_GROUP" --query "properties.outputs.webAppName.value" -o tsv)
FUNC_APP_NAME=$(az deployment group show --name "$DEPLOYMENT_NAME" --resource-group "$RESOURCE_GROUP" --query "properties.outputs.functionAppName.value" -o tsv)
SQL_CONN_STR=$(az deployment group show --name "$DEPLOYMENT_NAME" --resource-group "$RESOURCE_GROUP" --query "properties.outputs.sqlConnectionString.value" -o tsv)

echo "✅ Infraestructura creada:"
echo "   - WebApp: $WEB_APP_NAME ($WEB_APP_URL)"
echo "   - Functions: $FUNC_APP_NAME"

# 4. Desplegar WebApp
echo "[3/5] Desplegando WebApp..."
PROJECT_ROOT="$DIR/../.."
cd "$PROJECT_ROOT"
zip -r /tmp/optistack_app.zip app static requirements.txt startup.sh
az webapp deploy --resource-group "$RESOURCE_GROUP" --name "$WEB_APP_NAME" --src-path /tmp/optistack_app.zip --type zip
rm -f /tmp/optistack_app.zip

# 5. Desplegar Function
echo "[4/5] Desplegando Azure Function..."
cd "$PROJECT_ROOT/azure_function"
zip -r /tmp/optistack_func.zip .
az functionapp deployment source config-zip --resource-group "$RESOURCE_GROUP" --name "$FUNC_APP_NAME" --src /tmp/optistack_func.zip
rm -f /tmp/optistack_func.zip

echo "=========================================================="
echo " 🎉 ¡DESPLIEGUE FINALIZADO!"
echo " URL: $WEB_APP_URL"
echo "=========================================================="
