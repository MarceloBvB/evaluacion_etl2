import pandas as pd
import re

def procesar_lugares(archivo_subido):
    """
    Función ETL para el dataset de lugares.
    Limpia duplicados, separa las columnas según los requerimientos estrictos
    y normaliza la información en 3 DataFrames distintos basándose en DATOS3.TXT.
    """
    # 1. LECTURA EXPLICITA CON separador ';'
    try:
        df = pd.read_csv(archivo_subido, sep=';', encoding='utf-8-sig')
    except UnicodeDecodeError:
        archivo_subido.seek(0)
        df = pd.read_csv(archivo_subido, sep=';', encoding='latin-1')
    
    # Limpieza inicial de espacios en los nombres de las columnas
    df.columns = df.columns.str.strip()

    # Validación básica por si las columnas varían (Prevención de KeyError)
    cols_necesarias = ['Nombre del lugar', 'Dirección Completa', 'Georeferencia']
    for col in cols_necesarias:
        if col not in df.columns:
            coincidencias = [c for c in df.columns if col.lower()[:5] in c.lower()]
            if coincidencias:
                df.rename(columns={coincidencias[0]: col}, inplace=True)
            else:
                df[col] = '' # Creamos la columna vacía para evitar colapsos

    # 2. LIMPIEZA DE DUPLICADOS Y CREACIÓN DE ID
    df = df.drop_duplicates(subset=['Nombre del lugar', 'Dirección Completa'], keep='first').copy()
    df.insert(0, 'id', range(1, len(df) + 1))

    # 3. CREAR TABLA 1: LUGARES (ID, nombre_lugar)
    tabla_lugares = df[['id', 'Nombre del lugar']].copy()
    tabla_lugares.rename(columns={'Nombre del lugar': 'nombre_lugar'}, inplace=True)
    tabla_lugares['nombre_lugar'] = tabla_lugares['nombre_lugar'].astype(str).str.strip()
    # ORDENAMIENTO A-Z por 'nombre_lugar'
    tabla_lugares = tabla_lugares.sort_values(by='nombre_lugar', ascending=True).reset_index(drop=True)

    # 4. CREAR TABLA 2: GEOREFERENCIAS (ID, latitud, longitud)
    tabla_georeferencias = pd.DataFrame()
    tabla_georeferencias['id'] = df['id']
    
    # Dividir la columna por el separador coma
    geo_split = df['Georeferencia'].astype(str).str.split(',', expand=True)
    tabla_georeferencias['latitud'] = geo_split[0].str.strip() if 0 in geo_split.columns else ''
    tabla_georeferencias['longitud'] = geo_split[1].str.strip() if 1 in geo_split.columns else ''
    tabla_georeferencias.replace('nan', '', inplace=True) # Limpiar textos "nan" indeseados
    
    # ORDENAMIENTO A-Z por 'latitud'
    tabla_georeferencias = tabla_georeferencias.sort_values(by='latitud', ascending=True).reset_index(drop=True)

    # 5. CREAR TABLA 3: DIRECCIONES (Estrategia de Parseo Estricto)
    def parsear_direccion(direccion):
        dir_str = str(direccion).strip()
        if not dir_str or dir_str.lower() == 'nan':
            return '', '', '', ''
        
        partes = [p.strip() for p in dir_str.split(',')]
        
        if len(partes) == 1:
            calle_full, ciudad, pais = partes[0], '', partes[0] # Asignación segura en 1 parte
        elif len(partes) == 2:
            calle_full, ciudad, pais = partes[0], '', partes[1]
        else:
            calle_full = partes[0]
            ciudad = ", ".join(partes[1:-1]) # Juntar intermedios
            pais = partes[-1]
            
        # Extraer número de la calle usando Regex
        match = re.search(r'\d+', calle_full)
        if match:
            numero_calle = match.group()
            nombre_calle = re.sub(r'\d+', '', calle_full).strip()
            nombre_calle = re.sub(r'\s+', ' ', nombre_calle) # Limpiar espacios dobles
        else:
            nombre_calle = calle_full
            numero_calle = ''
            
        return nombre_calle, numero_calle, ciudad, pais

    parsed_dirs = df['Dirección Completa'].apply(parsear_direccion)
    
    tabla_direcciones = pd.DataFrame({
        'ID': df['id'],
        'nombre_calle': [p[0] for p in parsed_dirs],
        'numero_calle': [p[1] for p in parsed_dirs],
        'ciudad_estado_provincia': [p[2] for p in parsed_dirs],
        'pais': [p[3] for p in parsed_dirs]
    })
    
    # ORDENAMIENTO A-Z por 'nombre_calle'
    tabla_direcciones = tabla_direcciones.sort_values(by='nombre_calle', ascending=True).reset_index(drop=True)

    # 6. REGLAS ESTÉTICAS Y MANEJO DE NULOS
    # Reemplazamos strings vacíos o de puros espacios por None (NULL en SQL) para limpieza
    for col in ['numero_calle', 'ciudad_estado_provincia']:
        tabla_direcciones[col] = tabla_direcciones[col].apply(lambda x: None if pd.isna(x) or str(x).strip() == '' else x)

    # Aplicamos la misma regla a latitud/longitud por si vienen vacíos, evitando errores en base de datos
    for col in ['latitud', 'longitud']:
        tabla_georeferencias[col] = tabla_georeferencias[col].apply(lambda x: None if pd.isna(x) or str(x).strip() == '' else x)

    return tabla_lugares, tabla_georeferencias, tabla_direcciones