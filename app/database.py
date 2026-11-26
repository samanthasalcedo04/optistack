from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings


import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings

logger = logging.getLogger("optistack.db")

def create_resilient_engine():
    conn_str = settings.AZURE_SQL_CONNECTION_STRING
    if conn_str and conn_str.startswith("mssql"):
        try:
            eng = create_engine(conn_str, pool_pre_ping=True)
            with eng.connect() as c:
                c.execute(text("SELECT 1"))
            print("✅ Conexión exitosa a Azure SQL Database.")
            return eng
        except Exception as e:
            print(f"⚠️ Error conectando a Azure SQL Database: {e}")
            print("🔄 Activando base de datos local SQLite de respaldo para evitar caída del servidor...")
            return create_engine("sqlite:///./optistack_local.db", connect_args={"check_same_thread": False})

    connect_args = {"check_same_thread": False} if conn_str.startswith("sqlite") else {}
    return create_engine(conn_str, connect_args=connect_args, pool_pre_ping=True)

engine = create_resilient_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Generador de sesión de base de datos para inyección de dependencias en FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
