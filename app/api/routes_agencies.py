"""
API REST para el CRUD de Catálogo de Rutas / Agencias Destino (AgencyMaster)
incluyendo Descarga de Plantilla Excel (.xlsx) y Carga Masiva mediante Excel.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AgencyMaster, PackageData
from app.schemas import AgencyCreate, AgencyUpdate, AgencyOut, ExcelBulkImportResult
from app.services.excel_service import generate_routes_excel_template, process_routes_excel_upload
from app.api.websocket import ws_manager

router = APIRouter(prefix="/api/agencies", tags=["AgencyMaster CRUD & Excel Bulk Load"])


@router.get("", response_model=List[AgencyOut])
def list_agencies(db: Session = Depends(get_db)):
    return db.query(AgencyMaster).order_by(AgencyMaster.ZoneOrder.asc(), AgencyMaster.AgencyID.asc()).all()


@router.post("", response_model=AgencyOut, status_code=status.HTTP_201_CREATED)
async def create_agency(payload: AgencyCreate, db: Session = Depends(get_db)):
    ag_id = payload.AgencyID.strip().upper()
    existing = db.query(AgencyMaster).filter(AgencyMaster.AgencyID == ag_id).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe una ruta/agencia con el código '{ag_id}'.",
        )

    agency = AgencyMaster(
        AgencyID=ag_id,
        AgencyName=payload.AgencyName.strip(),
        RouteCode=payload.RouteCode.strip().upper(),
        ZoneOrder=payload.ZoneOrder,
        City=(payload.City or "").strip(),
        ColorHex=payload.ColorHex.upper(),
        IsActive=payload.IsActive,
    )
    db.add(agency)
    db.commit()
    db.refresh(agency)

    await ws_manager.broadcast_json({"event": "AGENCY_CATALOG_UPDATED", "agency_id": agency.AgencyID})
    return agency


@router.put("/{agency_id}", response_model=AgencyOut)
async def update_agency(agency_id: str, payload: AgencyUpdate, db: Session = Depends(get_db)):
    ag_id = agency_id.strip().upper()
    agency = db.query(AgencyMaster).filter(AgencyMaster.AgencyID == ag_id).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Ruta / Agencia no encontrada.")

    if payload.AgencyName is not None:
        agency.AgencyName = payload.AgencyName.strip()
    if payload.RouteCode is not None:
        agency.RouteCode = payload.RouteCode.strip().upper()
    if payload.ZoneOrder is not None:
        agency.ZoneOrder = payload.ZoneOrder
    if payload.City is not None:
        agency.City = payload.City.strip()
    if payload.ColorHex is not None:
        agency.ColorHex = payload.ColorHex.upper()
    if payload.IsActive is not None:
        agency.IsActive = payload.IsActive

    db.commit()
    db.refresh(agency)

    await ws_manager.broadcast_json({"event": "AGENCY_CATALOG_UPDATED", "agency_id": agency.AgencyID})
    return agency


@router.delete("/{agency_id}")
async def delete_agency(agency_id: str, db: Session = Depends(get_db)):
    ag_id = agency_id.strip().upper()
    agency = db.query(AgencyMaster).filter(AgencyMaster.AgencyID == ag_id).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Ruta / Agencia no encontrada.")

    pkg_count = db.query(PackageData).filter(PackageData.TargetAgencyID == ag_id).count()
    if pkg_count > 0:
        db.query(PackageData).filter(PackageData.TargetAgencyID == ag_id).delete()

    db.delete(agency)
    db.commit()

    await ws_manager.broadcast_json({"event": "AGENCY_CATALOG_UPDATED", "agency_id": ag_id})
    return {"status": "deleted", "agency_id": ag_id}


@router.get("/excel/template")
def download_excel_template():
    """Descarga la plantilla Excel (.xlsx) oficial para la carga masiva de rutas."""
    excel_bytes = generate_routes_excel_template()
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="Plantilla_Catalogo_Rutas_OptiStack.xlsx"'
        },
    )


@router.post("/excel/upload", response_model=ExcelBulkImportResult)
async def upload_routes_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Procesa un archivo Excel (.xlsx) para la carga masiva del catálogo de rutas."""
    filename = (file.filename or "").lower()
    if not filename.endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Por favor selecciona un archivo de Excel válido con extensión .xlsx",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="El archivo subido está vacío.")

    result = process_routes_excel_upload(content, db)
    await ws_manager.broadcast_json({"event": "AGENCY_CATALOG_UPDATED", "bulk": True})
    return result
