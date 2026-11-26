// =============================================================================
// OPTISTACK - MAIN BICEP DEPLOYMENT TEMPLATE
// Despliegue de Arquitectura Azure Cloud para OptiStack HMI 3D
// =============================================================================

@description('Prefijo para nombrar los recursos de OptiStack')
@minLength(3)
@maxLength(12)
param prefix string = 'optistack'

@description('Ambiente de despliegue')
@allowed(['dev', 'qa', 'prod'])
param envName string = 'prod'

@description('Región de Azure para los recursos')
param location string = resourceGroup().location

@description('Usuario administrador para Azure SQL Server')
param sqlAdminUser string = 'optiadmin'

@description('Contraseña para Azure SQL Server (debe cumplir políticas de complejidad)')
@secure()
param sqlAdminPassword string

// Generar sufijo único basado en el ID del Resource Group
var uniqueSuffix = substring(uniqueString(resourceGroup().id), 0, 6)
var baseName = '${prefix}-${envName}-${uniqueSuffix}'

// -----------------------------------------------------------------------------
// 1. Storage Account (Requerido por Azure Functions y backups)
// -----------------------------------------------------------------------------
var rawStorage = 'st${uniqueSuffix}${replace(baseName, '-', '')}'
var storageAccountName = take('${rawStorage}00000', 24)
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: toLower(storageAccountName)
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    accessTier: 'Hot'
  }
}

// -----------------------------------------------------------------------------
// 2. Azure IoT Hub (Recepción de telemetría MQTT desde Raspberry Pi / ESP32)
// -----------------------------------------------------------------------------
var iotHubName = 'iot-${baseName}'
resource iotHub 'Microsoft.Devices/IotHubs@2023-06-30' = {
  name: iotHubName
  location: location
  sku: {
    name: 'S1' // S1 para producción; cambiar a F1 (Free) si está disponible en la suscripción
    capacity: 1
  }
  properties: {
    eventHubEndpoints: {
      events: {
        retentionTimeInDays: 1
        partitionCount: 2
      }
    }
  }
}

// Consumer Group específico para la Azure Function
resource iotHubConsumerGroup 'Microsoft.Devices/IotHubs/eventHubEndpoints/ConsumerGroups@2023-06-30' = {
  name: '${iotHub.name}/events/cg-azure-function'
  properties: {
    name: 'cg-azure-function'
  }
}

// -----------------------------------------------------------------------------
// 3. Azure SQL Database (Tablas maestras, mapas de estiba y telemetría de paquetes)
// -----------------------------------------------------------------------------
var sqlServerName = 'sql-${baseName}'
resource sqlServer 'Microsoft.Sql/servers@2022-05-01-preview' = {
  name: sqlServerName
  location: location
  properties: {
    administratorLogin: sqlAdminUser
    administratorLoginPassword: sqlAdminPassword
    version: '12.0'
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }
}

// Regla de firewall: Permitir servicios internos de Azure (App Service, Functions)
resource sqlFirewallAzure 'Microsoft.Sql/servers/firewallRules@2022-05-01-preview' = {
  parent: sqlServer
  name: 'AllowAllWindowsAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// Regla de firewall para permitir todas las IPs si se desea acceso temporal de desarrollo
resource sqlFirewallDev 'Microsoft.Sql/servers/firewallRules@2022-05-01-preview' = {
  parent: sqlServer
  name: 'AllowAllForInitialSetup'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '255.255.255.255'
  }
}

var sqlDatabaseName = 'OptiStackDB'
resource sqlDatabase 'Microsoft.Sql/servers/databases@2022-05-01-preview' = {
  parent: sqlServer
  name: sqlDatabaseName
  location: location
  sku: {
    name: 'Basic' // Nivel económico para desarrollo/pruebas. Para producción usar 'GP_S_Gen5_1' (Serverless)
    tier: 'Basic'
    capacity: 5
  }
  properties: {
    collation: 'SQL_Latin1_General_CP1_CI_AS'
    maxSizeBytes: 2147483648 // 2 GB
  }
}

