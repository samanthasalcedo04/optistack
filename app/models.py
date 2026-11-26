from datetime import datetime, timezone
from sqlalchemy import String, Float, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TruckMaster(Base):
    """Catálogo CRUD de Camiones / Furgones con medidas internas personalizadas."""

    __tablename__ = "TruckMaster"

    TruckID: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    TruckPlate: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    TruckName: Mapped[str] = mapped_column(String(120), nullable=False)
    LengthCm: Mapped[float] = mapped_column(Float, nullable=False)
    WidthCm: Mapped[float] = mapped_column(Float, nullable=False)
    HeightCm: Mapped[float] = mapped_column(Float, nullable=False)
    MaxWeightKg: Mapped[float] = mapped_column(Float, nullable=False)
    EmptyWeightKg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    IsActive: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    CreatedAt: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class AgencyMaster(Base):
    """Catálogo CRUD de Rutas / Agencias Destino (soporta Carga Masiva Excel)."""

    __tablename__ = "AgencyMaster"

    AgencyID: Mapped[str] = mapped_column(String(40), primary_key=True)
    AgencyName: Mapped[str] = mapped_column(String(120), nullable=False)
    RouteCode: Mapped[str] = mapped_column(String(60), nullable=False)
    ZoneOrder: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    City: Mapped[str] = mapped_column(String(100), default="", nullable=True)
    ColorHex: Mapped[str] = mapped_column(String(12), default="#38BDF8", nullable=False)
    IsActive: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    CreatedAt: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class StowageMap(Base):
    """Mapa de Estiba activo o histórico asociado a un camión del CRUD."""

    __tablename__ = "StowageMaps"

    StowageMapID: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    MapCode: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    TruckID: Mapped[int] = mapped_column(Integer, ForeignKey("TruckMaster.TruckID"), nullable=False)
    TruckPlate: Mapped[str] = mapped_column(String(30), nullable=False)
    TruckName: Mapped[str] = mapped_column(String(120), nullable=False)
    RouteSummary: Mapped[str] = mapped_column(String(200), default="General", nullable=True)
    LengthCm: Mapped[float] = mapped_column(Float, nullable=False)
    WidthCm: Mapped[float] = mapped_column(Float, nullable=False)
    HeightCm: Mapped[float] = mapped_column(Float, nullable=False)
    MaxWeightKg: Mapped[float] = mapped_column(Float, nullable=False)
    Status: Mapped[str] = mapped_column(String(25), default="IN_PROGRESS", nullable=False)
    CreatedAt: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    packages: Mapped[list["PackageData"]] = relationship(
        "PackageData",
        back_populates="stowage_map",
        cascade="all, delete-orphan",
        order_by="PackageData.SequenceOrder",
    )


class PackageData(Base):
    """Paquetes escaneados por telemetría IoT y posicionados mediante Extreme Points 3D."""

    __tablename__ = "PackageData"

    PackageID: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    GuideID: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    StowageMapID: Mapped[int] = mapped_column(
        Integer, ForeignKey("StowageMaps.StowageMapID", ondelete="CASCADE"), nullable=False, index=True
    )
    LengthCm: Mapped[float] = mapped_column(Float, nullable=False)
    WidthCm: Mapped[float] = mapped_column(Float, nullable=False)
    HeightCm: Mapped[float] = mapped_column(Float, nullable=False)
    WeightKg: Mapped[float] = mapped_column(Float, nullable=False)
    TargetAgencyID: Mapped[str] = mapped_column(
        String(40), ForeignKey("AgencyMaster.AgencyID"), nullable=False
    )
    CoordX: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    CoordY: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    CoordZ: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    PlacedLengthCm: Mapped[float] = mapped_column(Float, nullable=False)
    PlacedWidthCm: Mapped[float] = mapped_column(Float, nullable=False)
    PlacedHeightCm: Mapped[float] = mapped_column(Float, nullable=False)
    RotationState: Mapped[str] = mapped_column(String(20), default="LWH", nullable=False)
    SequenceOrder: Mapped[int] = mapped_column(Integer, nullable=False)
    SourceDevice: Mapped[str] = mapped_column(String(60), default="IoT-RPi-Scanner-01", nullable=False)
    ScannedAt: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    stowage_map: Mapped["StowageMap"] = relationship("StowageMap", back_populates="packages")
