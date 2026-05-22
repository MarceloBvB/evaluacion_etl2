import streamlit as st
import pandas as pd
import io
import re
from logica_famosos import procesar_famosos
from logica_lugares import procesar_lugares
from conexion_db import inicializar_tablas, insertar_datos

# Funciones auxiliares para automatizar la subida a DB durante la descarga
def db_upload_lugares(df_l, df_g, df_d):
    try:
        inicializar_tablas()
        insertar_datos("lugares", df_l, ["id", "nombre_lugar"], "id")
        insertar_datos("georeferencias", df_g, ["id", "latitud", "longitud"], "id")
        insertar_datos("direcciones", df_d, ["ID", "nombre_calle", "numero_calle", "ciudad_estado_provincia", "pais"], "id")
        st.toast("✅ ¡Datos guardados en Neon automáticamente!", icon="🚀")
    except Exception as e:
        st.error(f"Error de base de datos: {e}")

def db_upload_famosos(df_f):
    try:
        inicializar_tablas()
        insertar_datos("famosos", df_f, ["Nombre", "Fecha_Final", "Edad", "Es_Cumpleanos_Hoy"], "nombre")
        st.toast("✅ ¡Famosos guardados en Neon automáticamente!", icon="🚀")
    except Exception as e:
        st.error(f"Error de base de datos: {e}")

# Configuración de la página
st.set_page_config(page_title="Procesador Universal ETL", layout="wide")

st.title("Evaluacion 2 Parte 2 - ETL")
st.subheader("Sube cualquier dataset")
st.markdown("---")

st.write("Coloca aquí tu archivo `.TXT`.")

# ÚNICO BOTÓN DE SUBIDA
archivo_subido = st.file_uploader("Arrastra o selecciona tu archivo de datos (.TXT)", type=["txt"])

st.markdown("---")
export_format = st.radio("Selecciona tu formato preferido para exportar los datos limpios:", ["CSV (Texto plano)", "Excel (XLSX)"], horizontal=True)

if archivo_subido is not None:
    st.info("Detectando estructura del archivo...")
    
    try:
        # Extraemos el contenido completo sin depender de los punteros
        contenido_bytes = archivo_subido.getvalue()
        try:
            texto_completo = contenido_bytes.decode('utf-8-sig')
        except UnicodeDecodeError:
            texto_completo = contenido_bytes.decode('latin-1')
            
        # Limpiamos líneas completamente vacías para evitar errores 'No columns to parse'
        lineas_limpias = [linea.strip('\ufeff').strip() for linea in texto_completo.splitlines() if linea.strip()]
        
        # Reconstruimos el archivo en un buffer de memoria limpio
        archivo_limpio = io.BytesIO(('\n'.join(lineas_limpias)).encode('utf-8'))

        # Tomamos las primeras 3 líneas para la inspección
        primeras_3_lineas = "\n".join(lineas_limpias[:3])

        # NUEVA REGLA DE DETECCIÓN AUTOMÁTICA INFALIBLE
        es_lugares = False
        if ';' in primeras_3_lineas:
            es_lugares = True

        if es_lugares:
            st.success("¡Dataset de UBICACIONES detectado automáticamente!")
            
            with st.spinner("Ejecutando ETL de normalización en 3 tablas..."):
                df_lugares, df_geo, df_dir = procesar_lugares(archivo_limpio)
                
            st.markdown("### Resultado de la Normalización Relacional")
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### 1. Tabla: Lugares")
                st.dataframe(df_lugares, use_container_width=True)
            with col2:
                st.markdown("#### 2. Tabla: Georeferencias")
                st.dataframe(df_geo, use_container_width=True)
                
            st.markdown("#### 3. Tabla: Direcciones (Estructura Estricta)")
            st.dataframe(df_dir, use_container_width=True)
            
            st.markdown("---")
            st.markdown("### 💾 Exportación de Datos")
            st.caption("Al descargar tus archivos, la base de datos se actualizará automáticamente.")
            
            if "CSV" in export_format:
                if st.download_button("Descargar Lugares (CSV)", df_lugares.to_csv(index=False).encode('utf-8'), "lugares.csv", "text/csv"):
                    db_upload_lugares(df_lugares, df_geo, df_dir)
                if st.download_button("Descargar Georeferencias (CSV)", df_geo.to_csv(index=False).encode('utf-8'), "geo.csv", "text/csv"):
                    db_upload_lugares(df_lugares, df_geo, df_dir)
                if st.download_button("Descargar Direcciones (CSV)", df_dir.to_csv(index=False).encode('utf-8'), "direcciones.csv", "text/csv"):
                    db_upload_lugares(df_lugares, df_geo, df_dir)
            else:
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_lugares.to_excel(writer, sheet_name="Lugares", index=False)
                    df_geo.to_excel(writer, sheet_name="Georeferencias", index=False)
                    df_dir.to_excel(writer, sheet_name="Direcciones", index=False)
                if st.download_button("Descargar Todo en Excel", buffer.getvalue(), "Dataset_Lugares_Limpio.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
                    db_upload_lugares(df_lugares, df_geo, df_dir)
            
        else:
            # Si no contiene elementos de dirección, ejecutamos la lógica de Famosos
            st.success("¡Dataset de FAMOSOS detectado automáticamente!")
            
            with st.spinner("Ejecutando ETL de Limpieza, Edades y Cumpleaños..."):
                df_famosos = procesar_famosos(archivo_limpio)
                
            st.markdown("### Resultado del Dataset de Famosos")
            st.dataframe(df_famosos, use_container_width=True)
            
            st.markdown("---")
            st.markdown("### 💾 Exportación de Datos")
            st.caption("Al descargar tu archivo, la base de datos se actualizará automáticamente.")
            
            if "CSV" in export_format:
                if st.download_button("Descargar Famosos (CSV)", df_famosos.to_csv(index=False).encode('utf-8'), "famosos.csv", "text/csv"):
                    db_upload_famosos(df_famosos)
            else:
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_famosos.to_excel(writer, index=False)
                if st.download_button("Descargar Famosos (Excel)", buffer.getvalue(), "Dataset_Famosos_Limpio.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
                    db_upload_famosos(df_famosos)

    except Exception as e:
        st.error(f"Ocurrió un error al procesar el archivo de forma automática: {e}")