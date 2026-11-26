"""
API REST para el CRUD de Gestión de Camiones / Furgones (TruckMaster).
Permite definir medidas internas libres (Largo, Ancho, Alto en cm y Peso Máximo en kg)
sin depender de medidas estándar fijas.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import TruckMaster, StowageMap
from app.schemas import TruckCreate, TruckUpdate, TruckOut
from app.api.websocket import ws_manager

router = APIRouter(prefix="/api/trucks", tags=["TruckMaster CRUD"])


@router.get("", response_model=List[TruckOut])
def list_trucks(db: Session = Depends(get_db)):
    return db.query(TruckMaster).order_by(TruckMaster.TruckID.desc()).all()


@router.post("", response_model=TruckOut, status_code=status.HTTP_201_CREATED)
async def create_truck(payload: TruckCreate, db: Session = Depends(get_db)):
    plate_clean = payload.TruckPlate.strip().upper()
    existing = db.query(TruckMaster).filter(TruckMaster.TruckPlate == plate_clean).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe un camión registrado con la placa '{plate_clean}'.",
        )

    truck = TruckMaster(
        TruckPlate=plate_clean,
        TruckName=payload.TruckName.strip(),
        LengthCm=payload.LengthCm,
        WidthCm=payload.WidthCm,
        HeightCm=payload.HeightCm,
        MaxWeightKg=payload.MaxWeightKg,
        EmptyWeightKg=payload.EmptyWeightKg,
        IsActive=payload.IsActive,
    )
    db.add(truck)
    db.commit()
    db.refresh(truck)

    await ws_manager.broadcast_json({"event": "TRUCK_CATALOG_UPDATED", "truck_id": truck.TruckID})
    return truck


@router.put("/{truck_id}", response_model=TruckOut)
async def update_truck(truck_id: int, payload: TruckUpdate, db: Session = Depends(get_db)):
    truck = db.query(TruckMaster).filter(TruckMaster.TruckID == truck_id).first()
    if not truck:
        raise HTTPException(status_code=404, detail="Camión no encontrado.")

    if payload.TruckPlate is not None:
        plate_clean = payload.TruckPlate.strip().upper()
        dup = (
            db.query(TruckMaster)
            .filter(TruckMaster.TruckPlate == plate_clean, TruckMaster.TruckID != truck_id)
            .first()
        )
        if dup:
            raise HTTPException(status_code=400, detail=f"La placa '{plate_clean}' ya está en uso.")
        truck.TruckPlate = plate_clean

    if payload.TruckName is not None:
        truck.TruckName = payload.TruckName.strip()
    if payload.LengthCm is not None:
        truck.LengthCm = payload.LengthCm
    if payload.WidthCm is not None:
        truck.WidthCm = payload.WidthCm
    if payload.HeightCm is not None:
        truck.HeightCm = payload.HeightCm
    if payload.MaxWeightKg is not None:
        truck.MaxWeightKg = payload.MaxWeightKg
    if payload.EmptyWeightKg is not None:
        truck.EmptyWeightKg = payload.EmptyWeightKg
    if payload.IsActive is not None:
        truck.IsActive = payload.IsActive

    # Sincronizar mapas de estiba en curso asociados a este camión
    active_maps = (
        db.query(StowageMap)
        .filter(StowageMap.TruckID == truck_id, StowageMap.Status == "IN_PROGRESS")
        .all()
    )
    for sm in active_maps:
        sm.TruckPlate = truck.TruckPlate
        sm.TruckName = truck.TruckName
        sm.LengthCm = truck.LengthCm
        sm.WidthCm = truck.WidthCm
        sm.HeightCm = truck.HeightCm
        sm.MaxWeightKg = truck.MaxWeightKg

    db.commit()
    db.refresh(truck)

    await ws_manager.broadcast_json({"event": "TRUCK_CATALOG_UPDATED", "truck_id": truck.TruckID})
    return truck


@router.delete("/{truck_id}")
async def delete_truck(truck_id: int, db: Session = Depends(get_db)):
    truck = db.query(TruckMaster).filter(TruckMaster.TruckID == truck_id).first()
    if not truck:
        raise HTTPException(status_code=404, detail="Camión no encontrado.")

    in_use = db.query(StowageMap).filter(StowageMap.TruckID == truck_id).count()
    if in_use > 0:
        # Eliminar también sus mapas o devolver aviso; permitimos eliminación limpia en cascada
        db.query(StowageMap).filter(StowageMap.TruckID == truck_id).delete()

    db.delete(truck)
    db.commit()
    await ws_manager.broadcast_json({"event": "TRUCK_CATALOG_UPDATED", "truck_id": truck_id})
    return {"status": "deleted", "truck_id": truck_id}
