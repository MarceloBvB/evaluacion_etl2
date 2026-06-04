import streamlit as st
import pandas as pd
import psycopg2
import psycopg2.extras
from datetime import datetime
import requests
import pydeck as pdk
import re
import unicodedata
import os
from dotenv import load_dotenv
from logica_famosos import procesar_famosos
from logica_lugares import procesar_lugares

# ==========================================
# 1. ESTILO Y MAQUETACIÓN INICIAL
# ==========================================
st.set_page_config(page_title="Gestor Corporativo de Datos", layout="wide", page_icon="⚙️")

# Estilos CSS personalizados e integración de un Encabezado Elegante
st.markdown("""
    <style>
    .header-card {
        text-align: center; 
        padding: 20px; 
        background-color: #f0f2f6; 
        border-radius: 10px; 
        margin-bottom: 25px;
        border-left: 5px solid #1f77b4;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .header-card h1 {
        color: #1f77b4;
        margin-bottom: 5px;
        font-weight: 700;
    }
    .header-card h4 {
        color: #555555;
        font-weight: 400;
    }
    .section-header {
        margin-top: 40px;
        margin-bottom: 20px;
        color: #2c3e50;
        border-bottom: 2px solid #e0e0e0;
        padding-bottom: 10px;
    }
    </style>
    <div class="header-card">
        <h1>🌐 Plataforma ETL y Análisis Avanzado</h1>
        <h4>Consolidación de Datos, Caché de APIs y Geolocalización 3D</h4>
    </div>
""", unsafe_allow_html=True)

# ==========================================
# 2. CONSTANTES Y CONEXIONES (ROBUSTEZ)
# ==========================================
def get_db_connection():
    """Establece conexión de manera segura usando variables secretas de Streamlit o .env local."""
    try:
        db_url = None
        try:
            db_url = st.secrets["DATABASE_URL"]
        except (FileNotFoundError, KeyError):
            load_dotenv()
            db_url = os.getenv("DATABASE_URL")
            
        if not db_url:
            raise ValueError("No se encontró DATABASE_URL en secrets.toml ni en el archivo .env")
            
        return psycopg2.connect(db_url)
    except Exception as e:
        st.error(f"Error crítico: No se pudo conectar a la Base de Datos. Verifica st.secrets o tu archivo .env. Detalles: {e}")
        return None

