# OptiStack HMI 3D Dashboard

Plataforma de optimización de estiba 3D y control de despacho para transporte de carga.

---

## 🚀 Cómo ejecutar en esta laptop

### Opción 1: Ejecución rápida (Doble clic)
Haz doble clic en el archivo `iniciar.bat` o ejecuta en PowerShell:
```powershell
.\iniciar.ps1
```

### Opción 2: Ejecución manual desde la terminal
```powershell
# 1. Activar el entorno virtual
.\.venv\Scripts\Activate.ps1

# 2. Iniciar el servidor Uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Una vez iniciado, abre tu navegador web en:
👉 **[http://localhost:8000](http://localhost:8000)**
👉 Documentación de la API (Swagger UI): **[http://localhost:8000/docs](http://localhost:8000/docs)**

---

## 🛠️ Ajustes y configuración realizados para esta laptop

1. **Reorganización de estructura**: Se movió el contenido anidado de la carpeta duplicada `optistack/` directamente a la raíz del proyecto.
2. **Entorno Virtual Configurado (`.venv`)**: Se creó el entorno virtual de Python 3.10 y se instalaron todas las dependencias (`FastAPI`, `Uvicorn`, `SQLAlchemy`, `Pydantic`, `OpenPyXL`, `pyodbc`, etc.).
3. **Compatibilidad Windows**: Se ajustó `requirements.txt` para excluir `gunicorn` en Windows (que es exclusivo de entornos Linux) y utilizar directamente `uvicorn`.
4. **Base de Datos Local**: Se inicializó automáticamente la base de datos SQLite (`optistack_local.db`) con el catálogo de camiones, agencias y mapas de estiba de prueba preconfigurados.
