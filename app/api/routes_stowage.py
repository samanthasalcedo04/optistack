"""
API REST para Mapas de Estiba (StowageMaps), Ingesta Dinámica de Paquetes (PackageData)
desde Azure IoT Hub / Azure Functions y Simulador de Telemetría IoT en tiempo real.
"""

import random
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import TruckMaster, AgencyMaster, StowageMap, PackageData
from app.schemas import (
    StowageMapCreate,
    StowageMapFullOut,
    TelemetryPackageIn,
)
from app.services.extreme_points import ExtremePoints3DEngine, PlacedBox3D
from app.services.stowage_service import build_stowage_map_response
from app.services.excel_service import generate_packages_excel_template, parse_packages_from_excel
from app.api.websocket import ws_manager

router = APIRouter(prefix="/api/stowage", tags=["Stowage 3D & IoT Telemetry"])


def _get_agencies_dict(db: Session) -> dict[str, AgencyMaster]:
    agencies = db.query(AgencyMaster).all()
    return {a.AgencyID: a for a in agencies}


@router.get("/maps")
def list_stowage_maps(db: Session = Depends(get_db)):
    maps = db.query(StowageMap).order_by(StowageMap.StowageMapID.desc()).all()
    return [
        {
            "StowageMapID": m.StowageMapID,
            "MapCode": m.MapCode,
            "TruckID": m.TruckID,
            "TruckPlate": m.TruckPlate,
            "TruckName": m.TruckName,
            "RouteSummary": m.RouteSummary,
            "LengthCm": m.LengthCm,
            "WidthCm": m.WidthCm,
            "HeightCm": m.HeightCm,
            "MaxWeightKg": m.MaxWeightKg,
            "Status": m.Status,
            "PackageCount": len(m.packages),
            "CreatedAt": m.CreatedAt,
        }
        for m in maps
    ]


@router.get("/maps/active", response_model=StowageMapFullOut)
def get_active_stowage_map(db: Session = Depends(get_db)):
    sm = (
        db.query(StowageMap)
        .filter(StowageMap.Status == "IN_PROGRESS")
        .order_by(StowageMap.StowageMapID.desc())
        .first()
    )
    if not sm:
        sm = db.query(StowageMap).order_by(StowageMap.StowageMapID.desc()).first()
    if not sm:
        raise HTTPException(
            status_code=404,
            detail="No hay mapas de estiba creados. Registra un camión en el CRUD e inicia una estiba.",
        )

    return build_stowage_map_response(sm, _get_agencies_dict(db))


@router.get("/maps/{map_id}", response_model=StowageMapFullOut)
def get_stowage_map_by_id(map_id: int, db: Session = Depends(get_db)):
    sm = db.query(StowageMap).filter(StowageMap.StowageMapID == map_id).first()
    if not sm:
        raise HTTPException(status_code=404, detail="Mapa de estiba no encontrado.")
    return build_stowage_map_response(sm, _get_agencies_dict(db))


@router.post("/maps", response_model=StowageMapFullOut)
async def create_stowage_map(payload: StowageMapCreate, db: Session = Depends(get_db)):
    truck = db.query(TruckMaster).filter(TruckMaster.TruckID == payload.TruckID).first()
    if not truck:
        raise HTTPException(status_code=404, detail="El camión seleccionado no existe en el CRUD.")

    map_code = payload.MapCode or f"EST-{truck.TruckPlate}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
    new_map = StowageMap(
        MapCode=map_code,
        TruckID=truck.TruckID,
        TruckPlate=truck.TruckPlate,
        TruckName=truck.TruckName,
        RouteSummary=payload.RouteSummary or "Estiba Dinámica 3D",
        LengthCm=truck.LengthCm,
        WidthCm=truck.WidthCm,
        HeightCm=truck.HeightCm,
        MaxWeightKg=truck.MaxWeightKg,
        Status="IN_PROGRESS",
    )
    db.add(new_map)
    db.commit()
    db.refresh(new_map)

    full_out = build_stowage_map_response(new_map, _get_agencies_dict(db))
    await ws_manager.broadcast_json(
        {
            "event": "STOWAGE_MAP_SWITCHED",
            "stowage_map": full_out.model_dump(mode="json"),
        }
    )
    return full_out