def inicializar_tablas():
    """Valida y crea automáticamente la estructura de la base de datos (PostgreSQL/Neon)."""
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                # Tablas de Comunas y Auditoría
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS comunas_consolidadas (
                        nombre_comuna VARCHAR(255) PRIMARY KEY,
                        region VARCHAR(255),
                        habitantes INTEGER,
                        actualizado_en TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS auditoria (
                        id SERIAL PRIMARY KEY,
                        fecha_ejecucion TIMESTAMP,
                        registros_leidos INTEGER,
                        comunas_procesadas INTEGER,
                        duplicados_eliminados INTEGER,
                        consolidados_correctamente INTEGER,
                        no_encontrados INTEGER,
                        errores TEXT
                    );
                """)
                # Tabla Caché para las consultas a la API de Wikipedia
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS famosos_cache (
                        nombre VARCHAR(255) PRIMARY KEY,
                        imagen_url TEXT,
                        fecha_captura TIMESTAMP
                    );
                """)
                # Tablas de Lugares para el Mapa Interactivo
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS lugares (
                        id INTEGER PRIMARY KEY,
                        nombre_lugar VARCHAR(255)
                    );
                    CREATE TABLE IF NOT EXISTS georeferencias (
                        id INTEGER PRIMARY KEY REFERENCES lugares(id),
                        latitud VARCHAR(100),
                        longitud VARCHAR(100)
                    );
                """)
                conn.commit()
        except Exception as e:
            st.error(f"Error al inicializar las tablas de base de datos: {e}")
        finally:
            conn.close()

# Aseguramos inicializar la base al abrir la App
inicializar_tablas()

@st.cache_data(show_spinner=False, ttl=86400)
def obtener_comunas_chile_oficial():
    """
    Combina 2 APIs Oficiales/Públicas (JOIN) para obtener datos exactos:
    1. API DPA (Gobierno): Garantiza el 100% de las 346 comunas y sus regiones.
    2. API Wikipedia: Extrae el censo de habitantes para rellenar los datos.
    *Nota: Bloques try-except independientes para tolerancia a fallos.
    """
    dataset = {}
    headers = {"User-Agent": "GestorApp/1.0 (contacto@dominio.com) python-requests"}
    
    # --- API 1: Wikipedia (Censo de Habitantes - Más rápida) ---
    try:
        import html
        params = {"action": "parse", "page": "Anexo:Comunas_de_Chile", "prop": "text", "format": "json"}
        res = requests.get("https://es.wikipedia.org/w/api.php", params=params, headers=headers, timeout=10)
        if res.status_code == 200:
            html_content = res.json()['parse']['text']['*']
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html_content, re.DOTALL | re.IGNORECASE)
            for row in rows:
                cols = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL | re.IGNORECASE)
                if len(cols) >= 6:
                    comuna_raw = html.unescape(re.sub(r'<[^>]+>', '', cols[1])).strip()
                    if comuna_raw.lower() in ["comuna", ""]: continue
                    
                    comuna = re.sub(r'\[\d+\]', '', comuna_raw).strip()
                    key_wiki = unicodedata.normalize('NFD', comuna.lower()).encode('ascii', 'ignore').decode('utf-8')
                    
                    region_raw = html.unescape(re.sub(r'<[^>]+>', '', cols[3])).strip()
                    region = re.sub(r'\[\d+\]', '', region_raw).strip()
                    
                    pob_raw = html.unescape(re.sub(r'<[^>]+>', '', cols[5])).replace('&#160;', '').replace('&nbsp;', '').replace(' ', '').replace('.', '').strip()
                    try:
                        habitantes = int(re.search(r'\d+', pob_raw).group())
                    except:
                        habitantes = 0
                        
                    dataset[key_wiki] = {
                        "region": region if "Región" in region else f"Región de {region}",
                        "habitantes": habitantes
                    }
    except Exception as e:
        pass # Si falla Wikipedia, continúa silenciosamente
        
    # --- API 2: Gobierno de Chile (DPA - Garantiza la base de 346 comunas) ---
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        reg = requests.get("https://apis.digital.gob.cl/dpa/regiones", headers=headers, timeout=15, verify=False)
        prov = requests.get("https://apis.digital.gob.cl/dpa/provincias", headers=headers, timeout=15, verify=False)
        com = requests.get("https://apis.digital.gob.cl/dpa/comunas", headers=headers, timeout=15, verify=False)
        
        if reg.status_code == 200 and com.status_code == 200:
            mapa_regiones = {r['codigo']: r['nombre'] for r in reg.json()}
            mapa_provincias = {p['codigo']: p['codigo_padre'] for p in prov.json()} if prov.status_code == 200 else {}
            
            for c in com.json():
                nombre = c['nombre']
                cod_prov = c['codigo_padre']
                cod_reg = mapa_provincias.get(cod_prov)
                nombre_region = mapa_regiones.get(cod_reg, "Región Desconocida")
                
                key = unicodedata.normalize('NFD', nombre.lower()).encode('ascii', 'ignore').decode('utf-8')
                
                if key not in dataset: # Solo inserta si no la pilló Wikipedia primero
                    dataset[key] = {
                        "region": nombre_region if "Región" in nombre_region else f"Región de {nombre_region}",
                        "habitantes": 0
                    }
    except Exception as e:
        pass # Si DPA falla, conserva lo que haya logrado extraer Wikipedia

    # --- Fallback Extremo si AMBAS APIs mueren al mismo tiempo (sin internet) ---
    if not dataset:
        return {
            "arica": {"region": "Región de Arica y Parinacota", "habitantes": 221364},
            "iquique": {"region": "Región de Tarapacá", "habitantes": 191468},
            "antofagasta": {"region": "Región de Antofagasta", "habitantes": 361873},
            "pica": {"region": "Región de Tarapacá", "habitantes": 9296},
            "penco": {"region": "Región del Biobío", "habitantes": 47367}, 
            "santiago": {"region": "Región Metropolitana", "habitantes": 404495},
            "quillon": {"region": "Región de Ñuble", "habitantes": 17485},
            "iquique": {"region": "Región de Tarapacá", "habitantes": 191468},
            "florida": {"region": "Región del Biobío", "habitantes": 10624},
            "la florida": {"region": "Región Metropolitana", "habitantes": 366916}
        }
        
    return dataset

# Cargar el dataset dinámico al arrancar mediante la API oficial
DATASET_OFICIAL = obtener_comunas_chile_oficial()

# ==========================================
# 3. BARRA LATERAL INFORMATIVA
# ==========================================
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3208/3208365.png", width=80)
    st.header("ℹ️ Información")
    st.markdown("---")
    st.caption("**Arquitectura de Datos - Evaluación 2**")
    st.caption("Docente: Hernán R. Sáez Talavera")
    st.info("💡 **Novedad:** Sistema de diseño One-Page con normalización automatizada en base de datos Neon y caché dinámico.")

# ==========================================
# 4. SISTEMA ONE-PAGE (PÁGINA UNIFICADA)
# ==========================================

# ------------------------------------------
# SECCIÓN 1: COMUNAS DE CHILE
# ------------------------------------------
st.markdown("<h2 class='section-header'>Comunas de Chile</h2>", unsafe_allow_html=True)
st.write("Ingrese los datos para procesar. El sistema limpiará las cadenas, removerá caracteres inconsistentes, aplicará el formato seleccionado, validará duplicados y persistirá la auditoría.")

formato_comuna = st.radio("Seleccione el formato de normalización a aplicar:", ["Formato Título", "MAYÚSCULAS", "minúsculas"], horizontal=True)

col_input1, col_input2 = st.columns(2)
with col_input1:
    input_text = st.text_area("Ingreso Manual (Separado por comas)", placeholder="Ejemplo: florida, penco, santiago", height=100)
with col_input2:
    uploaded_file = st.file_uploader("Carga de Archivo (.txt, .csv)", type=['txt', 'csv'])

if st.button("Procesar y Consolidar Sistema", type="primary", use_container_width=True):
    raw_texts = []
    if input_text:
        raw_texts.extend([c.strip() for c in input_text.split(',') if c.strip()])
    if uploaded_file is not None:
        try:
            content_bytes = uploaded_file.getvalue()
            try:
                content = content_bytes.decode('utf-8-sig')
            except UnicodeDecodeError:
                content = content_bytes.decode('latin-1')
            raw_texts.extend([line.strip() for line in content.splitlines() if line.strip()])
        except Exception as e:
            st.error(f"Error al leer el archivo: {e}")
    
    if not raw_texts:
        st.warning("Por favor, ingrese o cargue al menos una comuna.")
    else:
        with st.spinner("Procesando, normalizando y guardando en Neon DB..."):
            # 1. Normalización según selección del usuario y limpieza de caracteres
            comunas_limpias = []
            for c in raw_texts:
                # Corrección de caracteres inconsistentes (se dejan solo letras, números y espacios)
                c_clean = re.sub(r'[^\w\s]', '', c.strip())
                c_norm = re.sub(r'\s+', ' ', c_clean)
                
                if formato_comuna == "Formato Título":
                    c_norm = c_norm.title()
                elif formato_comuna == "MAYÚSCULAS":
                    c_norm = c_norm.upper()
                else:
                    c_norm = c_norm.lower()
                    
                comunas_limpias.append(c_norm)
                
            # 2. Filtro y Métricas
            comunas_unicas = list(dict.fromkeys(comunas_limpias))
            stats = {
                "leidos": len(raw_texts),
                "procesadas": len(comunas_unicas),
                "duplicados": len(raw_texts) - len(comunas_unicas),
                "consolidados": 0,
                "no_encontrados": 0,
                "errores": []
            }
            
            # 3. Inserción (UPSERT)
            conn = get_db_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        for comuna in comunas_unicas:
                            # Preparar string sin tildes y en minúscula solo para buscar en el diccionario
                            c_search = unicodedata.normalize('NFD', comuna.lower()).encode('ascii', 'ignore').decode('utf-8')
                            
                            # Validar Regla de Negocio Específica para "Florida"
                            if c_search == "florida":
                                st.info("💡 **Sugerencia del Sistema:** Se ha detectado la entrada 'Florida'. Como opciones válidas en Chile existen **'Florida'** (Región del Biobío) y **'La Florida'** (Región Metropolitana).")
                            
                            if c_search in DATASET_OFICIAL:
                                region = DATASET_OFICIAL[c_search]["region"]
                                habs = DATASET_OFICIAL[c_search]["habitantes"]
                                
                                try:
                                    # Limpiar posibles duplicados antiguos por diferencias de mayúsculas/minúsculas ("PENCO" vs "Penco")
                                    cur.execute("DELETE FROM comunas_consolidadas WHERE LOWER(nombre_comuna) = LOWER(%s) AND nombre_comuna != %s", (comuna, comuna))
                                    
                                    cur.execute("""
                                        INSERT INTO comunas_consolidadas (nombre_comuna, region, habitantes, actualizado_en)
                                        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                                        ON CONFLICT (nombre_comuna) 
                                        DO UPDATE SET 
                                            region = EXCLUDED.region,
                                            habitantes = EXCLUDED.habitantes,
                                            actualizado_en = CURRENT_TIMESTAMP;
                                    """, (comuna, region, habs))
                                    stats["consolidados"] += 1
                                except Exception as e:
                                    stats["errores"].append(f"DB Error en {comuna}: {str(e)[:50]}")
                                    conn.rollback()
                            else:
                                stats["no_encontrados"] += 1
                                stats["errores"].append(f"'{comuna}' ignorada por no existir en la fuente oficial.")
                                
                        errores_str = " | ".join(stats["errores"]) if stats["errores"] else "Ningún error."
                        
                        # Auditoría
                        cur.execute("""
                            INSERT INTO auditoria (fecha_ejecucion, registros_leidos, comunas_procesadas, 
                                                   duplicados_eliminados, consolidados_correctamente, no_encontrados, errores)
                            VALUES (%s, %s, %s, %s, %s, %s, %s);
                        """, (datetime.now(), stats["leidos"], stats["procesadas"], stats["duplicados"], 
                              stats["consolidados"], stats["no_encontrados"], errores_str))
                        conn.commit()
                except Exception as e:
                    st.error(f"Error durante el guardado de datos: {e}")
                finally:
                    conn.close()

        # Mostrar métricas animadas
        st.success("¡Procesamiento completado con éxito!")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Registros Ingresados", stats["leidos"])
        m2.metric("Procesados (Únicos)", stats["procesadas"])
        m3.metric("Duplicados Eliminados", stats["duplicados"], delta="-", delta_color="inverse")
        m4.metric("Consolidados OK", stats["consolidados"], delta="UPSERT", delta_color="normal")
        
        if stats["no_encontrados"] > 0:
            st.warning(f"⚠️ Alerta Operativa: {stats['no_encontrados']} registros ignorados por no pertenecer al dataset oficial.")

st.markdown("#### Vista de Datos Consolidados en Neon")
# Renderizar Dataframes interactivos independientemente del botón para visibilidad continua
try:
    conn = get_db_connection()
    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM comunas_consolidadas ORDER BY nombre_comuna")
            df_comunas = pd.DataFrame(cur.fetchall())
            cur.execute("SELECT * FROM auditoria ORDER BY fecha_ejecucion DESC LIMIT 10")
            df_auditoria = pd.DataFrame(cur.fetchall())
        conn.close()
        
        if not df_comunas.empty:
            st.dataframe(df_comunas, use_container_width=True)
        else:
            st.info("La tabla de comunas consolidadas actualmente se encuentra vacía.")
            
        with st.expander("Ver Historial Completo de Auditoría"):
            if not df_auditoria.empty:
                st.dataframe(df_auditoria, use_container_width=True)
            else:
                st.info("Sin registros de auditoría procesados aún.")
except Exception as e:
    st.error(f"Error obteniendo los registros desde Neon: {e}")

# ------------------------------------------
# SECCIÓN 2: GALERÍA DE CELEBRIDADES
# ------------------------------------------
st.markdown("<h2 class='section-header'>Galería de Celebridades</h2>", unsafe_allow_html=True)
st.write("Sube un archivo de texto con la lista de famosos. El sistema procesará los datos e identificará las celebridades para buscar sus imágenes vía API, optimizando con una caché en base de datos.")

def get_wiki_image(name):
    # 1. Caché DB Neon
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT imagen_url, fecha_captura FROM famosos_cache WHERE nombre = %s", (name,))
                res = cur.fetchone()
            conn.close()
            if res:
                return res['imagen_url'], res['fecha_captura'], True
    except Exception:
        pass 
    
    # 2. Wikipedia API
    try:
        headers = {
            "User-Agent": "GestorApp/1.0 (contacto@dominio.com) python-requests"
        }
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": name,
            "gsrlimit": 3,
            "prop": "pageimages",
            "format": "json",
            "pithumbsize": 500
        }
        # 1. Búsqueda inteligente en Wikipedia en Español
        resp = requests.get("https://es.wikipedia.org/w/api.php", params=params, headers=headers, timeout=5).json()
        pages = resp.get('query', {}).get('pages', {})
        img_url = None
        for page_id, page_data in pages.items():
            if 'thumbnail' in page_data:
                img_url = page_data['thumbnail']['source']
                break
                
        # 2. Respaldo (Fallback) a Wikipedia en Inglés si no encontró imagen
        if not img_url:
            resp_en = requests.get("https://en.wikipedia.org/w/api.php", params=params, headers=headers, timeout=5).json()
            pages_en = resp_en.get('query', {}).get('pages', {})
            for page_id, page_data in pages_en.items():
                if 'thumbnail' in page_data:
                    img_url = page_data['thumbnail']['source']
                    break
                    
        # 3. Respaldo directo por la API REST
        if not img_url:
            resp_exact = requests.get(f"https://es.wikipedia.org/api/rest_v1/page/summary/{name}", headers=headers, timeout=5)
            if resp_exact.status_code == 200:
                data = resp_exact.json()
                if 'thumbnail' in data:
                    img_url = data['thumbnail']['source']
        
        if img_url:
            now = datetime.now()
            # 3. Guardar en Caché (UPSERT)
            try:
                conn = get_db_connection()
                if conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO famosos_cache (nombre, imagen_url, fecha_captura)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (nombre) DO UPDATE
                            SET imagen_url = EXCLUDED.imagen_url, fecha_captura = EXCLUDED.fecha_captura
                        """, (name, img_url, now))
                        conn.commit()
                    conn.close()
            except Exception:
                pass
            return img_url, now, False
        return None, None, False
    except Exception as e:
        return None, None, False

