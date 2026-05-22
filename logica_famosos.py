import pandas as pd
from datetime import datetime
import re

def procesar_famosos(archivo_subido):
    """
    Función ETL para el dataset de famosos.
    Implementa lectura iterativa con regex para limpiar formatos,
    unificar fechas rotas, calcular edades (incluso a.C.) y ordenar.
    """
    # 1. LEER EL ARCHIVO LÍNEA POR LÍNEA Y REPARAR LÍNEAS ROTAS
    contenido_bytes = archivo_subido.getvalue() if hasattr(archivo_subido, 'getvalue') else archivo_subido.read()
    try:
        contenido = contenido_bytes.decode('utf-8-sig')
    except UnicodeDecodeError:
        contenido = contenido_bytes.decode('latin-1')
    lineas = contenido.splitlines()
    
    registros_reparados = []
    for linea in lineas:
        linea = linea.strip('\ufeff').strip()
        if not linea:
            continue
        
        # Lógica de reconstrucción de líneas rotas (ej: Nikola Tesla -\n 1856-07-10)
        if registros_reparados:
            ultima = registros_reparados[-1].strip()
            es_fecha = re.match(r'^\d{1,4}[/\-]\d{1,2}', linea)
            termina_separador = ultima.endswith('-') or ultima.endswith(',')
            es_texto_roto = re.match(r'^[a-z]', linea) and not re.search(r'\d|-|,|;|\||\t', linea)
            
            if es_fecha or termina_separador or es_texto_roto:
                registros_reparados[-1] += " " + linea
                continue
                
        registros_reparados.append(linea)

    # 2. PARSEAR NOMBRES Y FECHAS
    datos_extraidos = []
    for registro in registros_reparados:
        # Quitamos viñetas numéricas sin dañar fechas reales (ej: '1. ' o '1) ')
        registro_limpio = re.sub(r'^\d+[\.\-\)]?\s+', '', registro)
        
        # Primero intentamos separadores obvios (" - ", ",", ";", tabulaciones)
        # Se elimina la separación por múltiples espacios (\s{2,}) para evitar romper nombres que internamente tienen más de un espacio
        partes = re.split(r'\s+-\s+|\s*,\s*|\s*;\s*|\s*\|\s*|\t+', registro_limpio, 1)
        
        # Si no funciona, buscamos un espacio antes de un dígito o un guion pegado
        if len(partes) < 2:
            partes = re.split(r'\s+(?=\d{1,4}[/\-]\d{1,2}|\d{1,2}\s+[a-zA-Z])|-(?=\d{1,4})', registro_limpio, 1)

        if len(partes) >= 2:
            nombre = partes[0].strip()
            fecha_str = partes[1].strip()
        else:
            nombre = registro_limpio.strip()
            fecha_str = ""
        
        # Limpiar caracteres raros del nombre (dejando letras, números, espacios, puntos y guiones)
        nombre = re.sub(r'[^\w\s\.\-]', '', nombre).strip()
        
        if nombre: # Evitar agregar registros completamente vacíos
            datos_extraidos.append({'Nombre': nombre, 'Fecha_Original': fecha_str})

    df = pd.DataFrame(datos_extraidos)
    
    if df.empty:
        texto_debug = " | ".join(lineas[:3]) if lineas and any(lineas) else "EL ARCHIVO SE LEYÓ COMO VACÍO (0 BYTES)."
        raise ValueError(f"No se encontraron registros válidos. Muestra de lo detectado internamente: {texto_debug}")

    # 1. LIMPIEZA DE ESPACIOS MÚLTIPLES EN EL NOMBRE ANTES DE ELIMINAR DUPLICADOS
    df['Nombre'] = df['Nombre'].str.replace(r'\s+', ' ', regex=True).str.strip()

    # 3. ELIMINAR REGISTROS DUPLICADOS POR NOMBRE (Ignorando mayúsculas/minúsculas)
    df['Nombre_lower'] = df['Nombre'].str.lower()
    df = df.drop_duplicates(subset=['Nombre_lower'], keep='first')
    df = df.drop(columns=['Nombre_lower'])

    # 4. Y 5. UNIFICAR FECHAS Y CALCULAR EDADES
    hoy = datetime.now()
    fechas_finales = []
    edades = []
    flags_cumple = []

    for fecha_str in df['Fecha_Original']:
        fecha_str = str(fecha_str).strip()
        
        # Validación manual para fechas "a.C." o aproximadas ("alrededor")
        if 'a.c.' in fecha_str.lower() or 'alrededor' in fecha_str.lower():
            fechas_finales.append(fecha_str) # Mantenemos el texto original
            flags_cumple.append('No')
            
            # Extraemos el año usando regex y calculamos la edad manualmente
            match = re.search(r'\d+', fecha_str)
            if match:
                año_extraido = int(match.group())
                if 'a.c.' in fecha_str.lower():
                    edades.append(hoy.year + año_extraido) # Sumamos los años transcurridos
                else:
                    edades.append(hoy.year - año_extraido) # Restamos para fechas después de cristo
            else:
                edades.append(None)
        elif fecha_str:
            # Estrategia de conversión robusta con múltiples formatos explícitos
            try:
                fecha_dt = pd.NaT
                formatos = ['%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%Y/%m/%d']
                
                for fmt in formatos:
                    try:
                        fecha_dt = pd.to_datetime(fecha_str, format=fmt)
                        if pd.notna(fecha_dt):
                            break
                    except (ValueError, TypeError):
                        continue
                
                # Fallback: si los formatos estrictos fallan, intentar el parseo general
                if pd.isna(fecha_dt):
                    fecha_dt = pd.to_datetime(fecha_str, dayfirst=True)

                if pd.isna(fecha_dt):
                    raise ValueError("Fecha NaT")
                    
                fechas_finales.append(fecha_dt.strftime('%d-%m-%Y'))
                
                edad = hoy.year - fecha_dt.year
                if (hoy.month, hoy.day) < (fecha_dt.month, fecha_dt.day):
                    edad -= 1
                edades.append(edad)
                
                if hoy.month == fecha_dt.month and hoy.day == fecha_dt.day:
                    flags_cumple.append('Sí')
                else:
                    flags_cumple.append('No')
            except:
                fechas_finales.append('Fecha Inválida')
                edades.append(None)
                flags_cumple.append('No')
        else:
            fechas_finales.append('Fecha Inválida')
            edades.append(None)
            flags_cumple.append('No')

    df['Fecha_Final'] = fechas_finales
    df['Edad'] = edades
    df['Es_Cumpleanos_Hoy'] = flags_cumple

    # 6. SELECCIONAR COLUMNAS Y ORDENAMIENTO DE A-Z
    resultado_final = df[['Nombre', 'Fecha_Final', 'Edad', 'Es_Cumpleanos_Hoy']]
    resultado_final = resultado_final.sort_values(by='Nombre', ascending=True).reset_index(drop=True)
    
    return resultado_final