@router.post("/maps/{map_id}/clear", response_model=StowageMapFullOut)
async def clear_stowage_map(map_id: int, db: Session = Depends(get_db)):
    """Vacía todos los paquetes del mapa de estiba actual para reiniciar la carga."""
    sm = db.query(StowageMap).filter(StowageMap.StowageMapID == map_id).first()
    if not sm:
        raise HTTPException(status_code=404, detail="Mapa de estiba no encontrado.")

    db.query(PackageData).filter(PackageData.StowageMapID == map_id).delete()
    db.commit()
    db.refresh(sm)

    full_out = build_stowage_map_response(sm, _get_agencies_dict(db))
    await ws_manager.broadcast_json(
        {
            "event": "STOWAGE_MAP_CLEARED",
            "stowage_map": full_out.model_dump(mode="json"),
        }
    )
    return full_out


@router.post("/telemetry/package", response_model=StowageMapFullOut)
async def ingest_package_telemetry(payload: TelemetryPackageIn, db: Session = Depends(get_db)):
    """
    Endpoint receptor de paquetes escaneados por sensores volumétricos y balanza
    (vía Azure Functions / IoT Hub o panel de ingreso manual/simulado).
    Calcula coordenadas (x,y,z) con Extreme Points 3D y notifica al visor 3D por WebSocket.
    """
    if payload.StowageMapID:
        sm = db.query(StowageMap).filter(StowageMap.StowageMapID == payload.StowageMapID).first()
    else:
        sm = (
            db.query(StowageMap)
            .filter(StowageMap.Status == "IN_PROGRESS")
            .order_by(StowageMap.StowageMapID.desc())
            .first()
        )
    if not sm:
        raise HTTPException(status_code=404, detail="No existe un mapa de estiba activo.")

    agency = db.query(AgencyMaster).filter(AgencyMaster.AgencyID == payload.TargetAgencyID).first()
    if not agency:
        raise HTTPException(
            status_code=400,
            detail=f"La Agencia/Ruta '{payload.TargetAgencyID}' no existe en el catálogo AgencyMaster.",
        )

    # Construir lista de cajas ya ubicadas en el contenedor
    placed_boxes: List[PlacedBox3D] = [
        PlacedBox3D(
            x=p.CoordX,
            y=p.CoordY,
            z=p.CoordZ,
            lx=p.PlacedLengthCm,
            ly=p.PlacedHeightCm,
            lz=p.PlacedWidthCm,
            weight=p.WeightKg,
        )
        for p in sm.packages
    ]

    if (
        payload.CoordX is not None
        and payload.CoordY is not None
        and payload.CoordZ is not None
    ):
        cx, cy, cz = payload.CoordX, payload.CoordY, payload.CoordZ
        pl_l, pl_w, pl_h = payload.LengthCm, payload.WidthCm, payload.HeightCm
        rot_state = payload.RotationState or "LWH"
    else:
        cx, cy, cz, pl_l, pl_w, pl_h, rot_state = ExtremePoints3DEngine.calculate_optimal_coordinates(
            pkg_l=payload.LengthCm,
            pkg_w=payload.WidthCm,
            pkg_h=payload.HeightCm,
            pkg_weight=payload.WeightKg,
            zone_order=agency.ZoneOrder,
            container_l=sm.LengthCm,
            container_w=sm.WidthCm,
            container_h=sm.HeightCm,
            placed_boxes=placed_boxes,
        )

    seq_order = len(sm.packages) + 1
    guide_id = payload.GuideID.strip().upper()
    # Evitar colisión de GuideID en el mismo mapa
    existing_guide = (
        db.query(PackageData)
        .filter(PackageData.StowageMapID == sm.StowageMapID, PackageData.GuideID == guide_id)
        .first()
    )
    if existing_guide:
        guide_id = f"{guide_id}-{seq_order:03d}"

    new_pkg = PackageData(
        GuideID=guide_id,
        StowageMapID=sm.StowageMapID,
        LengthCm=round(payload.LengthCm, 1),
        WidthCm=round(payload.WidthCm, 1),
        HeightCm=round(payload.HeightCm, 1),
        WeightKg=round(payload.WeightKg, 2),
        TargetAgencyID=agency.AgencyID,
        CoordX=cx,
        CoordY=cy,
        CoordZ=cz,
        PlacedLengthCm=pl_l,
        PlacedWidthCm=pl_w,
        PlacedHeightCm=pl_h,
        RotationState=rot_state,
        SequenceOrder=seq_order,
        SourceDevice=payload.SourceDevice,
    )
    db.add(new_pkg)
    db.commit()
    db.refresh(sm)

    full_out = build_stowage_map_response(sm, _get_agencies_dict(db))
    latest_pkg_dict = full_out.packages[-1].model_dump(mode="json") if full_out.packages else None

    await ws_manager.broadcast_json(
        {
            "event": "PACKAGE_INGESTED",
            "latest_package": latest_pkg_dict,
            "stowage_map": full_out.model_dump(mode="json"),
        }
    )
    return full_out