// Cadena de conexión SQLAlchemy para la base de datos
var sqlConnectionString = 'mssql+pyodbc://${sqlAdminUser}:${sqlAdminPassword}@${sqlServer.properties.fullyQualifiedDomainName}:1433/${sqlDatabaseName}?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no'

// -----------------------------------------------------------------------------
// 4. App Service Plan & Web App (FastAPI Backend + Three.js 3D HMI Dashboard)
// -----------------------------------------------------------------------------
var appServicePlanName = 'asp-${baseName}'
resource appServicePlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: appServicePlanName
  location: location
  kind: 'linux'
  sku: {
    name: 'B1' // B1 (Basic Linux) soporta WebSockets para actualización 3D en tiempo real
    tier: 'Basic'
  }
  properties: {
    reserved: true // Requerido para Linux
  }
}

var webAppName = 'app-${baseName}'
resource webApp 'Microsoft.Web/sites@2023-01-01' = {
  name: webAppName
  location: location
  properties: {
    serverFarmId: appServicePlan.id
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appCommandLine: 'startup.sh'
      webSocketsEnabled: true // CRÍTICO para los WebSockets del visor 3D
      alwaysOn: true
      appSettings: [
        {
          name: 'APP_TITLE'
          value: 'OptiStack HMI 3D Dashboard - Azure Cloud'
        }
        {
          name: 'AZURE_SQL_CONNECTION_STRING'
          value: sqlConnectionString
        }
        {
          name: 'AZURE_IOT_HUB_NAME'
          value: iotHub.properties.hostName
        }
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
      ]
    }
  }
}

// -----------------------------------------------------------------------------
// 5. Azure Functions Plan & Function App (IoT Hub Ingestion & 3D Solver)
// -----------------------------------------------------------------------------
var functionPlanName = 'asp-func-${baseName}'
resource functionPlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: functionPlanName
  location: location
  kind: 'functionapp,linux'
  sku: {
    name: 'Y1' // Consumption Serverless (Pago por ejecución)
    tier: 'Dynamic'
  }
  properties: {
    reserved: true
  }
}

// Obtener la clave de acceso de IoT Hub para la Function
var iotHubKeys = iotHub.listKeys().value
var iotHubOwnerKey = filter(iotHubKeys, k => k.keyName == 'iothubowner')[0].primaryKey
var iotHubCompatibleEndpoint = iotHub.properties.eventHubEndpoints.events.endpoint
var iotHubCompatiblePath = iotHub.properties.eventHubEndpoints.events.path
var iotHubEventHubConnectionString = 'Endpoint=${iotHubCompatibleEndpoint};SharedAccessKeyName=iothubowner;SharedAccessKey=${iotHubOwnerKey};EntityPath=${iotHubCompatiblePath}'

var functionAppName = 'func-${baseName}'
resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  properties: {
    serverFarmId: functionPlan.id
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=${az.environment().suffixes.storage}'
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'IoTHubConnectionString'
          value: iotHubEventHubConnectionString
        }
        {
          name: 'AZURE_SQL_CONNECTION_STRING'
          value: sqlConnectionString
        }
        {
          name: 'OPTISTACK_WEBAPP_URL'
          value: 'https://${webApp.properties.defaultHostName}'
        }
      ]
    }
  }
}

// -----------------------------------------------------------------------------
// SALIDAS (Outputs para los scripts de despliegue)
// -----------------------------------------------------------------------------
output webAppUrl string = 'https://${webApp.properties.defaultHostName}'
output webAppName string = webApp.name
output functionAppName string = functionApp.name
output iotHubHostName string = iotHub.properties.hostName
output sqlServerFqdn string = sqlServer.properties.fullyQualifiedDomainName
output sqlDatabaseName string = sqlDatabase.name
output sqlConnectionString string = sqlConnectionString
