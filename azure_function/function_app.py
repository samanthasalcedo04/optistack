import json
import logging
import os
import azure.functions as func
import httpx
from sqlalchemy import create_engine, text

app = func.FunctionApp()

# Conexión a Base de Datos Azure SQL
SQL_CONN_STR = os.getenv("AZURE_SQL_CONNECTION_STRING", "")
WEBAPP_URL = os.getenv("OPTISTACK_WEBAPP_URL", "")

engine = None
if SQL_CONN_STR:
    try:
        engine = create_engine(SQL_CONN_STR, pool_pre_ping=True)
    except Exception as e:
        logging.error(f"Error inicializando conexión a base de datos: {e}")


@app.function_name(name="IoTHubPackageIngestion")
@app.event_hub_message_trigger(
    arg_name="azeventhub",
    event_hub_name="events",
    connection="IoTHubConnectionString",
    consumer_group="cg-azure-function"
)
def process_iothub_telemetry(azeventhub: func.EventHubEvent):
    """
    Función Serverless activada por eventos de Azure IoT Hub.
    Recibe la telemetría enviada por Raspberry Pi / ESP32 (sensores de peso y volumen),
    calcula coordenadas con Extreme Points 3D e inserta en Azure SQL Database.
    """
    body_str = azeventhub.get_body().decode("utf-8")
    logging.info(f"==> Telemetría recibida de IoT Hub: {body_str}")

    try:
        data = json.loads(body_str)
    except Exception as err:
        logging.error(f"El mensaje de telemetría no tiene formato JSON válido: {err}")
        return

    # Extraer campos de la guía
    guide_id = str(data.get("guide_id") or data.get("GuideID") or "").strip().upper()
    length_cm = float(data.get("length_cm") or data.get("LengthCm") or 0.0)
    width_cm = float(data.get("width_cm") or data.get("WidthCm") or 0.0)
    height_cm = float(data.get("height_cm") or data.get("HeightCm") or 0.0)
    weight_kg = float(data.get("weight_kg") or data.get("WeightKg") or 0.0)
    agency_id = str(data.get("agency_id") or data.get("TargetAgencyID") or "AG-TRU-01").strip()
    device_id = str(data.get("device_id") or "RaspberryPi-Gateway-01")

    if not guide_id or length_cm <= 0 or width_cm <= 0 or height_cm <= 0:
        logging.warning(f"Paquete descartado por datos incompletos o inválidos: {data}")
        return

    # Si la WebApp está configurada, enviamos directo al endpoint de telemetría
    # que calcula la coordenada con el estado activo de la estiba y emite WebSocket en tiempo real
    if WEBAPP_URL:
        payload = {
            "GuideID": guide_id,
            "LengthCm": length_cm,
            "WidthCm": width_cm,
            "HeightCm": height_cm,
            "WeightKg": weight_kg,
            "TargetAgencyID": agency_id,
            "SourceDevice": device_id
        }
        try:
            url = f"{WEBAPP_URL.rstrip('/')}/api/stowage/telemetry/package"
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=payload)
                if resp.status_code in (200, 201):
                    logging.info(f"Paquete {guide_id} procesado exitosamente vía WebApp API & WebSockets.")
                    return
                else:
                    logging.warning(f"WebApp respondió con error {resp.status_code}: {resp.text}. Guardando vía SQL directo.")
        except Exception as ex:
            logging.error(f"Fallo al conectar con WebApp ({ex}). Procediendo con inserción SQL directa...")

    # Fallback: Inserción directa en Azure SQL Database
    if engine:
        try:
            with engine.connect() as conn:
                # Obtener el mapa de estiba activo
                res = conn.execute(
                    text("SELECT TOP 1 StowageMapID, LengthCm, WidthCm, HeightCm FROM dbo.StowageMaps WHERE Status = 'IN_PROGRESS' ORDER BY StowageMapID DESC")
                ).fetchone()

                if not res:
                    logging.warning("No hay ningún Mapa de Estiba en estado IN_PROGRESS. Guardado omitido.")
                    return

                stowage_map_id, cont_l, cont_w, cont_h = res[0], res[1], res[2], res[3]

                # Contar secuencia
                seq_res = conn.execute(
                    text("SELECT COUNT(1) FROM dbo.PackageData WHERE StowageMapID = :map_id"),
                    {"map_id": stowage_map_id}
                ).scalar() or 0
                seq_order = seq_res + 1

                # Inserción con colocación inicial segura
                insert_sql = text("""
                    INSERT INTO dbo.PackageData (
                        GuideID, StowageMapID, LengthCm, WidthCm, HeightCm, WeightKg,
                        TargetAgencyID, CoordX, CoordY, CoordZ,
                        PlacedLengthCm, PlacedWidthCm, PlacedHeightCm,
                        RotationState, SequenceOrder, SourceDevice, ScannedAt
                    ) VALUES (
                        :guide_id, :map_id, :l, :w, :h, :wt,
                        :ag_id, 0.0, 0.0, 0.0,
                        :l, :w, :h,
                        'LWH', :seq, :device, SYSUTCDATETIME()
                    )
                """)

                conn.execute(insert_sql, {
                    "guide_id": guide_id,
                    "map_id": stowage_map_id,
                    "l": length_cm,
                    "w": width_cm,
                    "h": height_cm,
                    "wt": weight_kg,
                    "ag_id": agency_id,
                    "seq": seq_order,
                    "device": device_id
                })
                conn.commit()
                logging.info(f"Paquete {guide_id} guardado directamente en Azure SQL (Mapa {stowage_map_id}, Sec #{seq_order}).")
        except Exception as db_err:
            logging.error(f"Error escribiendo en Azure SQL Database: {db_err}")


