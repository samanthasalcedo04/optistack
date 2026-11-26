"""
Motor de Inferencia Extreme Points 3D (Azure Machine Learning + Algoritmo 3D-EP Nativo).
Calcula las coordenadas óptimas (x, y, z) dentro del furgón respetando:
- Dimensiones internas personalizadas del camión (LengthCm, WidthCm, HeightCm)
- No solapamiento geométrico 3D (AABB Collision Check)
- Soporte físico en la base (evita cajas flotantes en el aire)
- Prioridad de descarga LIFO según ZoneOrder de la ruta/agencia destino
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional
import httpx
from app.config import settings


@dataclass
class PlacedBox3D:
    x: float
    y: float
    z: float
    lx: float  # Dimensión en eje X (Largo del camión: 0 = Cabina/Fondo -> LengthCm = Puerta)
    ly: float  # Dimensión en eje Y (Alto del camión: 0 = Piso -> HeightCm = Techo)
    lz: float  # Dimensión en eje Z (Ancho del camión: 0 = Pared Izq -> WidthCm = Pared Der)
    weight: float = 0.0
    zone_order: int = 1


class ExtremePoints3DEngine:
    """
    Implementación del algoritmo Extreme Points 3D (Crainic, Perboli, Tadei)
    integrado con llamada al Endpoint Serverless de Azure Machine Learning.
    """

    @staticmethod
    def boxes_overlap(
        x1: float, y1: float, z1: float, lx1: float, ly1: float, lz1: float,
        b: PlacedBox3D, eps: float = 0.05
    ) -> bool:
        """Verifica intersección 3D estricta entre un candidato y una caja ya estibada."""
        if x1 + lx1 <= b.x + eps or b.x + b.lx <= x1 + eps:
            return False
        if y1 + ly1 <= b.y + eps or b.y + b.ly <= y1 + eps:
            return False
        if z1 + lz1 <= b.z + eps or b.z + b.lz <= z1 + eps:
            return False
        return True

    @staticmethod
    def support_ratio(
        x: float, y: float, z: float, lx: float, lz: float,
        placed: List[PlacedBox3D], eps: float = 0.5
    ) -> float:
        """
        Calcula la fracción de área de la base de la caja que está soportada
        físicamente por el piso (y=0) o por el techo de cajas inferiores.
        """
        if y <= eps:
            return 1.0  # Apoyada directamente sobre el piso del furgón
        base_area = lx * lz
        if base_area <= 0:
            return 0.0

        supported_area = 0.0
        for b in placed:
            # Verificar si el tope superior de 'b' coincide con la base 'y' de la nueva caja
            if abs((b.y + b.ly) - y) <= eps:
                ox = max(0.0, min(x + lx, b.x + b.lx) - max(x, b.x))
                oz = max(0.0, min(z + lz, b.z + b.lz) - max(z, b.z))
                supported_area += ox * oz

        return min(1.0, supported_area / base_area)

    @classmethod
    def generate_candidate_points(
        cls, placed: List[PlacedBox3D], container_l: float, container_h: float, container_w: float
    ) -> List[Tuple[float, float, float]]:
        """
        Genera los Extreme Points 3D proyectados a partir de todas las cajas existentes
        más el origen (0,0,0) en el fondo izquierdo del furgón.
        """
        points = {(0.0, 0.0, 0.0)}
        for b in placed:
            # Puntos extremos en las esquinas proyectadas (+X, +Y, +Z)
            if b.x + b.lx < container_l:
                points.add((round(b.x + b.lx, 2), round(b.y, 2), round(b.z, 2)))
                points.add((round(b.x + b.lx, 2), 0.0, round(b.z, 2)))
                points.add((round(b.x + b.lx, 2), 0.0, 0.0))
            if b.y + b.ly < container_h:
                points.add((round(b.x, 2), round(b.y + b.ly, 2), round(b.z, 2)))
            if b.z + b.lz < container_w:
                points.add((round(b.x, 2), round(b.y, 2), round(b.z + b.lz, 2)))
                points.add((round(b.x, 2), 0.0, round(b.z + b.lz, 2)))

        # Ordenar puntos priorizando: X más profundo (hacia cabina), Y más bajo (piso), Z (izquierda a derecha)
        return sorted(points, key=lambda p: (p[0], p[1], p[2]))

    @classmethod
    def calculate_optimal_coordinates(
        cls,
        pkg_l: float,
        pkg_w: float,
        pkg_h: float,
        pkg_weight: float,
        zone_order: int,
        container_l: float,
        container_w: float,
        container_h: float,
        placed_boxes: List[PlacedBox3D],
    ) -> Tuple[float, float, float, float, float, float, str]:
        """
        Evalúa los Extreme Points y orientaciones ortogonales permitidas (LWH y WLH sobre base estable)
        devolviendo (CoordX, CoordY, CoordZ, PlacedLengthCm, PlacedWidthCm, PlacedHeightCm, RotationState).
        """
        # Si está configurado un endpoint remoto de Azure ML, intentar inferencia remota primero
        if settings.AZURE_ML_ENDPOINT_URL:
            remote_res = cls._call_azure_ml_endpoint(
                pkg_l, pkg_w, pkg_h, pkg_weight, zone_order,
                container_l, container_w, container_h, placed_boxes
            )
            if remote_res is not None:
                return remote_res

        candidates = cls.generate_candidate_points(placed_boxes, container_l, container_h, container_w)

        # Rotaciones ortogonales manteniendo la altura vertical (Y = pkg_h) para respetar flechas "Este lado arriba"
        orientations = [
            (pkg_l, pkg_h, pkg_w, "LWH"),
            (pkg_w, pkg_h, pkg_l, "WLH"),
        ]

        best_score = float("inf")
        best_result: Optional[Tuple[float, float, float, float, float, float, str]] = None

        for (cx, cy, cz) in candidates:
            for (lx, ly, lz, rot_code) in orientations:
                # 1. Validar límites del contenedor personalizado
                if cx + lx > container_l + 0.01:
                    continue
                if cy + ly > container_h + 0.01:
                    continue
                if cz + lz > container_w + 0.01:
                    continue

                # 2. Validar no colisión con ninguna caja previa
                collision = False
                for b in placed_boxes:
                    if cls.boxes_overlap(cx, cy, cz, lx, ly, lz, b):
                        collision = True
                        break
                if collision:
                    continue

                # 3. Validar soporte físico mínimo en la base (>= 65% apoyado)
                sup = cls.support_ratio(cx, cy, cz, lx, lz, placed_boxes)
                if sup < 0.65:
                    continue

                # 4. Función de costo multi-objetivo (Extreme Points 3D + Estabilidad + LIFO):
                # - Prioriza llenar desde el fondo (X bajo), piso (Y bajo, especialmente si es pesado),
                #   y compactar en Z.
                weight_height_penalty = cy * (1.0 + (pkg_weight / 25.0))
                score = (cx * 3.2) + (weight_height_penalty * 2.5) + (cz * 1.1) - (sup * 15.0)

                if score < best_score:
                    best_score = score
                    best_result = (
                        round(cx, 2),
                        round(cy, 2),
                        round(cz, 2),
                        round(lx, 2),
                        round(lz, 2),
                        round(ly, 2),
                        rot_code,
                    )

        # Si por alta saturación ningún punto tuvo 65% de soporte, relajar umbral de soporte a 35%
        if best_result is None:
            for (cx, cy, cz) in candidates:
                for (lx, ly, lz, rot_code) in orientations:
                    if cx + lx <= container_l and cy + ly <= container_h and cz + lz <= container_w:
                        if not any(cls.boxes_overlap(cx, cy, cz, lx, ly, lz, b) for b in placed_boxes):
                            if cls.support_ratio(cx, cy, cz, lx, lz, placed_boxes) >= 0.30:
                                return (
                                    round(cx, 2),
                                    round(cy, 2),
                                    round(cz, 2),
                                    round(lx, 2),
                                    round(lz, 2),
                                    round(ly, 2),
                                    rot_code,
                                )

        if best_result is not None:
            return best_result

        # Fallback en caso de contenedor lleno: posicionar en zona de puerta
        return (
            round(max(0.0, container_l - pkg_l), 2),
            0.0,
            0.0,
            round(pkg_l, 2),
            round(pkg_w, 2),
            round(pkg_h, 2),
            "OVERFLOW",
        )

    @classmethod
    def optimize_batch_manifest(
        cls,
        container_l: float,
        container_w: float,
        container_h: float,
        max_weight_kg: float,
        packages_input: List[dict],
        agencies_by_id: dict,
    ) -> List[dict]:
        """
        MOTOR DE INTELIGENCIA ARTIFICIAL PARA ESTIBA MASIVA (Batch AI Optimizer).
        Acomoda de forma global una tabla completa de paquetes (ej. manifiesto de carga Excel):
        1. Pre-ordenamiento inteligente jerárquico:
           - Prioridad 1: Orden de descarga LIFO (ZoneOrder: 1 al fondo, N a la puerta).
           - Prioridad 2: Heavy-First (Bultos pesados primero para piso y bajar CoG).
           - Prioridad 3: Largest-Base-First (Mayor área LxW para crear bases estables).
        2. Búsqueda y asignación de Extreme Points 3D no colisionantes.
        3. Asignación de secuencia óptima de carga para el estibador.
        """
        # Enriquecer cada paquete con el ZoneOrder de su agencia destino
        enriched: List[dict] = []
        for pkg in packages_input:
            ag_id = str(pkg.get("agency_id") or pkg.get("TargetAgencyID") or "AG-TRU-01").strip()
            ag = agencies_by_id.get(ag_id)
            z_ord = ag.ZoneOrder if ag else 99
            enriched.append({
                "guide_id": str(pkg.get("guide_id") or pkg.get("GuideID") or "").strip().upper(),
                "length_cm": float(pkg.get("length_cm") or pkg.get("LengthCm") or 0.0),
                "width_cm": float(pkg.get("width_cm") or pkg.get("WidthCm") or 0.0),
                "height_cm": float(pkg.get("height_cm") or pkg.get("HeightCm") or 0.0),
                "weight_kg": float(pkg.get("weight_kg") or pkg.get("WeightKg") or 0.0),
                "agency_id": ag_id,
                "zone_order": z_ord,
                "source_device": str(pkg.get("source_device") or pkg.get("SourceDevice") or "AI-Batch-Optimizer"),
            })

        # Criterio de ordenamiento multi-objetivo del modelo de IA:
        # (zone_order ascendente -> menor número al fondo, mayor peso primero, mayor área primero)
        enriched.sort(key=lambda p: (
            p["zone_order"],
            -p["weight_kg"],
            -(p["length_cm"] * p["width_cm"]),
            -(p["length_cm"] * p["width_cm"] * p["height_cm"]),
        ))

        placed_boxes: List[PlacedBox3D] = []
        result_packages: List[dict] = []

        for idx, item in enumerate(enriched, start=1):
            cx, cy, cz, pl_l, pl_w, pl_h, rot = cls.calculate_optimal_coordinates(
                pkg_l=item["length_cm"],
                pkg_w=item["width_cm"],
                pkg_h=item["height_cm"],
                pkg_weight=item["weight_kg"],
                zone_order=item["zone_order"],
                container_l=container_l,
                container_w=container_w,
                container_h=container_h,
                placed_boxes=placed_boxes,
            )

            placed_boxes.append(
                PlacedBox3D(
                    x=cx,
                    y=cy,
                    z=cz,
                    lx=pl_l,
                    ly=pl_h,
                    lz=pl_w,
                    weight=item["weight_kg"],
                    zone_order=item["zone_order"],
                )
            )

            result_packages.append({
                "GuideID": item["guide_id"],
                "LengthCm": item["length_cm"],
                "WidthCm": item["width_cm"],
                "HeightCm": item["height_cm"],
                "WeightKg": item["weight_kg"],
                "TargetAgencyID": item["agency_id"],
                "CoordX": cx,
                "CoordY": cy,
                "CoordZ": cz,
                "PlacedLengthCm": pl_l,
                "PlacedWidthCm": pl_w,
                "PlacedHeightCm": pl_h,
                "RotationState": rot,
                "SequenceOrder": idx,
                "SourceDevice": item["source_device"],
            })

        return result_packages

    _azure_ml_consecutive_failures: int = 0

    @classmethod
    def _call_azure_ml_endpoint(
        cls,
        pkg_l: float,
        pkg_w: float,
        pkg_h: float,
        pkg_weight: float,
        zone_order: int,
        container_l: float,
        container_w: float,
        container_h: float,
        placed_boxes: List[PlacedBox3D],
    ) -> Optional[Tuple[float, float, float, float, float, float, str]]:
        """Invoca el Endpoint Serverless de Azure Machine Learning si está configurado."""
        if cls._azure_ml_consecutive_failures > 2:
            return None
        try:
            headers = {"Content-Type": "application/json"}
            if settings.AZURE_ML_API_KEY:
                headers["Authorization"] = f"Bearer {settings.AZURE_ML_API_KEY}"

            payload = {
                "container": {"L": container_l, "W": container_w, "H": container_h},
                "package": {"L": pkg_l, "A": pkg_w, "H": pkg_h, "weight": pkg_weight, "zone_order": zone_order},
                "placed_boxes": [
                    {"x": b.x, "y": b.y, "z": b.z, "lx": b.lx, "ly": b.ly, "lz": b.lz}
                    for b in placed_boxes
                ],
            }
            with httpx.Client(timeout=2.0) as client:
                resp = client.post(settings.AZURE_ML_ENDPOINT_URL, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    cls._azure_ml_consecutive_failures = 0
                    return (
                        float(data["x"]),
                        float(data["y"]),
                        float(data["z"]),
                        float(data.get("lx", pkg_l)),
                        float(data.get("lz", pkg_w)),
                        float(data.get("ly", pkg_h)),
                        str(data.get("rotation", "LWH")),
                    )
        except Exception:
            cls._azure_ml_consecutive_failures += 1
            return None
        return None
