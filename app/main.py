"""
Punto de Entrada Principal - OptiStack HMI 3D Dashboard (Azure App Service).
Integra FastAPI, SQLAlchemy (Azure SQL Database), WebSockets en tiempo real y
archivos estáticos del visualizador 3D (Three.js).
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import Base, engine, SessionLocal
from app.models import TruckMaster, AgencyMaster, StowageMap, PackageData
from app.api.routes_trucks import router as trucks_router
from app.api.routes_agencies import router as agencies_router
from app.api.routes_stowage import router as stowage_router
from app.api.websocket import ws_manager
from app.services.extreme_points import ExtremePoints3DEngine, PlacedBox3D


def seed_initial_catalog_if_empty():
    """
    Inicializa registros base en el catálogo CRUD de camiones (TruckMaster) y
    rutas (AgencyMaster) únicamente si la base de datos está vacía en el primer arranque.
    """
    db = SessionLocal()
    try:
        if db.query(TruckMaster).count() == 0:
            trucks = [
                TruckMaster(
                    TruckPlate="ABC-789",
                    TruckName="Furgón Cerrado 12T - Flota Principal",
                    LengthCm=680.0,
                    WidthCm=245.0,
                    HeightCm=250.0,
                    MaxWeightKg=12000.0,
                    EmptyWeightKg=4800.0,
                    IsActive=True,
                ),
                TruckMaster(
                    TruckPlate="XYZ-450",
                    TruckName="Furgón Reparto Urbano 5T",
                    LengthCm=460.0,
                    WidthCm=215.0,
                    HeightCm=210.0,
                    MaxWeightKg=5000.0,
                    EmptyWeightKg=2900.0,
                    IsActive=True,
                ),
                TruckMaster(
                    TruckPlate="TRK-990",
                    TruckName="Contenedor Gran Volumen 18T",
                    LengthCm=850.0,
                    WidthCm=248.0,
                    HeightCm=265.0,
                    MaxWeightKg=18000.0,
                    EmptyWeightKg=6200.0,
                    IsActive=True,
                ),
            ]
            db.add_all(trucks)
            db.commit()

        if db.query(AgencyMaster).count() == 0:
            agencies = [
                AgencyMaster(
                    AgencyID="AG-TRU-01",
                    AgencyName="Agencia Trujillo Norte",
                    RouteCode="CORREDOR-NORTE",
                    ZoneOrder=1,
                    City="Trujillo",
                    ColorHex="#38BDF8",
                    IsActive=True,
                ),
                AgencyMaster(
                    AgencyID="AG-CHI-02",
                    AgencyName="Agencia Chiclayo Central",
                    RouteCode="CORREDOR-NORTE",
                    ZoneOrder=2,
                    City="Chiclayo",
                    ColorHex="#10B981",
                    IsActive=True,
                ),
                AgencyMaster(
                    AgencyID="AG-PIU-03",
                    AgencyName="Agencia Piura Industrial",
                    RouteCode="CORREDOR-NORTE",
                    ZoneOrder=3,
                    City="Piura",
                    ColorHex="#F59E0B",
                    IsActive=True,
                ),
                AgencyMaster(
                    AgencyID="AG-CAJ-04",
                    AgencyName="Agencia Cajamarca Express",
                    RouteCode="CORREDOR-SIERRA",
                    ZoneOrder=4,
                    City="Cajamarca",
                    ColorHex="#A855F7",
                    IsActive=True,
                ),
            ]
            db.add_all(agencies)
            db.commit()

        if db.query(StowageMap).count() == 0:
            first_truck = db.query(TruckMaster).order_by(TruckMaster.TruckID.asc()).first()
            if first_truck:
                sm = StowageMap(
                    MapCode=f"EST-{first_truck.TruckPlate}-001",
                    TruckID=first_truck.TruckID,
                    TruckPlate=first_truck.TruckPlate,
                    TruckName=first_truck.TruckName,
                    RouteSummary="Corredor Norte Multipunto",
                    LengthCm=first_truck.LengthCm,
                    WidthCm=first_truck.WidthCm,
                    HeightCm=first_truck.HeightCm,
                    MaxWeightKg=first_truck.MaxWeightKg,
                    Status="IN_PROGRESS",
                )
                db.add(sm)
                db.commit()
                db.refresh(sm)

                # Sembrar 6 paquetes iniciales calculados con Extreme Points 3D
                initial_specs = [
                    ("GUIA-TRU-1001", 80.0, 60.0, 55.0, 34.5, "AG-TRU-01", 1),
                    ("GUIA-TRU-1002", 80.0, 60.0, 55.0, 31.0, "AG-TRU-01", 1),
                    ("GUIA-TRU-1003", 75.0, 55.0, 50.0, 26.8, "AG-TRU-01", 1),
                    ("GUIA-CHI-1004", 70.0, 50.0, 45.0, 22.4, "AG-CHI-02", 2),
                    ("GUIA-CHI-1005", 65.0, 50.0, 45.0, 18.0, "AG-CHI-02", 2),
                    ("GUIA-PIU-1006", 60.0, 45.0, 40.0, 14.2, "AG-PIU-03", 3),
                ]
                placed: list[PlacedBox3D] = []
                for idx, (gid, l_cm, w_cm, h_cm, wt, ag_id, z_ord) in enumerate(initial_specs, start=1):
                    cx, cy, cz, pl_l, pl_w, pl_h, rot = ExtremePoints3DEngine.calculate_optimal_coordinates(
                        pkg_l=l_cm,
                        pkg_w=w_cm,
                        pkg_h=h_cm,
                        pkg_weight=wt,
                        zone_order=z_ord,
                        container_l=sm.LengthCm,
                        container_w=sm.WidthCm,
                        container_h=sm.HeightCm,
                        placed_boxes=placed,
                    )
                    placed.append(PlacedBox3D(x=cx, y=cy, z=cz, lx=pl_l, ly=pl_h, lz=pl_w, weight=wt))
                    db.add(
                        PackageData(
                            GuideID=gid,
                            StowageMapID=sm.StowageMapID,
                            LengthCm=l_cm,
                            WidthCm=w_cm,
                            HeightCm=h_cm,
                            WeightKg=wt,
                            TargetAgencyID=ag_id,
                            CoordX=cx,
                            CoordY=cy,
                            CoordZ=cz,
                            PlacedLengthCm=pl_l,
                            PlacedWidthCm=pl_w,
                            PlacedHeightCm=pl_h,
                            RotationState=rot,
                            SequenceOrder=idx,
                            SourceDevice="IoT-RPi-ESP32-Gate01",
                        )
                    )
                db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        Base.metadata.create_all(bind=engine)
        seed_initial_catalog_if_empty()
        print("✅ Base de datos inicializada correctamente.")
    except Exception as e:
        print(f"⚠️ Advertencia de conexión a base de datos en arranque: {e}")
    yield


app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trucks_router)
app.include_router(agencies_router)
app.include_router(stowage_router)


@app.get("/api/system/status")
def get_system_status():
    return {
        "app": settings.APP_TITLE,
        "version": settings.APP_VERSION,
        "database_engine": "Azure SQL Database (T-SQL)" if settings.is_azure_sql else "SQLite Local Dev (Compatible Azure SQL)",
        "azure_ml_endpoint": settings.AZURE_ML_ENDPOINT_URL or "Extreme Points 3D Engine (Active)",
        "iot_hub": settings.AZURE_IOT_HUB_NAME,
        "active_ws_clients": len(ws_manager.active_connections),
    }


@app.websocket("/ws/stowage")
async def websocket_stowage_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"event": "PONG"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def serve_hmi_dashboard():
    return FileResponse(os.path.join(static_dir, "index.html"))
