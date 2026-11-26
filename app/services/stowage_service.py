"""
Servicio de Cálculo de KPIs de Estiba, Ocupación Volumétrica, Distribución por Agencia
y Monitor de Centro de Gravedad (CoG) según normas de seguridad de transporte.
"""

from typing import Dict, List
from app.models import StowageMap, PackageData, AgencyMaster
from app.schemas import StowageKPIs, PackageOut, StowageMapFullOut


def build_stowage_map_response(
    stowage_map: StowageMap,
    agencies_by_id: Dict[str, AgencyMaster],
) -> StowageMapFullOut:
    """Construye la respuesta enriquecida del Mapa de Estiba con KPIs en tiempo real."""
    container_vol_m3 = (stowage_map.LengthCm * stowage_map.WidthCm * stowage_map.HeightCm) / 1_000_000.0
    container_vol_m3 = max(container_vol_m3, 0.001)

    total_weight_kg = 0.0
    occupied_vol_m3 = 0.0

    # Momentos estáticos para cálculo de Centro de Gravedad (CoG)
    moment_x = 0.0
    moment_y = 0.0
    moment_z = 0.0

    agency_stats: Dict[str, dict] = {}
    packages_out: List[PackageOut] = []

    for pkg in stowage_map.packages:
        ag = agencies_by_id.get(pkg.TargetAgencyID)
        ag_name = ag.AgencyName if ag else pkg.TargetAgencyID
        ag_route = ag.RouteCode if ag else "SIN-RUTA"
        ag_zone = ag.ZoneOrder if ag else 1
        ag_color = ag.ColorHex if ag else "#38BDF8"

        pkg_vol_m3 = (pkg.LengthCm * pkg.WidthCm * pkg.HeightCm) / 1_000_000.0
        occupied_vol_m3 += pkg_vol_m3
        total_weight_kg += pkg.WeightKg

        # Centro geométrico de la caja colocada
        center_x = pkg.CoordX + (pkg.PlacedLengthCm / 2.0)
        center_y = pkg.CoordY + (pkg.PlacedHeightCm / 2.0)
        center_z = pkg.CoordZ + (pkg.PlacedWidthCm / 2.0)

        moment_x += pkg.WeightKg * center_x
        moment_y += pkg.WeightKg * center_y
        moment_z += pkg.WeightKg * center_z

        if pkg.TargetAgencyID not in agency_stats:
            agency_stats[pkg.TargetAgencyID] = {
                "AgencyID": pkg.TargetAgencyID,
                "AgencyName": ag_name,
                "RouteCode": ag_route,
                "ZoneOrder": ag_zone,
                "ColorHex": ag_color,
                "package_count": 0,
                "total_weight_kg": 0.0,
                "total_volume_m3": 0.0,
            }

        agency_stats[pkg.TargetAgencyID]["package_count"] += 1
        agency_stats[pkg.TargetAgencyID]["total_weight_kg"] = round(
            agency_stats[pkg.TargetAgencyID]["total_weight_kg"] + pkg.WeightKg, 2
        )
        agency_stats[pkg.TargetAgencyID]["total_volume_m3"] = round(
            agency_stats[pkg.TargetAgencyID]["total_volume_m3"] + pkg_vol_m3, 3
        )

        packages_out.append(
            PackageOut(
                PackageID=pkg.PackageID,
                GuideID=pkg.GuideID,
                StowageMapID=pkg.StowageMapID,
                LengthCm=pkg.LengthCm,
                WidthCm=pkg.WidthCm,
                HeightCm=pkg.HeightCm,
                WeightKg=pkg.WeightKg,
                TargetAgencyID=pkg.TargetAgencyID,
                AgencyName=ag_name,
                RouteCode=ag_route,
                ZoneOrder=ag_zone,
                ColorHex=ag_color,
                CoordX=pkg.CoordX,
                CoordY=pkg.CoordY,
                CoordZ=pkg.CoordZ,
                PlacedLengthCm=pkg.PlacedLengthCm,
                PlacedWidthCm=pkg.PlacedWidthCm,
                PlacedHeightCm=pkg.PlacedHeightCm,
                RotationState=pkg.RotationState,
                SequenceOrder=pkg.SequenceOrder,
                SourceDevice=pkg.SourceDevice,
                ScannedAt=pkg.ScannedAt,
            )
        )

    if total_weight_kg > 0:
        cog_x = moment_x / total_weight_kg
        cog_y = moment_y / total_weight_kg
        cog_z = moment_z / total_weight_kg
    else:
        cog_x = stowage_map.LengthCm / 2.0
        cog_y = 0.0
        cog_z = stowage_map.WidthCm / 2.0

    # Desviaciones porcentuales respecto al centro ideal del furgón
    cog_x_offset_pct = ((cog_x - (stowage_map.LengthCm / 2.0)) / max(stowage_map.LengthCm, 1.0)) * 100.0
    cog_z_offset_pct = ((cog_z - (stowage_map.WidthCm / 2.0)) / max(stowage_map.WidthCm, 1.0)) * 100.0

    vol_pct = min(100.0, (occupied_vol_m3 / container_vol_m3) * 100.0)
    weight_pct = (total_weight_kg / max(stowage_map.MaxWeightKg, 1.0)) * 100.0

    # Evaluación de estabilidad según ISA-101 (OPTIMAL, WARNING, CRITICAL)
    stability = "OPTIMAL"
    if weight_pct > 100.0 or abs(cog_z_offset_pct) > 18.0 or cog_y > (stowage_map.HeightCm * 0.62):
        stability = "CRITICAL"
    elif weight_pct > 90.0 or abs(cog_z_offset_pct) > 10.0 or cog_y > (stowage_map.HeightCm * 0.50):
        stability = "WARNING"

    breakdown_list = sorted(
        agency_stats.values(),
        key=lambda item: item["ZoneOrder"],
    )

    kpis = StowageKPIs(
        total_packages=len(packages_out),
        occupied_volume_m3=round(occupied_vol_m3, 3),
        container_volume_m3=round(container_vol_m3, 3),
        volume_utilization_pct=round(vol_pct, 1),
        total_weight_kg=round(total_weight_kg, 2),
        max_weight_kg=round(stowage_map.MaxWeightKg, 2),
        weight_utilization_pct=round(weight_pct, 1),
        cog_x_cm=round(cog_x, 1),
        cog_y_cm=round(cog_y, 1),
        cog_z_cm=round(cog_z, 1),
        cog_x_Offset_pct=round(cog_x_offset_pct, 1),
        cog_z_Offset_pct=round(cog_z_offset_pct, 1),
        stability_status=stability,
        agency_breakdown=breakdown_list,
    )

    return StowageMapFullOut(
        StowageMapID=stowage_map.StowageMapID,
        MapCode=stowage_map.MapCode,
        TruckID=stowage_map.TruckID,
        TruckPlate=stowage_map.TruckPlate,
        TruckName=stowage_map.TruckName,
        RouteSummary=stowage_map.RouteSummary,
        LengthCm=stowage_map.LengthCm,
        WidthCm=stowage_map.WidthCm,
        HeightCm=stowage_map.HeightCm,
        MaxWeightKg=stowage_map.MaxWeightKg,
        Status=stowage_map.Status,
        CreatedAt=stowage_map.CreatedAt,
        packages=packages_out,
        kpis=kpis,
    )
