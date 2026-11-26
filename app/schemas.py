from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# =============================================================================
# 1. ESQUEMAS CRUD DE CAMIONES / FURGONES (TruckMaster)
# =============================================================================
class TruckBase(BaseModel):
    TruckPlate: str = Field(..., min_length=2, max_length=30, description="Placa única del furgón/camión")
    TruckName: str = Field(..., min_length=2, max_length=120, description="Nombre o descripción del furgón")
    LengthCm: float = Field(..., gt=50, le=2500, description="Largo interno útil del furgón en cm")
    WidthCm: float = Field(..., gt=50, le=500, description="Ancho interno útil del furgón en cm")
    HeightCm: float = Field(..., gt=50, le=500, description="Alto interno útil del furgón en cm")
    MaxWeightKg: float = Field(..., gt=50, le=60000, description="Capacidad máxima de carga en kg")
    EmptyWeightKg: float = Field(default=0.0, ge=0, description="Tara o peso vacío en kg")
    IsActive: bool = Field(default=True)


class TruckCreate(TruckBase):
    pass


class TruckUpdate(BaseModel):
    TruckPlate: Optional[str] = Field(None, min_length=2, max_length=30)
    TruckName: Optional[str] = Field(None, min_length=2, max_length=120)
    LengthCm: Optional[float] = Field(None, gt=50, le=2500)
    WidthCm: Optional[float] = Field(None, gt=50, le=500)
    HeightCm: Optional[float] = Field(None, gt=50, le=500)
    MaxWeightKg: Optional[float] = Field(None, gt=50, le=60000)
    EmptyWeightKg: Optional[float] = Field(None, ge=0)
    IsActive: Optional[bool] = None


class TruckOut(TruckBase):
    TruckID: int
    CreatedAt: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# 2. ESQUEMAS CRUD DE CATÁLOGO DE RUTAS / AGENCIAS (AgencyMaster)
# =============================================================================
class AgencyBase(BaseModel):
    AgencyID: str = Field(..., min_length=2, max_length=40, description="Código único de Ruta/Agencia")
    AgencyName: str = Field(..., min_length=2, max_length=120, description="Nombre de Agencia o Destino")
    RouteCode: str = Field(..., min_length=2, max_length=60, description="Código de Corredor o Ruta")
    ZoneOrder: int = Field(
        default=1,
        ge=1,
        le=99,
        description="Orden de estiba LIFO (1 = última parada/al fondo, mayor = cerca a puerta)",
    )
    City: Optional[str] = Field(default="", max_length=100)
    ColorHex: str = Field(default="#38BDF8", pattern=r"^#[0-9A-Fa-f]{6}$")
    IsActive: bool = Field(default=True)


class AgencyCreate(AgencyBase):
    pass


class AgencyUpdate(BaseModel):
    AgencyName: Optional[str] = Field(None, min_length=2, max_length=120)
    RouteCode: Optional[str] = Field(None, min_length=2, max_length=60)
    ZoneOrder: Optional[int] = Field(None, ge=1, le=99)
    City: Optional[str] = Field(None, max_length=100)
    ColorHex: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    IsActive: Optional[bool] = None


class AgencyOut(AgencyBase):
    CreatedAt: datetime

    model_config = {"from_attributes": True}


class ExcelBulkImportResult(BaseModel):
    total_rows_read: int
    inserted_count: int
    updated_count: int
    skipped_count: int
    errors: List[str]


# =============================================================================
# 3. ESQUEMAS DE PAQUETES Y MAPA DE ESTIBA 3D (StowageMaps & PackageData)
# =============================================================================
class TelemetryPackageIn(BaseModel):
    """Payload de entrada desde Azure IoT Hub / Azure Functions o Simulador HMI."""

    GuideID: str = Field(..., min_length=2, max_length=60, description="Código de guía escaneado")
    LengthCm: float = Field(..., gt=5, le=600, description="Largo medido por sensor volumétrico (L) en cm")
    WidthCm: float = Field(..., gt=5, le=400, description="Ancho medido por sensor volumétrico (A) en cm")
    HeightCm: float = Field(..., gt=5, le=400, description="Alto medido por sensor volumétrico (H) en cm")
    WeightKg: float = Field(..., gt=0.1, le=5000, description="Peso medido por balanza industrial en kg")
    TargetAgencyID: str = Field(..., description="Código de Ruta/Agencia destino")
    StowageMapID: Optional[int] = Field(None, description="ID del mapa de estiba (usa el activo si se omite)")
    SourceDevice: str = Field(default="IoT-RPi-ESP32-Gate01")
    # Opcional: si Azure Functions ya calculó (x,y,z) con Azure ML lo puede enviar directamente:
    CoordX: Optional[float] = None
    CoordY: Optional[float] = None
    CoordZ: Optional[float] = None
    RotationState: Optional[str] = None


class PackageOut(BaseModel):
    PackageID: int
    GuideID: str
    StowageMapID: int
    LengthCm: float
    WidthCm: float
    HeightCm: float
    WeightKg: float
    TargetAgencyID: str
    AgencyName: Optional[str] = None
    RouteCode: Optional[str] = None
    ZoneOrder: Optional[int] = 1
    ColorHex: Optional[str] = "#38BDF8"
    CoordX: float
    CoordY: float
    CoordZ: float
    PlacedLengthCm: float
    PlacedWidthCm: float
    PlacedHeightCm: float
    RotationState: str
    SequenceOrder: int
    SourceDevice: str
    ScannedAt: datetime

    model_config = {"from_attributes": True}


class StowageMapCreate(BaseModel):
    TruckID: int = Field(..., description="ID del camión registrado en el CRUD TruckMaster")
    RouteSummary: Optional[str] = Field(default="Ruta Nacional Multipunto", max_length=200)
    MapCode: Optional[str] = Field(None, max_length=50)


class StowageKPIs(BaseModel):
    total_packages: int
    occupied_volume_m3: float
    container_volume_m3: float
    volume_utilization_pct: float
    total_weight_kg: float
    max_weight_kg: float
    weight_utilization_pct: float
    cog_x_cm: float
    cog_y_cm: float
    cog_z_cm: float
    cog_x_Offset_pct: float  # Desviación respecto al centro longitudinal (-50% a +50%)
    cog_z_Offset_pct: float  # Desviación lateral izquierda/derecha (-50% a +50%)
    stability_status: str    # OPTIMAL, WARNING, CRITICAL
    agency_breakdown: list[dict]


class StowageMapFullOut(BaseModel):
    StowageMapID: int
    MapCode: str
    TruckID: int
    TruckPlate: str
    TruckName: str
    RouteSummary: Optional[str]
    LengthCm: float
    WidthCm: float
    HeightCm: float
    MaxWeightKg: float
    Status: str
    CreatedAt: datetime
    packages: List[PackageOut]
    kpis: StowageKPIs