@router.post("/telemetry/simulate-random", response_model=StowageMapFullOut)
async def simulate_iot_package(
    map_id: int | None = None,
    db: Session = Depends(get_db),
):
    """
    Simula un paquete entrante desde los sensores (Raspberry Pi / ESP32 -> Azure IoT Hub)
    eligiendo una ruta activa del catálogo AgencyMaster y dimensiones realistas de carga.
    """
    agencies = db.query(AgencyMaster).filter(AgencyMaster.IsActive == True).order_by(AgencyMaster.ZoneOrder.asc()).all()
    if not agencies:
        raise HTTPException(
            status_code=400,
            detail="No hay rutas/agencias activas en el catálogo. Registra o importa rutas por Excel primero.",
        )

    if map_id:
        sm = db.query(StowageMap).filter(StowageMap.StowageMapID == map_id).first()
    else:
        sm = (
            db.query(StowageMap)
            .filter(StowageMap.Status == "IN_PROGRESS")
            .order_by(StowageMap.StowageMapID.desc())
            .first()
        )
    if not sm:
        raise HTTPException(status_code=404, detail="No hay un mapa de estiba activo.")

    # Seleccionar agencia priorizando rutas de fondo al inicio y puertas conforme avanza la carga
    seq = len(sm.packages) + 1
    idx = min(len(agencies) - 1, int((seq - 1) / 5) % len(agencies))
    chosen_agency = agencies[idx] if random.random() < 0.72 else random.choice(agencies)

    # Perfiles realistas de cajas/bultos industriales (L, A, H en cm y rango de peso en kg)
    box_profiles = [
        (60.0, 45.0, 45.0, (12.0, 28.0)),
        (80.0, 60.0, 50.0, (18.0, 42.0)),
        (55.0, 40.0, 35.0, (6.0, 16.0)),
        (100.0, 60.0, 60.0, (25.0, 55.0)),
        (70.0, 50.0, 40.0, (10.0, 24.0)),
        (50.0, 50.0, 50.0, (8.0, 20.0)),
    ]
    l_cm, w_cm, h_cm, (w_min, w_max) = random.choice(box_profiles)

    # Ajustar si el furgón personalizado es muy compacto
    l_cm = min(l_cm, round(sm.LengthCm * 0.35, 1))
    w_cm = min(w_cm, round(sm.WidthCm * 0.45, 1))
    h_cm = min(h_cm, round(sm.HeightCm * 0.40, 1))

    weight_kg = round(random.uniform(w_min, w_max), 1)
    guide_code = f"GUIA-{chosen_agency.AgencyID[-3:]}-{1000 + seq}"

    sim_payload = TelemetryPackageIn(
        GuideID=guide_code,
        LengthCm=l_cm,
        WidthCm=w_cm,
        HeightCm=h_cm,
        WeightKg=weight_kg,
        TargetAgencyID=chosen_agency.AgencyID,
        StowageMapID=sm.StowageMapID,
        SourceDevice="RPi4-LaserVol-ESP32",
    )
    return await ingest_package_telemetry(sim_payload, db)


