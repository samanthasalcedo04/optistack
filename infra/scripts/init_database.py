"""
Script para inicializar las tablas de Azure SQL Database
utilizando el archivo schema_azure_sql.sql
"""

import sys
import os
from sqlalchemy import create_engine, text

def init_db(connection_string: str, sql_file_path: str):
    print(f"🔗 Conectando a Azure SQL Database...")
    engine = create_engine(connection_string)

    if not os.path.exists(sql_file_path):
        print(f"❌ Error: Archivo SQL no encontrado en {sql_file_path}")
        sys.exit(1)

    with open(sql_file_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    # Separar por 'GO' propio de T-SQL
    statements = [stmt.strip() for stmt in sql_content.split("GO") if stmt.strip()]

    with engine.connect() as conn:
        for idx, stmt in enumerate(statements, start=1):
            try:
                conn.execute(text(stmt))
                conn.commit()
                print(f"✅ Bloque T-SQL {idx}/{len(statements)} ejecutado con éxito.")
            except Exception as e:
                print(f"⚠️ Advertencia en bloque {idx}: {e}")

    print("🎉 Inicialización de Azure SQL Database completada.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python init_database.py <AZURE_SQL_CONNECTION_STRING>")
        sys.exit(1)

    conn_str = sys.argv[1]
    sql_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "sql", "schema_azure_sql.sql"))
    init_db(conn_str, sql_path)