archivo_famosos = st.file_uploader("📂 Sube tu archivo de famosos (.txt, .csv)", type=['txt', 'csv'], key="upload_famosos")

if archivo_famosos is not None:
    try:
        df_famosos = procesar_famosos(archivo_famosos)
        st.success("Dataset de celebridades procesado exitosamente.")
        
        with st.expander("Ver tabla de datos procesados"):
            st.dataframe(df_famosos, use_container_width=True)
            
        st.markdown("### Galería Dinámica")
        for idx, row in df_famosos.iterrows():
            nombre = row['Nombre']
            edad = row['Edad']
            fecha_final = row['Fecha_Final']
            
            with st.container(border=True):
                col1, col2 = st.columns([3, 1], vertical_alignment="center")
                with col1:
                    st.subheader(nombre)
                    edad_str = f"{int(edad)} años" if pd.notna(edad) else "Desconocida"
                    st.markdown(f"**Edad calculada:** {edad_str} &nbsp;|&nbsp; **Fecha original/calculada:** {fecha_final}")
                with col2:
                    ver_img = st.button("🖼️ Ver Imagen", key=f"btn_fam_{idx}", use_container_width=True)
                
                if ver_img:
                    with st.spinner(f"Buscando imagen de {nombre}..."):
                        img_url, cap_date, from_cache = get_wiki_image(nombre)
                        if img_url:
                            if from_cache:
                                st.info("Imagen recuperada desde la Caché en Neon (famosos_cache).", icon="⚡")
                            else:
                                st.warning("Imagen consultada desde Wikipedia API y guardada en caché.", icon="🌐")
                            
                            img_c1, img_c2, img_c3 = st.columns([1, 2, 1])
                            with img_c2:
                                st.image(img_url, width=350)
                                st.markdown(f"""
                                <div style='background-color: #f8f9fa; padding: 10px; border-radius: 5px; text-align: center; border: 1px solid #ddd; margin-top: -10px; width: 350px;'>
                                    <small style='color: #555;'><b>Captura:</b> {cap_date.strftime('%Y-%m-%d %H:%M:%S')}</small>
                                </div>
                                """, unsafe_allow_html=True)
                        else:
                            st.error("No se pudo obtener la imagen o no existe en Wikipedia.")
    except Exception as e:
        st.error(f"Error al procesar el archivo de famosos: {e}")
