# Guía de Despliegue de Infraestructura OptiStack en Microsoft Azure

Esta guía explica paso a paso cómo aprovisionar la arquitectura completa de OptiStack en la nube de Azure de acuerdo con el diagrama de arquitectura:
- **Azure IoT Hub:** Ingesta de telemetría MQTT desde dispositivos (Raspberry Pi / ESP32).
- **Azure Functions (Python):** Procesamiento Serverless con *IoT Hub Trigger*.
- **Azure SQL Database:** Base de datos relacional para camiones, rutas y paquetes.
- **Azure App Service (Linux):** Host de FastAPI y visor 3D HMI en Three.js con WebSockets.
- **Simulador de Sensores IoT:** Emulador de balanza y dimensionador volumétrico.

---

## 📋 Requisitos Previos

1. **Una cuenta activa de Azure:** (Suscripción gratuita o de pago).
2. **Azure CLI instalado en tu computadora:**
   - [Descargar instalador para Windows](https://aka.ms/installazurecliwindows)
   - O bien puedes usar **Azure Cloud Shell** directamente desde el navegador en [https://shell.azure.com](https://shell.azure.com).

---

## 🚀 Método 1: Despliegue Automático con PowerShell (Recomendado)

Si estás en tu terminal de Windows, solo requieres 2 pasos:

### 1. Iniciar sesión en Azure
```powershell
az login
```
*(Se abrirá tu navegador web para que elijas tu cuenta de Microsoft/Azure).*

### 2. Ejecutar el script de despliegue
```powershell
cd C:\Users\admin\Downloads\optistack
.\infra\scripts\deploy.ps1
```

> **Parámetros opcionales:**
> Puedes personalizar el nombre del grupo de recursos, ubicación y contraseña de SQL si lo deseas:
> ```powershell
> .\infra\scripts\deploy.ps1 -ResourceGroupName "rg-optistack-prod" -Location "eastus" -SqlAdminPassword "TuClaveSegura#2026"
> ```

El script realizará de forma automática:
1. Creación del Resource Group.
2. Aprovisionamiento de todos los servicios mediante la plantilla [main.bicep](file:///c:/Users/admin/Downloads/optistack/infra/bicep/main.bicep).
3. Creación de las tablas e índices en Azure SQL Database ejecutando [schema_azure_sql.sql](file:///c:/Users/admin/Downloads/optistack/sql/schema_azure_sql.sql).
4. Empaquetado y publicación del código web en Azure App Service.
5. Empaquetado y publicación de la Azure Function.

---

## 🌐 Método 2: Despliegue desde Azure Cloud Shell (Navegador)

Si no tienes Azure CLI instalado en tu laptop, puedes hacerlo 100% online:

1. Entra a [https://shell.azure.com](https://shell.azure.com) y selecciona **Bash**.
2. Sube los archivos o clona el repositorio.
3. Ejecuta:
   ```bash
   chmod +x infra/scripts/deploy.sh
   ./infra/scripts/deploy.sh rg-optistack-prod eastus
   ```

---

## 💻 Método 3: Despliegue Manual Paso a Paso (Azure Portal)

Si prefieres crear cada recurso visualmente a través del portal de Azure ([portal.azure.com](https://portal.azure.com)):

### 1. Crear el Grupo de Recursos
- Ve a **Resource groups** > **+ Create**.
- Nombre: `rg-optistack-prod`.
- Región: `East US` (o la más cercana).

### 2. Crear Azure SQL Database
- Busca **SQL Database** > **+ Create**.
- Database name: `OptiStackDB`.
- Server: Crea uno nuevo (ej. `sql-optistack-prod`), Authentication: *Use SQL authentication*, Usuario: `optiadmin`, Contraseña segura.
- Compute + Storage: Selecciona **Basic** (5 DTUs, muy económico) o **Serverless (General Purpose)**.
- En **Networking**: Marca *"Allow Azure services and resources to access this server"* en **Yes**.
- Una vez creado, abre el **Query editor** en el portal y pega el contenido del archivo `sql/schema_azure_sql.sql` para crear las tablas.

### 3. Crear Azure IoT Hub
- Busca **IoT Hub** > **+ Create**.
- Nombre: `iot-optistack-prod`.
- Tier: **F1 (Free)** si tienes cupo libre, o **S1 (Standard)**.
- Ve a la pestaña **Hub settings** > **Built-in endpoints** > **Consumer Groups** y agrega uno llamado: `cg-azure-function`.

### 4. Crear Azure App Service (Web App)
- Busca **App Services** > **+ Create**.
- Runtime stack: **Python 3.11**.
- Operating System: **Linux**.
- Pricing plan: **Basic B1** (importante: B1 soporta WebSockets, Free F1 no tiene soporte WebSocket estable).
- En **Configuration** > **General settings**:
  - Web sockets: **On**.
  - Startup Command: `startup.sh`.
- En **Application settings**, añade:
  - `AZURE_SQL_CONNECTION_STRING` = `mssql+pyodbc://optiadmin:TU_PASSWORD@sql-optistack-prod.database.windows.net:1433/OptiStackDB?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no`
  - `AZURE_IOT_HUB_NAME` = `iot-optistack-prod.azure-devices.net`

### 5. Crear Azure Function App
- Busca **Function App** > **+ Create**.
- Runtime stack: **Python 3.11**.
- Hosting: **Consumption (Serverless)**.
- En **Configuration**, añade la cadena de conexión de eventos de IoT Hub con el nombre `IoTHubConnectionString`.

---

## 📡 Cómo probar el envío de telemetría IoT desde Raspberry Pi / ESP32

Una vez desplegada la infraestructura:

1. Registra tu dispositivo en el IoT Hub:
   ```bash
   az iot hub device-identity create --hub-name iot-optistack-prod --device-id RPi-Gate01
   az iot hub device-identity connection-string show --hub-name iot-optistack-prod --device-id RPi-Gate01 --output tsv
   ```
2. Ejecuta el simulador en tu Raspberry Pi (o en tu laptop para probar):
   ```powershell
   $env:IOTHUB_DEVICE_CONNECTION_STRING = "HostName=iot-optistack-prod.azure-devices.net;DeviceId=RPi-Gate01;SharedAccessKey=xxx="
   python devices/iot_device_simulator.py
   ```
3. Verás cómo los paquetes ingresan al IoT Hub, la Azure Function los procesa, calcula la posición 3D, los guarda en Azure SQL y el visualizador 3D en la WebApp se actualiza automáticamente.
