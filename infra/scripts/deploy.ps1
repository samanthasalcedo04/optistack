<#
.SYNOPSIS
    Script automatizado de despliegue de Infraestructura y Plataforma OptiStack en Microsoft Azure.
.DESCRIPTION
    1. Verifica la sesión activa de Azure CLI (az login).
    2. Crea el Resource Group.
    3. Despliega la plantilla Bicep (IoT Hub, Azure SQL, App Service, Azure Function, Storage).
    4. Inicializa el esquema de Azure SQL Database.
    5. Despliega el código de la WebApp y la Azure Function.
#>

param (
    [string]$ResourceGroupName = "rg-optistack-brazil",
    [string]$Location = "brazilsouth",
    [string]$Prefix = "optistack",
    [string]$Environment = "prod",
    [string]$SqlAdminUser = "optiadmin",
    [string]$SqlAdminPassword = "OptiStack#2026!SecureKey"
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " 🚀 DESPLIEGUE AUTOMATIZADO DE OPTISTACK EN AZURE CLOUD" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Comprobar Azure CLI
Write-Host "`n[1/6] Verificando Azure CLI..." -ForegroundColor Yellow
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Error "Azure CLI no está instalado. Por favor instálalo desde: https://aka.ms/installazurecliwindows"
}

# 2. Comprobar Sesión
$account = az account show --output json 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "Iniciando sesión en Azure... Por favor autentícate en el navegador." -ForegroundColor Yellow
    az login --output none
    $account = az account show --output json | ConvertFrom-Json
}
Write-Host "✅ Autenticado en suscripción: $($account.name) ($($account.id))" -ForegroundColor Green

# 3. Crear Resource Group
Write-Host "`n[2/6] Creando Resource Group '$ResourceGroupName' en $Location..." -ForegroundColor Yellow
az group create --name $ResourceGroupName --location $Location --output table

# 4. Desplegar Bicep
Write-Host "`n[3/6] Desplegando infraestructura en la nube (Bicep)... Esto puede tardar 3-5 minutos." -ForegroundColor Yellow
$bicepPath = Join-Path $PSScriptRoot "..\bicep\main.bicep"

$deploymentJson = az deployment group create `
    --resource-group $ResourceGroupName `
    --template-file $bicepPath `
    --parameters prefix=$Prefix envName=$Environment sqlAdminUser=$SqlAdminUser sqlAdminPassword=$SqlAdminPassword `
    --output json

$deployment = $deploymentJson | ConvertFrom-Json

$webAppUrl = $deployment.properties.outputs.webAppUrl.value
$webAppName = $deployment.properties.outputs.webAppName.value
$functionAppName = $deployment.properties.outputs.functionAppName.value
$iotHubHostName = $deployment.properties.outputs.iotHubHostName.value
$sqlConnStr = $deployment.properties.outputs.sqlConnectionString.value

Write-Host "✅ Infraestructura aprovisionada exitosamente:" -ForegroundColor Green
Write-Host "   - WebApp URL: $webAppUrl" -ForegroundColor Cyan
Write-Host "   - IoT Hub:    $iotHubHostName" -ForegroundColor Cyan
Write-Host "   - Functions:  $functionAppName" -ForegroundColor Cyan

# 5. Inicializar Base de Datos Azure SQL
Write-Host "`n[4/6] Inicializando tablas y datos maestros en Azure SQL..." -ForegroundColor Yellow
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$initScript = Join-Path $PSScriptRoot "init_database.py"

if (Test-Path $pythonExe) {
    & $pythonExe $initScript $sqlConnStr
} else {
    Write-Host "Python .venv no encontrado en la raíz. Ejecuta manualmente: python infra/scripts/init_database.py `"$sqlConnStr`"" -ForegroundColor Yellow
}

# 6. Desplegar código de WebApp
Write-Host "`n[5/6] Desplegando código de la aplicación en Azure App Service ($webAppName)..." -ForegroundColor Yellow
Push-Location $projectRoot
try {
    # Empaquetar y desplegar mediante ZIP deploy
    $zipPath = Join-Path $env:TEMP "optistack_app.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path "app", "static", "requirements.txt", "startup.sh" -DestinationPath $zipPath -Force
    az webapp deploy --resource-group $ResourceGroupName --name $webAppName --src-path $zipPath --type zip
    Remove-Item $zipPath -Force
    Write-Host "✅ WebApp desplegada exitosamente." -ForegroundColor Green
} finally {
    Pop-Location
}

# 7. Desplegar Azure Function
Write-Host "`n[6/6] Desplegando código de la Azure Function ($functionAppName)..." -ForegroundColor Yellow
$funcFolder = Join-Path $projectRoot "azure_function"
Push-Location $funcFolder
try {
    $funcZip = Join-Path $env:TEMP "optistack_func.zip"
    if (Test-Path $funcZip) { Remove-Item $funcZip -Force }
    Compress-Archive -Path * -DestinationPath $funcZip -Force
    az functionapp deployment source config-zip --resource-group $ResourceGroupName --name $functionAppName --src $funcZip
    Remove-Item $funcZip -Force
    Write-Host "✅ Azure Function desplegada exitosamente." -ForegroundColor Green
} finally {
    Pop-Location
}

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " 🎉 ¡DESPLIEGUE FINALIZADO CON ÉXITO!" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "👉 Dashboard HMI 3D:    $webAppUrl" -ForegroundColor Cyan
Write-Host "👉 Swagger API Docs:    $webAppUrl/docs" -ForegroundColor Cyan
Write-Host "👉 IoT Hub Host:        $iotHubHostName" -ForegroundColor Cyan