@router.delete("/packages/{package_id}", response_model=StowageMapFullOut)
async def delete_single_package(package_id: int, db: Session = Depends(get_db)):
    pkg = db.query(PackageData).filter(PackageData.PackageID == package_id).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="Paquete no encontrado.")

    map_id = pkg.StowageMapID
    db.delete(pkg)
    db.commit()

    sm = db.query(StowageMap).filter(StowageMap.StowageMapID == map_id).first()
    full_out = build_stowage_map_response(sm, _get_agencies_dict(db))
    await ws_manager.broadcast_json(
        {
            "event": "PACKAGE_REMOVED",
            "stowage_map": full_out.model_dump(mode="json"),
        }
    )
    return full_out


@router.get("/excel/packages-template")
def download_packages_template():
    """Descarga la plantilla Excel (.xlsx) oficial para la carga de manifiesto de paquetes."""
    excel_bytes = generate_packages_excel_template()
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="Plantilla_Manifiesto_Paquetes_OptiStack.xlsx"'},
    )


@router.post("/maps/{map_id}/excel/packages", response_model=StowageMapFullOut)
async def upload_packages_excel_and_optimize(
    map_id: int,
    file: UploadFile = File(...),
    replace_existing: bool = True,
    db: Session = Depends(get_db),
):
    """
    ENDPOINT DE INTELIGENCIA ARTIFICIAL (BATCH OPTIMIZER):
    1. Recibe un archivo Excel (.xlsx) con el manifiesto de carga de paquetes.
    2. Ejecuta el algoritmo AI Extreme Points 3D (ordenamiento LIFO + CoG + soporte).
    3. Persiste las coordenadas en Azure SQL y emite la actualización 3D en vivo por WebSocket.
    """
    sm = db.query(StowageMap).filter(StowageMap.StowageMapID == map_id).first()
    if not sm:
        raise HTTPException(status_code=404, detail="Mapa de estiba no encontrado.")

    if not file.filename.endswith((".xlsx", ".XLSX")):
        raise HTTPException(status_code=400, detail="El archivo debe tener formato Excel (.xlsx).")

    file_bytes = await file.read()
    raw_packages = parse_packages_from_excel(file_bytes)
    if not raw_packages:
        raise HTTPException(status_code=400, detail="El archivo Excel no contiene paquetes con datos válidos.")

    agencies_dict = _get_agencies_dict(db)

    # Si se pide reemplazar existentes, limpiar primero
    if replace_existing:
        db.query(PackageData).filter(PackageData.StowageMapID == map_id).delete()
        db.commit()

    # Ejecutar el Motor de IA
    placed_results = ExtremePoints3DEngine.optimize_batch_manifest(
        container_l=sm.LengthCm,
        container_w=sm.WidthCm,
        container_h=sm.HeightCm,
        max_weight_kg=sm.MaxWeightKg,
        packages_input=raw_packages,
        agencies_by_id=agencies_dict,
    )

    # Persistir en la base de datos
    for p in placed_results:
        db.add(
            PackageData(
                GuideID=p["GuideID"],
                StowageMapID=sm.StowageMapID,
                LengthCm=p["LengthCm"],
                WidthCm=p["WidthCm"],
                HeightCm=p["HeightCm"],
                WeightKg=p["WeightKg"],
                TargetAgencyID=p["TargetAgencyID"],
                CoordX=p["CoordX"],
                CoordY=p["CoordY"],
                CoordZ=p["CoordZ"],
                PlacedLengthCm=p["PlacedLengthCm"],
                PlacedWidthCm=p["PlacedWidthCm"],
                PlacedHeightCm=p["PlacedHeightCm"],
                RotationState=p["RotationState"],
                SequenceOrder=p["SequenceOrder"],
                SourceDevice="AI-Batch-Optimizer-Excel",
            )
        )
    db.commit()
    db.refresh(sm)

    full_out = build_stowage_map_response(sm, agencies_dict)
    await ws_manager.broadcast_json(
        {
            "event": "AI_BATCH_STOWAGE_OPTIMIZED",
            "stowage_map": full_out.model_dump(mode="json"),
        }
    )
    return full_out


