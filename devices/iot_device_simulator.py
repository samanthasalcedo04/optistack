"""
SIMULADOR DE DISPOSITIVO IOT - RASPBERRY PI / ESP32
Envía telemetría de pesaje y dimensionamiento volumétrico 3D hacia Azure IoT Hub.
"""

import os
import time
import json
import random
from datetime import datetime

# Si la librería azure-iot-device está instalada, se usa el cliente nativo MQTT de Azure
try:
    from azure.iot.device import IoTHubDeviceClient, Message
    HAS_AZURE_IOT = True
except ImportError:
    HAS_AZURE_IOT = False
    import httpx

# Cadena de conexión del dispositivo obtenida desde Azure IoT Hub
# Ejemplo: "HostName=iot-optistack.azure-devices.net;DeviceId=RaspberryPi-Gate01;SharedAccessKey=xxx="
IOTHUB_DEVICE_CONNECTION_STRING = os.getenv("IOTHUB_DEVICE_CONNECTION_STRING", "")

# Fallback HTTP si se prueba directamente contra la API de la plataforma o Azure Function
FALLBACK_API_URL = os.getenv("OPTISTACK_API_URL", "http://localhost:8000/api/stowage/telemetry/package")

AGENCIES = ["AG-TRU-01", "AG-CHI-02", "AG-PIU-03", "AG-CAJ-04"]


def generate_simulated_package(index: int) -> dict:
    """Genera lecturas simuladas de sensores (Balanza + Dimensionador Óptico/Ultrasónico)."""
    return {
        "guide_id": f"GUIA-AUTO-{random.randint(1000, 9999)}",
        "length_cm": round(random.uniform(40.0, 90.0), 1),
        "width_cm": round(random.uniform(30.0, 70.0), 1),
        "height_cm": round(random.uniform(25.0, 60.0), 1),
        "weight_kg": round(random.uniform(5.0, 45.0), 2),
        "agency_id": random.choice(AGENCIES),
        "device_id": "IoT-RPi-Gate01-SensorStation",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


def send_via_mqtt(client, package_data: dict):
    msg_str = json.dumps(package_data)
    message = Message(msg_str)
    message.content_encoding = "utf-8"
    message.content_type = "application/json"
    client.send_message(message)
    print(f"📡 [MQTT -> Azure IoT Hub] Paquete enviado: {package_data['guide_id']} ({package_data['length_cm']}x{package_data['width_cm']}x{package_data['height_cm']} cm, {package_data['weight_kg']} kg)")


def send_via_http(package_data: dict):
    payload = {
        "GuideID": package_data["guide_id"],
        "LengthCm": package_data["length_cm"],
        "WidthCm": package_data["width_cm"],
        "HeightCm": package_data["height_cm"],
        "WeightKg": package_data["weight_kg"],
        "TargetAgencyID": package_data["agency_id"],
        "SourceDevice": package_data["device_id"]
    }
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(FALLBACK_API_URL, json=payload)
        if resp.status_code in (200, 201):
            print(f"🌐 [HTTP Fallback API] Paquete enviado correctamente: {payload['GuideID']}")
        else:
            print(f"⚠️ [HTTP Error {resp.status_code}]: {resp.text}")


def main():
    print("==========================================================")
    print(" 🚛 OptiStack - Simulador de Sensores IoT (Balanza / LiDAR)")
    print("==========================================================")

    client = None
    if HAS_AZURE_IOT and IOTHUB_DEVICE_CONNECTION_STRING:
        print("🔗 Conectando a Azure IoT Hub mediante MQTT...")
        client = IoTHubDeviceClient.create_from_connection_string(IOTHUB_DEVICE_CONNECTION_STRING)
        client.connect()
        print("✅ Conexión establecida con Azure IoT Hub.")
    else:
        print("ℹ️ Modo local/fallback HTTP activo (contra App Service o localhost).")
        print(f"🎯 URL de destino: {FALLBACK_API_URL}")

    count = 1
    try:
        while True:
            pkg = generate_simulated_package(count)
            if client:
                send_via_mqtt(client, pkg)
            else:
                send_via_http(pkg)

            count += 1
            interval = random.randint(4, 8)
            print(f"⏳ Esperando siguiente paquete ({interval}s)...\n")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n🛑 Simulador detenido por el usuario.")
        if client:
            client.shutdown()


if __name__ == "__main__":
    main()