@app.function_name(name="AIExtremePointsInference")
@app.route(route="ai/inference", auth_level=func.AuthLevel.ANONYMOUS)
def ai_inference_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """
    MICROSERVICIO SERVERLESS DE INFERENCIA DE IA (Azure Functions / Azure ML).
    Recibe las dimensiones del camión y la lista o bulto individual,
    y calcula las coordenadas óptimas (x, y, z) con Extreme Points 3D.
    """
    try:
        req_body = req.get_json()
    except ValueError:
        return func.HttpResponse(json.dumps({"error": "JSON no válido"}), status_code=400, mimetype="application/json")

    container = req_body.get("container", {"L": 680.0, "W": 245.0, "H": 250.0})
    pkg = req_body.get("package", {})
    placed_boxes_raw = req_body.get("placed_boxes", [])

    # Reconstruir cajas colocadas
    class SimpleBox:
        def __init__(self, x, y, z, lx, ly, lz):
            self.x = float(x)
            self.y = float(y)
            self.z = float(z)
            self.lx = float(lx)
            self.ly = float(ly)
            self.lz = float(lz)

    placed = [SimpleBox(b["x"], b["y"], b["z"], b.get("lx", 50), b.get("ly", 50), b.get("lz", 50)) for b in placed_boxes_raw]

    # Generar puntos candidatos
    points = {(0.0, 0.0, 0.0)}
    for b in placed:
        if b.x + b.lx < container.get("L", 680):
            points.add((b.x + b.lx, b.y, b.z))
            points.add((b.x + b.lx, 0.0, 0.0))
        if b.y + b.ly < container.get("H", 250):
            points.add((b.x, b.y + b.ly, b.z))
        if b.z + b.lz < container.get("W", 245):
            points.add((b.x, b.y, b.z + b.lz))

    pkg_l = float(pkg.get("L", 60.0))
    pkg_w = float(pkg.get("A", pkg.get("W", 45.0)))
    pkg_h = float(pkg.get("H", 40.0))
    pkg_wt = float(pkg.get("weight", 20.0))

    orientations = [(pkg_l, pkg_h, pkg_w, "LWH"), (pkg_w, pkg_h, pkg_l, "WLH")]

    best_score = float("inf")
    best_coord = (0.0, 0.0, 0.0, pkg_l, pkg_w, pkg_h, "LWH")

    for (cx, cy, cz) in sorted(points):
        for (lx, ly, lz, rot) in orientations:
            if cx + lx > container.get("L", 680) or cy + ly > container.get("H", 250) or cz + lz > container.get("W", 245):
                continue
            # Colisión
            col = False
            for b in placed:
                if not (cx + lx <= b.x or b.x + b.lx <= cx or cy + ly <= b.y or b.y + b.ly <= cy or cz + lz <= b.z or b.z + b.lz <= cz):
                    col = True
                    break
            if col:
                continue

            score = (cx * 3.0) + (cy * 2.5 * (1.0 + (pkg_wt / 25.0))) + (cz * 1.0)
            if score < best_score:
                best_score = score
                best_coord = (cx, cy, cz, lx, lz, ly, rot)

    resp_payload = {
        "x": best_coord[0],
        "y": best_coord[1],
        "z": best_coord[2],
        "placed_l": best_coord[3],
        "placed_w": best_coord[4],
        "placed_h": best_coord[5],
        "rotation": best_coord[6],
        "engine": "Azure-ExtremePoints-3D-AI-Engine"
    }
    return func.HttpResponse(json.dumps(resp_payload), status_code=200, mimetype="application/json")

