"""
Servicio de Carga Masiva y Generación de Plantilla Excel (.xlsx) para el Catálogo
CRUD de Rutas / Agencias Destino (AgencyMaster).
"""

from io import BytesIO
from typing import List, Tuple
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from sqlalchemy.orm import Session
from app.models import AgencyMaster
from app.schemas import ExcelBulkImportResult


DEFAULT_PALETTE = [
    "#38BDF8",  # Sky Blue
    "#10B981",  # Emerald
    "#F59E0B",  # Amber
    "#A855F7",  # Purple
    "#EC4899",  # Pink
    "#06B6D4",  # Cyan
    "#F97316",  # Orange
    "#84CC16",  # Lime
]


def generate_routes_excel_template() -> bytes:
    """
    Genera un archivo Excel (.xlsx) con formato profesional e instrucciones
    para la carga masiva del catálogo de Rutas / Agencias Destino.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Catalogo_Rutas"

    headers = [
        "CodigoAgencia",
        "NombreAgencia",
        "CodigoRuta",
        "OrdenDescargaLIFO",
        "Ciudad",
        "ColorHex",
    ]
    ws.append(headers)

    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="38BDF8")
    thin_border = Border(
        left=Side(style="thin", color="334155"),
        right=Side(style="thin", color="334155"),
        top=Side(style="thin", color="334155"),
        bottom=Side(style="thin", color="334155"),
    )

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    sample_rows = [
        ["AG-TRU-01", "Agencia Trujillo Norte", "RUTA-NORTE-01", 1, "Trujillo", "#38BDF8"],
        ["AG-CHI-02", "Agencia Chiclayo Central", "RUTA-NORTE-01", 2, "Chiclayo", "#10B981"],
        ["AG-PIU-03", "Agencia Piura Industrial", "RUTA-NORTE-01", 3, "Piura", "#F59E0B"],
        ["AG-CAJ-04", "Agencia Cajamarca Express", "RUTA-SIERRA-02", 4, "Cajamarca", "#A855F7"],
        ["AG-ARE-05", "Agencia Arequipa Sur", "RUTA-SUR-01", 5, "Arequipa", "#EC4899"],
        ["AG-CUS-06", "Agencia Cusco Principal", "RUTA-SUR-01", 6, "Cusco", "#06B6D4"],
    ]

    for row_data in sample_rows:
        ws.append(row_data)

    for row in ws.iter_rows(min_row=2, max_row=len(sample_rows) + 1, min_col=1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")

    col_widths = [18, 28, 20, 20, 18, 14]
    for idx, width in enumerate(col_widths, start=1):
        col_letter = openpyxl.utils.get_column_letter(idx)
        ws.column_dimensions[col_letter].width = width

    # Segunda pestaña con guía de llenado
    ws_info = wb.create_sheet(title="Instrucciones")
    ws_info.append(["Campo", "Obligatorio", "Descripción"])
    ws_info.append(["CodigoAgencia", "SÍ", "Identificador único de la agencia o destino (ej. AG-TRU-01)"])
    ws_info.append(["NombreAgencia", "SÍ", "Nombre descriptivo de la agencia o punto de entrega"])
    ws_info.append(["CodigoRuta", "SÍ", "Código del corredor o ruta logística (ej. RUTA-NORTE-01)"])
    ws_info.append([
        "OrdenDescargaLIFO",
        "SÍ",
        "Prioridad de estiba (1 = Última parada/Fondo del camión, Mayor = Primera parada/Puerta)",
    ])
    ws_info.append(["Ciudad", "NO", "Ciudad o provincia de destino"])
    ws_info.append(["ColorHex", "NO", "Color en formato hexadecimal (#RRGGBB) para el modelo 3D"])

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def process_routes_excel_upload(file_bytes: bytes, db: Session) -> ExcelBulkImportResult:
    """
    Lee un archivo Excel (.xlsx), valida cada fila y realiza Upsert masivo
    (Inserta nuevas rutas o actualiza existentes por CodigoAgencia) en AgencyMaster.
    """
    wb = openpyxl.load_workbook(filename=BytesIO(file_bytes), data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows or len(rows) < 2:
        return ExcelBulkImportResult(
            total_rows_read=0,
            inserted_count=0,
            updated_count=0,
            skipped_count=0,
            errors=["El archivo Excel no contiene filas de datos debajo del encabezado."],
        )

    # Mapear encabezados de manera flexible (sin importar mayúsculas, tildes o espacios)
    raw_headers = [str(h or "").strip().lower().replace(" ", "").replace("_", "") for h in rows[0]]

    def find_col(possible_names: List[str], default_idx: int) -> int:
        for idx, h in enumerate(raw_headers):
            for name in possible_names:
                if name in h:
                    return idx
        return default_idx

    idx_id = find_col(["codigoagencia", "agencyid", "id", "codigo"], 0)
    idx_name = find_col(["nombreagencia", "agencyname", "nombre", "agencia", "destino"], 1)
    idx_route = find_col(["codigoruta", "routecode", "ruta", "corredor"], 2)
    idx_zone = find_col(["ordendescarga", "zoneorder", "orden", "lifo", "prioridad"], 3)
    idx_city = find_col(["ciudad", "city", "provincia", "ubicacion"], 4)
    idx_color = find_col(["color", "colorhex", "hex"], 5)

    inserted = 0
    updated = 0
    skipped = 0
    errors: List[str] = []
    total_read = 0

    for row_num, row in enumerate(rows[1:], start=2):
        if not row or all(cell is None or str(cell).strip() == "" for cell in row):
            continue

        total_read += 1
        try:
            agency_id = str(row[idx_id] if idx_id < len(row) and row[idx_id] is not None else "").strip().upper()
            agency_name = str(row[idx_name] if idx_name < len(row) and row[idx_name] is not None else "").strip()
            route_code = str(row[idx_route] if idx_route < len(row) and row[idx_route] is not None else "").strip().upper()

            if not agency_id or not agency_name:
                skipped += 1
                errors.append(f"Fila {row_num}: 'CodigoAgencia' y 'NombreAgencia' son obligatorios.")
                continue

            if not route_code:
                route_code = "RUTA-GEN"

            raw_zone = row[idx_zone] if idx_zone < len(row) else 1
            try:
                zone_order = max(1, min(99, int(float(str(raw_zone).strip()))))
            except Exception:
                zone_order = 1

            city = ""
            if idx_city < len(row) and row[idx_city] is not None:
                city = str(row[idx_city]).strip()

            color_hex = DEFAULT_PALETTE[(total_read - 1) % len(DEFAULT_PALETTE)]
            if idx_color < len(row) and row[idx_color] is not None:
                candidate_color = str(row[idx_color]).strip()
                if not candidate_color.startswith("#") and len(candidate_color) == 6:
                    candidate_color = "#" + candidate_color
                if len(candidate_color) == 7 and candidate_color.startswith("#"):
                    color_hex = candidate_color.upper()

            existing = db.query(AgencyMaster).filter(AgencyMaster.AgencyID == agency_id).first()
            if existing:
                existing.AgencyName = agency_name
                existing.RouteCode = route_code
                existing.ZoneOrder = zone_order
                existing.City = city
                existing.ColorHex = color_hex
                existing.IsActive = True
                updated += 1
            else:
                new_agency = AgencyMaster(
                    AgencyID=agency_id,
                    AgencyName=agency_name,
                    RouteCode=route_code,
                    ZoneOrder=zone_order,
                    City=city,
                    ColorHex=color_hex,
                    IsActive=True,
                )
                db.add(new_agency)
                inserted += 1

        except Exception as exc:
            skipped += 1
            errors.append(f"Fila {row_num}: Error de formato ({str(exc)})")

    db.commit()
    return ExcelBulkImportResult(
        total_rows_read=total_read,
        inserted_count=inserted,
        updated_count=updated,
        skipped_count=skipped,
        errors=errors,
    )


def generate_packages_excel_template() -> bytes:
    """
    Genera una plantilla Excel (.xlsx) para la carga masiva de paquetes / manifiesto de carga
    que el Modelo de IA acomodará automáticamente en el camión 3D.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Manifiesto_Paquetes"

    headers = [
        "GuideID",
        "LargoCm",
        "AnchoCm",
        "AltoCm",
        "PesoKg",
        "CodigoAgencia",
        "Notas",
    ]
    ws.append(headers)

    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="10B981")
    thin_border = Border(
        left=Side(style="thin", color="334155"),
        right=Side(style="thin", color="334155"),
        top=Side(style="thin", color="334155"),
        bottom=Side(style="thin", color="334155"),
    )

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    sample_pkgs = [
        ["GUIA-TRU-1001", 80.0, 60.0, 55.0, 35.0, "AG-TRU-01", "Carga pesada industrial"],
        ["GUIA-TRU-1002", 75.0, 55.0, 50.0, 28.0, "AG-TRU-01", "Cajas de repuestos"],
        ["GUIA-TRU-1003", 60.0, 45.0, 40.0, 15.5, "AG-TRU-01", "Mercadería general"],
        ["GUIA-CHI-2001", 85.0, 65.0, 60.0, 42.0, "AG-CHI-02", "Maquinaria compacta"],
        ["GUIA-CHI-2002", 70.0, 50.0, 45.0, 22.0, "AG-CHI-02", "Insumos médicos"],
        ["GUIA-PIU-3001", 65.0, 50.0, 45.0, 18.0, "AG-PIU-03", "Paquetería express"],
        ["GUIA-PIU-3002", 50.0, 40.0, 35.0, 10.0, "AG-PIU-03", "Caja ligera"],
        ["GUIA-CAJ-4001", 75.0, 50.0, 40.0, 25.0, "AG-CAJ-04", "Herramientas"],
    ]

    for row_data in sample_pkgs:
        ws.append(row_data)

    for row in ws.iter_rows(min_row=2, max_row=len(sample_pkgs) + 1, min_col=1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")

    col_widths = [20, 14, 14, 14, 14, 20, 28]
    for idx, width in enumerate(col_widths, start=1):
        col_letter = openpyxl.utils.get_column_letter(idx)
        ws.column_dimensions[col_letter].width = width

    ws_info = wb.create_sheet(title="Instrucciones_IA")
    ws_info.append(["Campo", "Obligatorio", "Descripción"])
    ws_info.append(["GuideID", "SÍ", "Código único de guía o bulto (ej. GUIA-TRU-1001)"])
    ws_info.append(["LargoCm", "SÍ", "Dimensión de largo en centímetros"])
    ws_info.append(["AnchoCm", "SÍ", "Dimensión de ancho en centímetros"])
    ws_info.append(["AltoCm", "SÍ", "Dimensión de alto en centímetros"])
    ws_info.append(["PesoKg", "SÍ", "Peso neto en kilogramos (usado por la IA para cálculo de CoG y base pesada)"])
    ws_info.append(["CodigoAgencia", "SÍ", "Código de la agencia/ruta de destino (debe existir en el CRUD de Rutas)"])
    ws_info.append(["Notas", "NO", "Observaciones del paquete"])

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def parse_packages_from_excel(file_bytes: bytes) -> List[dict]:
    """
    Lee un archivo Excel de manifiesto de carga y retorna una lista de paquetes
    listos para ser procesados por el Optimizador de IA Extreme Points 3D.
    """
    wb = openpyxl.load_workbook(filename=BytesIO(file_bytes), data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows or len(rows) < 2:
        return []

    raw_headers = [str(h or "").strip().lower().replace(" ", "").replace("_", "") for h in rows[0]]

    def find_col(possible_names: List[str], default_idx: int) -> int:
        for idx, h in enumerate(raw_headers):
            for name in possible_names:
                if name in h:
                    return idx
        return default_idx

    idx_guide = find_col(["guideid", "guia", "codigo", "tracking", "id"], 0)
    idx_l = find_col(["largocm", "largo", "length", "l"], 1)
    idx_w = find_col(["anchocm", "ancho", "width", "w", "a"], 2)
    idx_h = find_col(["altocm", "alto", "height", "h"], 3)
    idx_weight = find_col(["pesokg", "peso", "weight", "kg"], 4)
    idx_agency = find_col(["codigoagencia", "agencia", "agency", "destino", "ruta"], 5)

    packages: List[dict] = []
    for row_num, row in enumerate(rows[1:], start=2):
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue

        try:
            guide_id = str(row[idx_guide] if idx_guide < len(row) and row[idx_guide] is not None else f"PKG-{row_num}").strip().upper()
            l_val = float(str(row[idx_l]).strip()) if idx_l < len(row) and row[idx_l] is not None else 0.0
            w_val = float(str(row[idx_w]).strip()) if idx_w < len(row) and row[idx_w] is not None else 0.0
            h_val = float(str(row[idx_h]).strip()) if idx_h < len(row) and row[idx_h] is not None else 0.0
            wt_val = float(str(row[idx_weight]).strip()) if idx_weight < len(row) and row[idx_weight] is not None else 0.0
            ag_id = str(row[idx_agency] if idx_agency < len(row) and row[idx_agency] is not None else "AG-TRU-01").strip().upper()

            if l_val > 0 and w_val > 0 and h_val > 0 and wt_val > 0:
                packages.append({
                    "guide_id": guide_id,
                    "length_cm": l_val,
                    "width_cm": w_val,
                    "height_cm": h_val,
                    "weight_kg": wt_val,
                    "agency_id": ag_id,
                })
        except Exception:
            continue

    return packages