else:
    st.info("ℹ Sube un archivo con los datos de las celebridades para generar la galería y la consulta de imágenes.")

# ------------------------------------------
# SECCIÓN 3: GEOLOCALIZACIÓN HISTÓRICA
# ------------------------------------------
st.markdown("<h2 class='section-header'>🗺️ III. Geolocalización Histórica Mundial</h2>", unsafe_allow_html=True)
st.write("Explora la base de datos relacional mediante un modelo de renderizado 3D dinámico impulsado por Pydeck.")

try:
    conn = get_db_connection()
    df_lugares = pd.DataFrame()
    if conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT l.nombre_lugar, g.latitud, g.longitud 
                FROM lugares l 
                JOIN georeferencias g ON l.id = g.id
                WHERE g.latitud IS NOT NULL AND g.longitud IS NOT NULL
            """)
            datos_geo = cur.fetchall()
        conn.close()
        
        if datos_geo:
            df_lugares = pd.DataFrame(datos_geo)
            df_lugares['lat'] = pd.to_numeric(df_lugares['latitud'], errors='coerce')
            df_lugares['lon'] = pd.to_numeric(df_lugares['longitud'], errors='coerce')
            df_lugares = df_lugares.dropna(subset=['lat', 'lon'])
            
    if not df_lugares.empty:
        opciones_lugares = ["Seleccione un lugar para acercar..."] + sorted(df_lugares['nombre_lugar'].tolist())
        seleccion = st.selectbox("📍 Buscar destino histórico:", opciones_lugares)
        
        view_lat = df_lugares['lat'].mean()
        view_lon = df_lugares['lon'].mean()
        zoom = 1
        
        if seleccion != "Seleccione un lugar para acercar...":
            row = df_lugares[df_lugares['nombre_lugar'] == seleccion].iloc[0]
            view_lat = float(row['lat'])
            view_lon = float(row['lon'])
            zoom = 12 
            
        layer = pdk.Layer(
            "ScatterplotLayer",
            data=df_lugares,
            get_position='[lon, lat]',
            get_color='[200, 30, 0, 160]',
            get_radius=1000,
            radius_min_pixels=5,
            radius_max_pixels=15,
            pickable=True
        )
        
        view_state = pdk.ViewState(
            latitude=view_lat,
            longitude=view_lon,
            zoom=zoom,
            pitch=45,
            transition_duration=1500
        )
        
        st.pydeck_chart(pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            map_style="road",
            tooltip={"text": "{nombre_lugar}"}
        ))
    else:
        st.info("ℹ️ Aún no hay datos de georeferencias cargados en la base de datos Neon.")
except Exception as e:
    st.error(f"Error imprevisto al cargar el mapa interactivo: {e}")