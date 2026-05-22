import os
import psycopg2
import pandas as pd
from dotenv import load_dotenv

# Cargar variables de entorno del archivo .env
load_dotenv()

def obtener_conexion():
    """
    Establece y devuelve la conexión a PostgreSQL (Neon) 
    leyendo las credenciales desde variables de entorno.
    """
    return psycopg2.connect(os.getenv("DATABASE_URL"))

def inicializar_tablas():
    """
    Crea automáticamente las tablas en PostgreSQL si no existen (IF NOT EXISTS).
    """
    conn = obtener_conexion()
    cursor = conn.cursor()
    
    # Tabla Famosos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS famosos (
        nombre VARCHAR(255) PRIMARY KEY,
        fecha_final VARCHAR(255),
        edad INTEGER,
        es_cumpleanos_hoy VARCHAR(10)
    );
    """)

    # Forzar la actualización de la columna en la base de datos por si ya existía con el límite de 20
    cursor.execute("""
    ALTER TABLE famosos ALTER COLUMN fecha_final TYPE VARCHAR(255);
    """)
    
    # Tablas Lugares, Georeferencias y Direcciones (Estructura Relacional)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lugares (
        id INTEGER PRIMARY KEY,
        nombre_lugar VARCHAR(255)
    );
    CREATE TABLE IF NOT EXISTS georeferencias (
        id INTEGER PRIMARY KEY REFERENCES lugares(id),
        latitud VARCHAR(100),
        longitud VARCHAR(100)
    );
    CREATE TABLE IF NOT EXISTS direcciones (
        id INTEGER PRIMARY KEY REFERENCES lugares(id),
        nombre_calle VARCHAR(255),
        numero_calle VARCHAR(100),
        ciudad_estado_provincia VARCHAR(255),
        pais VARCHAR(150)
    );
    """)
    
    conn.commit()
    cursor.close()
    conn.close()

def insertar_datos(tabla, df, columnas, conflict_col):
    """
    Función genérica para insertar datos previniendo duplicados
    (ON CONFLICT DO NOTHING).
    """
    conn = obtener_conexion()
    cursor = conn.cursor()
    
    # Convertimos los 'NaN' de Pandas a 'None' nativos de Python para evitar errores en Psycopg2
    df_limpio = df.where(pd.notnull(df), None)
    
    columnas_str = ", ".join(columnas)
    valores_marcadores = ", ".join(["%s"] * len(columnas))
    
    query = f"""
        INSERT INTO {tabla} ({columnas_str}) 
        VALUES ({valores_marcadores})
        ON CONFLICT ({conflict_col}) DO NOTHING;
    """
    
    for _, fila in df_limpio.iterrows():
        # Extraemos los valores de la fila en el orden de las columnas requeridas
        valores = tuple(fila[col] for col in df.columns if col in columnas or col.lower() in [c.lower() for c in columnas])
        # Debido al mapeo estricto, usamos una comprensión que asegure el orden:
        valores_ordenados = tuple(fila[df.columns[df.columns.str.lower() == col.lower()][0]] for col in columnas)
        cursor.execute(query, valores_ordenados)
        
    conn.commit()
    cursor.close()
    conn.close()