import os
from dataclasses import dataclass


@dataclass
class Settings:
    """Configuración central para Azure App Service, Azure SQL Database y Azure ML."""

    APP_TITLE: str = "OptiStack HMI 3D Dashboard - Azure Cloud"
    APP_VERSION: str = "1.0.0"

    # Cadena de conexión SQLAlchemy para Azure SQL Database:
    # Ejemplo en Azure App Service Configuration:
    # mssql+pyodbc://usuario:password@servidor.database.windows.net:1433/OptiStackDB?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no
    AZURE_SQL_CONNECTION_STRING: str = os.getenv(
        "AZURE_SQL_CONNECTION_STRING",
        "sqlite:///./optistack_local.db",
    )

    # Endpoint de inferencia en Azure Machine Learning (Extreme Points 3D)
    AZURE_ML_ENDPOINT_URL: str = os.getenv("AZURE_ML_ENDPOINT_URL", "")
    AZURE_ML_API_KEY: str = os.getenv("AZURE_ML_API_KEY", "")

    # Nombre del Hub IoT informativo para la cabecera de telemetría
    AZURE_IOT_HUB_NAME: str = os.getenv("AZURE_IOT_HUB_NAME", "iothub-optistack-prod.azure-devices.net")

    @property
    def is_azure_sql(self) -> bool:
        return self.AZURE_SQL_CONNECTION_STRING.startswith("mssql")


settings = Settings()
