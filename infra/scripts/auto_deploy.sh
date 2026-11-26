#!/usr/bin/env bash
set -e

# =============================================================================
# OPTISTACK - DESPLIEGUE INTELIGENTE CON AUTODETECCIÓN DE CUOTA
# =============================================================================

echo "=========================================================="
echo " 🚀 DESPLIEGUE INTELIGENTE DE OPTISTACK EN AZURE"
echo "=========================================================="

RG="rg-optistack"

# Asegurar grupo de recursos
if ! az group show --name "$RG" > /dev/null 2>&1; then
    echo "[1/6] Creando Grupo de Recursos '$RG'..."
    az group create --name "$RG" --location eastus2 -o table
else
    echo "[1/6] Usando Grupo de Recursos existente '$RG'..."
fi

# Detectar región disponible probando planes
echo "[2/6] Buscando región con cuota disponible en tu suscripción..."
REGIONS=("eastus2" "centralus" "westus2" "eastus" "northcentralus")
PLAN_NAME="asp-optistack-plan"
FOUND_REGION=""
CHOSEN_SKU="F1"

# Eliminar plan previo fallido si existiera
az appservice plan delete --name "$PLAN_NAME" --resource-group "$RG" --yes > /dev/null 2>&1 || true

for r in "${REGIONS[@]}"; do
    echo "  -> Probando en '$r' con plan F1 (Gratuito)..."
    if az appservice plan create --name "$PLAN_NAME" --resource-group "$RG" --sku F1 --is-linux --location "$r" -o none 2>/dev/null; then
        FOUND_REGION="$r"
        CHOSEN_SKU="F1"
        echo "  ✅ ¡Cuota aprobada en '$r' (Plan Gratuito F1)!"
        break
    fi

    echo "  -> Probando en '$r' con plan B1..."
    if az appservice plan create --name "$PLAN_NAME" --resource-group "$RG" --sku B1 --is-linux --location "$r" -o none 2>/dev/null; then
        FOUND_REGION="$r"
        CHOSEN_SKU="B1"
        echo "  ✅ ¡Cuota aprobada en '$r' (Plan B1)!"
        break
    fi
done

if [ -z "$FOUND_REGION" ]; then
    echo "⚠️ Probando creación directa en eastus2..."
    FOUND_REGION="eastus2"
    az appservice plan create --name "$PLAN_NAME" --resource-group "$RG" --sku F1 --is-linux --location "$FOUND_REGION" -o table
fi

# Crear Web App
RAND_ID=$((1000 + RANDOM % 9000))
APP_NAME="app-optistack-$RAND_ID"
echo "[3/6] Creando Web App '$APP_NAME' en $FOUND_REGION..."
az webapp create --name "$APP_NAME" --resource-group "$RG" --plan "$PLAN_NAME" --runtime "PYTHON:3.11" -o table

# Configurar WebSockets y Startup Command
echo "[4/6] Configurando WebSockets y parámetros del servidor..."
az webapp config set --name "$APP_NAME" --resource-group "$RG" --web-sockets-enabled true --startup-file "startup.sh" -o none

# Detectar servidor SQL existente
SQL_SERVER=$(az sql server list --resource-group "$RG" --query "[0].fullyQualifiedDomainName" -o tsv 2>/dev/null || echo "")
if [ -n "$SQL_SERVER" ]; then
    echo "  🔗 Vinculando Azure SQL Database: $SQL_SERVER"
    az webapp config appsettings set --name "$APP_NAME" --resource-group "$RG" --settings \
        AZURE_SQL_CONNECTION_STRING="mssql+pyodbc://optiadmin:OptiStack#2026!@$SQL_SERVER:1433/OptiStackDB?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no" \
        SCM_DO_BUILD_DURING_DEPLOYMENT="true" -o none
else
    echo "  ℹ️ No se detectó SQL Server automático en $RG. Podrás ingresar la cadena de conexión luego."
fi

# Desplegar código de la aplicación
echo "[5/6] Empaquetando y subiendo el código de la plataforma..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/../.."
cd "$PROJECT_ROOT"

rm -f /tmp/optistack_app.zip
zip -r /tmp/optistack_app.zip app static requirements.txt startup.sh -x "*.pyc" "*__pycache__*"
az webapp deploy --name "$APP_NAME" --resource-group "$RG" --src-path /tmp/optistack_app.zip --type zip
rm -f /tmp/optistack_app.zip

# Crear Azure IoT Hub
echo "[6/6] Aprovisionando Azure IoT Hub..."
IOT_NAME="iot-optistack-$RAND_ID"
if ! az iot hub create --name "$IOT_NAME" --resource-group "$RG" --location "$FOUND_REGION" --sku F1 --partition-count 2 -o none 2>/dev/null; then
    az iot hub create --name "$IOT_NAME" --resource-group "$RG" --location "$FOUND_REGION" --sku S1 --partition-count 2 -o none 2>/dev/null || true
fi

echo ""
echo "=========================================================="
echo " 🎉 ¡DESPLIEGUE FINALIZADO EXITOSAMENTE!"
echo "=========================================================="
echo " 👉 URL DE TU PLATAFORMA: https://$APP_NAME.azurewebsites.net"
echo " 👉 DOCUMENTACIÓN API:   https://$APP_NAME.azurewebsites.net/docs"
echo "=========================================================="