@router.post("/maps/{map_id}/ai-reoptimize", response_model=StowageMapFullOut)
async def reoptimize_existing_stowage_map(map_id: int, db: Session = Depends(get_db)):
    """
    Reorganiza y re-optimiza con el motor de IA todos los paquetes actualmente asignados
    al mapa de estiba, aplicando el ordenamiento LIFO estricto y la minimización del CoG.
    """
    sm = db.query(StowageMap).filter(StowageMap.StowageMapID == map_id).first()
    if not sm:
        raise HTTPException(status_code=404, detail="Mapa de estiba no encontrado.")

    existing_pkgs = db.query(PackageData).filter(PackageData.StowageMapID == map_id).all()
    if not existing_pkgs:
        raise HTTPException(status_code=400, detail="No hay paquetes en este mapa para optimizar.")

    raw_list = [
        {
            "guide_id": p.GuideID,
            "length_cm": p.LengthCm,
            "width_cm": p.WidthCm,
            "height_cm": p.HeightCm,
            "weight_kg": p.WeightKg,
            "agency_id": p.TargetAgencyID,
        }
        for p in existing_pkgs
    ]

    agencies_dict = _get_agencies_dict(db)

    # Limpiar posiciones anteriores
    db.query(PackageData).filter(PackageData.StowageMapID == map_id).delete()
    db.commit()

    # Re-optimizar con IA
    placed_results = ExtremePoints3DEngine.optimize_batch_manifest(
        container_l=sm.LengthCm,
        container_w=sm.WidthCm,
        container_h=sm.HeightCm,
        max_weight_kg=sm.MaxWeightKg,
        packages_input=raw_list,
        agencies_by_id=agencies_dict,
    )

    for p in placed_results:
        db.add(
            PackageData(
                GuideID=p["GuideID"],
                StowageMapID=sm.StowageMapID,
                LengthCm=p["LengthCm"],
                WidthCm=p["WidthCm"],
                HeightCm=p["HeightCm"],
                WeightKg=p["WeightKg"],
                TargetAgencyID=p["TargetAgencyID"],
                CoordX=p["CoordX"],
                CoordY=p["CoordY"],
                CoordZ=p["CoordZ"],
                PlacedLengthCm=p["PlacedLengthCm"],
                PlacedWidthCm=p["PlacedWidthCm"],
                PlacedHeightCm=p["PlacedHeightCm"],
                RotationState=p["RotationState"],
                SequenceOrder=p["SequenceOrder"],
                SourceDevice="AI-Reoptimizer",
            )
        )
    db.commit()
    db.refresh(sm)

    full_out = build_stowage_map_response(sm, agencies_dict)
    await ws_manager.broadcast_json(
        {
            "event": "AI_BATCH_STOWAGE_OPTIMIZED",
            "stowage_map": full_out.model_dump(mode="json"),
        }
    )
    return full_out

