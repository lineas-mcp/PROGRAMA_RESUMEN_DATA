import folium
from streamlit_folium import st_folium
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import pandas as pd
import re
from datetime import datetime
from io import BytesIO
import altair as alt
import pydeck as pdk 
from fpdf import FPDF
import matplotlib.pyplot as plt
import io
import numpy as np
from folium.plugins import HeatMap

# ==========================================
# 1. CONFIGURACIÓN Y ESTILO JSJSJSJS
# ==========================================
st.set_page_config(page_title="Chinalco - Control de Mantenimiento", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #FFFFFF; }
    h1, h2, h3 { color: #01305D; border-bottom: 2px solid #01305D; padding-bottom: 10px; }
    
    /* Diseño mejorado para todos los Tabs (Principales y Sub-tabs) */
    .stTabs [data-baseweb="tab-list"] {
        gap: 15px;
        background-color: #f8f9fa;
        padding: 10px 15px;
        border-radius: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 5px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        padding: 0 20px;
    }
    .stTabs [aria-selected="true"] { 
        background-color: #01305D !important; 
        color: white !important; 
        font-weight: bold; 
        border: none;
    }
    
    .stButton>button { background-color: #01305D; color: white; border-radius: 5px; width: 100%; }
    .stDownloadButton>button { background-color: #28a745; color: white; border-radius: 5px; }
    .dataframe th { text-align: left !important; background-color: #f0f2f6 !important; }
    </style>
    """, unsafe_allow_html=True)

@st.cache_resource
def conectar_firebase():
    if not firebase_admin._apps:
        try:
            if "firebase" in st.secrets:
                creds = dict(st.secrets["firebase"])
                
                # REPARACIÓN MANUAL DE LA LLAVE PEM
                key = creds["private_key"]
                if "-----BEGIN PRIVATE KEY-----" in key and "\\n" not in key:
                    # Extraemos el contenido base64 quitando los encabezados
                    header = "-----BEGIN PRIVATE KEY-----"
                    footer = "-----END PRIVATE KEY-----"
                    content = key.replace(header, "").replace(footer, "").replace(" ", "").strip()
                    
                    # Reconstruimos el formato PEM oficial: Cabecera + contenido cada 64 chars + Pie
                    lines = [content[i:i+64] for i in range(0, len(content), 64)]
                    key_rebuilt = header + "\n" + "\n".join(lines) + "\n" + footer + "\n"
                    creds["private_key"] = key_rebuilt
                
                cred = credentials.Certificate(creds)
            else:
                cred = credentials.Certificate("credenciales.json")
                
            firebase_admin.initialize_app(cred)
            return firestore.client()
        except Exception as e:
            st.error(f"❌ Error de conexión Firebase: {e}")
            return None
    return firestore.client()

db = conectar_firebase()

# ==========================================
# 2. PROCESADORES TÉCNICOS
# ==========================================
def procesar_detalles_lineas(texto, lista_comps):
    res = {c: "N/A" for c in lista_comps}
    obs_dict = {f"obs_{c}": "" for c in lista_comps}
    act_dict = {f"act_{c}": "" for c in lista_comps}
    foto_dict = {f"foto_{c}": "NO FOTO" for c in lista_comps} # 👈 1. Nuevo diccionario para guardar las fotos
    
    if not texto: 
        return res | obs_dict | act_dict | foto_dict | {"Obs_Final": "", "Act_Final": ""}

    bloques = re.findall(r'\[(.*?)\]', texto)
    resumen_obs = []
    resumen_act = []
    
    omitir = ["", "N/A", "NINGUNA", "SIN OBS", "SIN OBSERVACION", "SIN OBSERVACIONES", "SIN ACT", "SIN ACTIVIDAD"]
    conv = {"ALTO": "A", "MEDIO": "M", "BAJO": "B", "BUENO": "B", "REGULAR": "M", "MALO": "A", "NT": "NT"}

    for b in bloques:
        p = b.split(" | ")
        if len(p) >= 2:
            c_nom = p[0].strip()
            if c_nom in res:
                # 1. Estado (A, M, B...)
                res[c_nom] = conv.get(p[1].strip().upper(), p[1].strip().upper())
                
                # 👈 2. Buscar dinámicamente si hay una FOTO en cualquiera de las partes de la cadena
                for part in p:
                    if part.strip().startswith("FOTO:"):
                        foto_dict[f"foto_{c_nom}"] = part.replace("FOTO:", "").strip()
                
                # 3. Extraer Observación (p[2])
                if len(p) >= 3:
                    obs_val = p[2].strip()
                    if obs_val.upper() not in omitir and not obs_val.startswith("FOTO:"):
                        obs_dict[f"obs_{c_nom}"] = obs_val
                        resumen_obs.append(f"• {c_nom}: {obs_val}")
                
                # 4. Extraer Actividad (p[3])
                if len(p) >= 4:
                    act_val = p[3].replace("ACT:", "").strip()
                    if act_val.upper() not in omitir and not act_val.startswith("FOTO:"):
                        act_dict[f"act_{c_nom}"] = act_val
                        resumen_act.append(f"• {c_nom}: {act_val}")

    res["Obs_Final"] = "\n".join(resumen_obs)
    res["Act_Final"] = "\n".join(resumen_act)
    
    # Retornamos también el diccionario de fotos
    return res | obs_dict | act_dict | foto_dict

def color_estado(val):
    if val is None or pd.isna(val):
        return 'text-align: center;'
        
    v = str(val).strip().upper()
    
    # --- LÓGICA DE COLORES PARA LÍNEAS (Incluyendo la N) ---
    if v == "A": 
        return 'background-color: #FFDADA; color: #CC0000; font-weight: bold; text-align: center;'
    if v == "M" or v == "NT": 
        return 'background-color: #FFF4E5; color: #E67E22; font-weight: bold; text-align: center;'
    if v == "B": # 👈 Aquí agregamos la N para que se pinte como "Bueno/Normal"
        return 'background-color: #E8F5E9; color: #2E7D32; font-weight: bold; text-align: center;'
    if v == "N/A": 
        return 'color: #BDC3C7; text-align: center;'
    
    # --- LÓGICA PARA GENSETS ---
    if v in ["CAMBIAR", "INOPERATIVO", "VACÍO", "1/4", "SUCIO"]: 
        return 'background-color: #FFDADA; color: #CC0000; font-weight: bold; text-align: center;'
    if v in ["NO TIENE", "1/2", "STAND BY"]: 
        return 'background-color: #FFF4E5; color: #E67E22; font-weight: bold; text-align: center;'
    if v in ["TIENE", "OPERATIVO", "FULL", "3/4", "LIMPIO", "TRABAJANDO", "INSPECCIÓN"]: 
        return 'background-color: #E8F5E9; color: #2E7D32; font-weight: bold; text-align: center;'
        
    return 'text-align: center;'

ORDEN_EXACTO_GENSET = [
    "Actividad", "Estado", "Voltaje", "Combustible", "Refrigerante",
    "Aceite Motor", "Limpieza", "Batería", "Contacto de Batería",
    "Cable de la Batería", "Alternador", "Motor", "Filtro de Aire del Motor",
    "Indicador Filtro de Aire", "Separador de Agua", "Filtros de Aceite",
    "Cargador de Baterias", "Neumáticos", "Fajas", "Tuberías", "Ventilador",
    "Gata", "Gancho de Remolque", "Tacos", "Extintor", "Conos",
    "Recomendación de Cambio", "Comentarios"
]

# ==========================================
# 3. INTERFAZ Y DESCARGA (ARQUITECTURA ACUMULATIVA)
# ==========================================
st.image("logo_chinalco.png", width=250)

if db:
    # --- INICIALIZACIÓN DE LA MEMORIA ---
    if "df_master" not in st.session_state: st.session_state.df_master = pd.DataFrame()
    if "df_genset" not in st.session_state: st.session_state.df_genset = pd.DataFrame()
    if "campanas_descargadas" not in st.session_state: st.session_state.campanas_descargadas = []
    if "gensets_descargados" not in st.session_state: st.session_state.gensets_descargados = False

    # --- OBTENER LISTA DE CAMPAÑAS ---
    @st.cache_data(ttl=600)
    def obtener_campanas():
        docs_c = db.collection("reportes_inspeccion_lineas").select(["campana"]).stream()
        return sorted(list(set([d.to_dict().get("campana") for d in docs_c if d.to_dict().get("campana")])), reverse=True)
    
    camps_totales = obtener_campanas()
    camps_pendientes = [c for c in camps_totales if c not in st.session_state.campanas_descargadas]

    # --- PANEL SUPERIOR DE SINCRONIZACIÓN ---
    with st.expander("📦 Panel de Sincronización de Datos (Firebase)", expanded=True):
        st.markdown(f"**✅ Campañas en Memoria:** {', '.join(st.session_state.campanas_descargadas) if st.session_state.campanas_descargadas else '*Ninguna*'} | **🚜 Gensets Descargados:** {'Sí' if st.session_state.gensets_descargados else 'No'}")
        
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        
        # OJO: Ahora mostramos TODAS las campañas en el selector, no solo las pendientes
        # Esto permite seleccionar una que ya está en memoria para "Actualizarla"
        with c1:
            seleccionados = st.multiselect("Selecciona campañas para descargar o actualizar:", camps_totales)
        
        ejecutar_descarga = False
        campanas_a_descargar = []

        with c2:
            if st.button("📥 Descargar Nuevas", use_container_width=True):
                # Filtramos para descargar solo lo que no está en memoria
                nuevas_sel = [c for c in seleccionados if c not in st.session_state.campanas_descargadas]
                if nuevas_sel or not st.session_state.gensets_descargados:
                    ejecutar_descarga = True
                    campanas_a_descargar = nuevas_sel
                else:
                    st.info("Las campañas seleccionadas ya están en memoria.")
                    
        with c3:
            if st.button("🔄 Buscar en Nube", use_container_width=True):
                obtener_campanas.clear() 
                st.rerun()
                
        with c4:
            # Reemplazamos "Descargar Faltantes" por "Actualizar Selección"
            if st.button("⚡ Actualizar Selección", use_container_width=True, type="primary"):
                if seleccionados:
                    ejecutar_descarga = True
                    campanas_a_descargar = seleccionados # Descargará todo lo seleccionado, esté o no en memoria
                else:
                    st.info("Selecciona al menos una campaña en la lista para actualizarla.")

        if st.button("🗑️ Vaciar Memoria (Reset Total)", use_container_width=True):
            st.session_state.df_master = pd.DataFrame()
            st.session_state.df_genset = pd.DataFrame()
            st.session_state.campanas_descargadas = []
            st.session_state.gensets_descargados = False
            st.rerun()

        # ==========================================
        # LÓGICA DE DESCARGA UNIFICADA
        # ==========================================
        if ejecutar_descarga:
            with st.spinner("Sincronizando con Firebase..."):
                
                # 1. ACUMULAR O ACTUALIZAR LÍNEAS
                if campanas_a_descargar:
                    data_l = []
                    comps_l = ["Estructura", "Aislador", "Cable", "Drenaje", "Ferreteria", "Guarda", "Inclinacion", "PAT", "Pararrayos", "Retenida", "Seccionador","Señalética","Otros"]
                    docs_l = db.collection("reportes_inspeccion_lineas").where("campana", "in", campanas_a_descargar).stream()
                    
                    for doc in docs_l:
                        d = doc.to_dict()
                        if d.get("poste"):
                            dt = pd.to_datetime(d.get("fecha_inspeccion", 0), unit='ms')
                            info = procesar_detalles_lineas(d.get("detalles_tecnicos", ""), comps_l)
                            row = {
                                "ID_Doc": doc.id, 
                                "Campaña": d.get("campana"), 
                                "Inspector": d.get("inspector"), 
                                "Orden Trabajo": d.get("orden_trabajo", "N/A"),
                                "Tipo Poste": d.get("tipo_poste", "N/A"),
                                "Fecha": dt, 
                                "Zona": d.get("zona", "N/A").strip(), 
                                "Derivación": d.get("equipo", "N/A").strip(), 
                                "Poste": d.get("poste"),
                                "Latitud": d.get("latitud"),   
                                "Longitud": d.get("longitud")  
                            }
                            row.update(info)
                            data_l.append(row)
                    
                    if data_l:
                        nuevo_df_l = pd.DataFrame(data_l)
                        
                        if st.session_state.df_master.empty:
                            st.session_state.df_master = nuevo_df_l
                        else:
                            # Concatenamos la data vieja con la nueva
                            st.session_state.df_master = pd.concat([st.session_state.df_master, nuevo_df_l], ignore_index=True)
                            
                            # 🔥 EL FILTRO ANTI-DUPLICADOS:
                            # Si un ID_Doc se repite, Pandas elimina el viejo y se queda con el 'last' (el que acabamos de descargar)
                            st.session_state.df_master = st.session_state.df_master.drop_duplicates(subset=["ID_Doc"], keep="last").reset_index(drop=True)
                    
                    # Actualizamos la lista de memoria sin duplicar nombres
                    for c in campanas_a_descargar:
                        if c not in st.session_state.campanas_descargadas:
                            st.session_state.campanas_descargadas.append(c)

                # 2. DESCARGAR GENSETS (Solo si no se han descargado antes)
                if not st.session_state.gensets_descargados:
                    docs_g = db.collection("historial_inspecciones").stream()
                    data_g = []
                    for doc in docs_g:
                        d = doc.to_dict()
                        if d.get("equipo") and not d.get("poste"):
                            f_raw = d.get("fecha_registro") or d.get("fecha_inspeccion") or 0
                            try: dt = pd.to_datetime(f_raw, unit='ms')
                            except: dt = pd.to_datetime(f_raw)
                            
                            nombre_equipo_actual = str(d.get("equipo", "")).strip()
                            tipo_val = d.get("tipo_genset") or d.get("ubicacion_gps") or "Estacionario"
                            if "GENSET 07" in nombre_equipo_actual.upper() or "MOVIL" in str(tipo_val).upper() or "MÓVIL" in str(tipo_val).upper(): tipo_val = "Móvil"
                            else: tipo_val = "Estacionario"
                            
                            row = {
                                "Tipo": tipo_val,
                                "Zona": str(d.get("ubicacion_texto", "N/A")).strip(),
                                "Equipo": nombre_equipo_actual,
                                "Fecha": dt,
                                "Horómetro": float(d.get("horometro", 0)),
                                "Inspector": str(d.get("inspector", "N/A")),
                                "Estado_Op": str(d.get("estado", "NO DEFINIDO")).capitalize(),
                                "Actividad": str(d.get("actividad", "N/A")),
                                "Estado": str(d.get("estado", "NO DEFINIDO")).capitalize(),
                                "Modo": str(d.get("modo", "N/A")),
                                "Voltaje": str(d.get("voltaje", "N/A")),
                                "Combustible": str(d.get("combustible", "N/A")),
                                "Refrigerante": str(d.get("refrigerante", "N/A")),
                                "Aceite Motor": str(d.get("aceite_motor", "N/A")),
                                "Limpieza": str(d.get("limpieza", "N/A")),
                                "Comentarios": str(d.get("comentario", "")).strip()
                            }
                            
                            comp_map = d.get("estado_componentes", {})
                            piezas_cambio = []
                            if isinstance(comp_map, dict):
                                for key, value in comp_map.items():
                                    val_str = str(value).strip()
                                    row[key] = val_str
                                    if val_str.upper() == "CAMBIAR": piezas_cambio.append(key)
                                        
                            row["Recomendación de Cambio"] = ", ".join(piezas_cambio) if piezas_cambio else "Ninguna"
                            row = {k: v for k, v in row.items() if v != "" and v != "N/A" and v != "None"}
                            data_g.append(row)
                    
                    st.session_state.df_genset = pd.DataFrame(data_g)
                    st.session_state.gensets_descargados = True

            st.rerun()

    
    # --- COSAS QUE HACE (ES COMO LAS ACCIONES PERO QUE HACE XD) ---
    tab1, tab2, tab3 = st.tabs(["⚡ Líneas Eléctricas", "🚜 Grupos Electrógenos", "⚖️ Comparativa de Postes"])

    with tab1:
        st.header("Reporte de Líneas")
        df_l = st.session_state.df_master
        if not df_l.empty:
            c1, c2, c3 = st.columns(3)
            with c1: camp_f = st.selectbox("Filtrar por Campaña Vista:", sorted(df_l["Campaña"].unique(), reverse=True))
            df_f = df_l[df_l["Campaña"] == camp_f].copy().reset_index(drop=True)
            
            with c2: zona_f = st.selectbox("Zona:", ["TODAS"] + sorted(df_f["Zona"].unique().tolist()))
            df_f = df_f[df_f["Zona"] == zona_f] if zona_f != "TODAS" else df_f
            
            if "Fecha" in df_f.columns:
                df_f["Fecha"] = pd.to_datetime(df_f["Fecha"]).dt.strftime("%d/%m/%Y")
            
            # LISTA ACTUALIZZZZZADA
            cols_visibles = ["Fecha", "Orden Trabajo", "Campaña", "Zona", "Derivación", "Inspector", "Poste", "Tipo Poste"] + comps_l + ["Obs_Final", "Act_Final"]
            
            comps_l = ["Estructura", "Aislador", "Cable", "Drenaje", "Ferreteria", "Guarda", "Inclinacion", "PAT", "Pararrayos", "Retenida", "Seccionador","Señalética","Otros"]
            
            cols_visibles = ["Fecha","Orden Trabajo","Campaña", "Zona", "Derivación", "Inspector", "Poste", "Tipo Poste"] + comps_l + ["Obs_Final", "Act_Final"]
            
            st.info("💡 Ahora puedes editar la **Campaña** o el **Poste** directamente en la tabla. El sistema usa el ID interno para no perder el rastro.")

            editor_key = f"ed_lin_{camp_f}"

            df_con_estilo = df_f[["ID_Doc"] + cols_visibles].style.map(color_estado, subset=comps_l)
             
            modo_edicion = st.toggle("📝 Activar modo edición", help="Oculta los colores para permitir modificar los datos")

            df_display = df_f[["ID_Doc"] + cols_visibles]

            if modo_edicion:
                clave = st.text_input("🔑 Ingresa la clave de autorización:", type="password")
                
                if clave == "CHINALCO":
                    st.success("✅ Acceso concedido. Ahora puedes editar estados, observaciones y actividades al detalle.")
                    
                    columnas_edicion = ["ID_Doc", "Campaña", "Zona", "Derivación", "Poste"]
                    config_cols = {
                        "ID_Doc": st.column_config.TextColumn("ID Documento", disabled=True),
                        "Campaña": st.column_config.TextColumn("Campaña"),
                        "Poste": st.column_config.TextColumn("Poste"),
                    }
                    
                    for cp in comps_l:
                        columnas_edicion.extend([cp, f"obs_{cp}", f"act_{cp}"])
                        config_cols[cp] = st.column_config.SelectboxColumn(f"⚙️ {cp}", options=["A", "M", "B", "NT", "N/A", "N"])
                        config_cols[f"obs_{cp}"] = st.column_config.TextColumn(f"📝 Obs {cp}")
                        config_cols[f"act_{cp}"] = st.column_config.TextColumn(f"🛠️ Act {cp}")

                    df_display_edit = df_f[columnas_edicion]
                    
                    df_editado = st.data_editor(
                        df_display_edit, 
                        column_config=config_cols,
                        use_container_width=True, 
                        hide_index=True,
                        key=editor_key
                    )
                elif clave != "":
                    st.error("❌ Clave incorrecta. Acceso denegado.")
            else:
                # Modo solo lectura con los colores y columnas resumidas
                df_display_view = df_f[["ID_Doc"] + cols_visibles]
                df_con_estilo = df_display_view.style.map(color_estado, subset=comps_l)
                st.dataframe(df_con_estilo, use_container_width=True, hide_index=True)

            cambios = {}
            # Solo procesamos cambios si el modo edición está activo y la clave es correcta
            if modo_edicion and st.session_state.get(editor_key):
                cambios = st.session_state[editor_key].get("edited_rows", {})

            if cambios:
                st.divider()
                st.subheader("📝 Resumen de Cambios Pendientes")
                
                validos_para_subir = []
                for idx_str, mods in cambios.items():
                    idx = int(idx_str)
                    fila_original = df_f.iloc[idx]
                    id_doc_firebase = fila_original["ID_Doc"]
                    
                    st.write(f"📍 **Documento ID:** `{id_doc_firebase}` (Poste: {fila_original['Poste']})")
                    for col, val in mods.items():
                        st.caption(f"   • {col}: `{fila_original[col]}` → `{val}`")
                    
                    validos_para_subir.append((id_doc_firebase, fila_original, mods))

                c_btn1, c_btn2 = st.columns(2)
                with c_btn1:
                    if st.button("💾 Aplicar Cambios Globales", type="primary", use_container_width=True):
                        with st.spinner("Actualizando Firebase con formato estricto..."):
                            for id_f, f_orig, f_mods in validos_para_subir:
                                update_dict = {}
                                
                                if "Campaña" in f_mods: update_dict["campana"] = f_mods["Campaña"]
                                if "Inspector" in f_mods: update_dict["inspector"] = f_mods["Inspector"]
                                if "Zona" in f_mods: update_dict["zona"] = f_mods["Zona"]
                                if "Derivación" in f_mods: update_dict["equipo"] = f_mods["Derivación"]
                                if "Poste" in f_mods: update_dict["poste"] = f_mods["Poste"]
                                
                                # --- INICIO DE LA RECONSTRUCCIÓN ---
                                texto_obs_final = f_orig.get("Obs_Final", "")
                                texto_act_final = f_orig.get("Act_Final", "")

                                # Si se modificó el estado, la observación o la actividad de algún componente
                                if any(c.replace("obs_", "").replace("act_", "") in comps_l for c in f_mods):
                                    f_nueva = f_orig.copy()
                                    for c, v in f_mods.items(): f_nueva[c] = v
                                    
                                    detalles_lista = []
                                    resumen_obs_nuevo = []
                                    resumen_act_nuevo = []
                                    omitir = ["", "N/A", "NINGUNA", "SIN OBS", "SIN OBSERVACION", "SIN OBSERVACIONES", "SIN ACT", "SIN ACTIVIDAD"]

                                    for cp in comps_l:
                                        est = str(f_nueva.get(cp, "N/A")).strip().upper()
                                        
                                        foto_str = str(f_nueva.get(f"foto_{cp}", "NO FOTO")).strip()
                                        if not foto_str or foto_str.lower() in ["nan", "none", ""]: 
                                            foto_str = "NO FOTO"
                                        
                                        if est == "N":
                                            obs = "Sin Obs"
                                            act = "Ninguna"
                                        else:
                                            obs = str(f_nueva.get(f"obs_{cp}", "Sin Obs")).strip()
                                            if not obs or obs.lower() in ["nan", "none"]: obs = "Sin Obs"
                                            
                                            act = str(f_nueva.get(f"act_{cp}", "Ninguna")).strip()
                                            if not act or act.lower() in ["nan", "none"]: act = "Ninguna"
                                            
                                        # 1. Armamos el bloque para Firebase
                                        bloque_formateado = f"[{cp} | {est} | {obs} | ACT: {act} | FOTO: {foto_str}]"
                                        detalles_lista.append(bloque_formateado)
                                        
                                        # 2. Armamos las viñetas para la tabla visual
                                        if obs.upper() not in omitir:
                                            resumen_obs_nuevo.append(f"• {cp}: {obs}")
                                        if act.upper() not in omitir:
                                            resumen_act_nuevo.append(f"• {cp}: {act}")
                                        
                                    update_dict["detalles_tecnicos"] = " ".join(detalles_lista)
                                    texto_obs_final = "\n".join(resumen_obs_nuevo)
                                    texto_act_final = "\n".join(resumen_act_nuevo)

                                try:
                                    # Subir a Firebase
                                    db.collection("reportes_inspeccion_lineas").document(id_f).update(update_dict)
                                    
                                    # ACTUALIZAR MEMORIA LOCAL AL INSTANTE
                                    idx_master = st.session_state.df_master[st.session_state.df_master["ID_Doc"] == id_f].index
                                    
                                    # a) Actualizamos las celdas individuales editadas
                                    for col_m, val_m in f_mods.items():
                                        st.session_state.df_master.loc[idx_master, col_m] = val_m
                                        
                                    # b) Actualizamos los resúmenes para que se vean al apagar el switch
                                    if any(c.replace("obs_", "").replace("act_", "") in comps_l for c in f_mods):
                                        st.session_state.df_master.loc[idx_master, "Obs_Final"] = texto_obs_final
                                        st.session_state.df_master.loc[idx_master, "Act_Final"] = texto_act_final

                                except Exception as e:
                                    st.error(f"Error al actualizar {id_f}: {e}")

                        st.success("✅ Firebase actualizado correctamente.")
                        st.rerun()

                with c_btn2:
                    if st.button("🚩 Cancelar Edición", use_container_width=True):
                        st.rerun()
            
            if not df_f.empty:
                out_l = BytesIO()
                with pd.ExcelWriter(out_l, engine='openpyxl') as writer:
                    df_ex_l = df_f[["ID_Doc"] + cols_visibles].copy() 
                    if 'Fecha' in df_ex_l.columns: 
                        df_ex_l['Fecha'] = df_ex_l['Fecha'].dt.tz_localize(None)
                    df_ex_l.to_excel(writer, index=False, sheet_name="Lineas")
                
                st.download_button("📥 Descargar Excel de Líneas", out_l.getvalue(), "Reporte_Lineas.xlsx")
            else:
                st.warning("⚠️ No hay datos con los filtros actuales para descargar el Excel.")
            
            # ==========================================
            # 📊 SECCIÓN DE ESTADÍSTICAS Y MAPA (TAB 1)
            # ==========================================

            sub_analitica, sub_mapa, sub_pdf = st.tabs([
                "📊", 
                "🗺️", 
                "📄"
            ])

            # ------------------------------------------
            # SUB-TAB B: ANALÍTICA Y KPIs (CON MARCOS / CARDS)
            # ------------------------------------------
            with sub_analitica:
                st.subheader("📊 Analítica de Inspección")
                st.caption(f"Mostrando datos para: **{camp_f}** | Postes evaluados: **{len(df_f)}**")
                
                if not df_f.empty:
                    # 1. PREPARACIÓN DE DATOS MAESTROS
                    df_graf = df_f[["Poste", "Inspector"] + comps_l].copy()
                    df_melt = df_graf.melt(id_vars=["Poste", "Inspector"], value_vars=comps_l, var_name="Componente", value_name="Estado")
                    df_melt = df_melt[df_melt["Estado"].isin(["A", "M", "B", "NT"])]

                    # Cálculos rápidos
                    total_postes = len(df_graf)
                    postes_criticos = df_graf[comps_l].apply(lambda row: 'A' in row.values, axis=1).sum() 
                    fallas_a = len(df_melt[df_melt["Estado"] == 'A'])
                    fallas_m = len(df_melt[df_melt["Estado"] == 'M'])

                    # --- MARCO 1: KPIs ---
                    with st.container(border=True):
                        st.markdown("### 🎯 Indicadores Clave de Riesgo")
                        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
                        kpi1.metric("📌 Total Postes Revisados", total_postes)
                        kpi2.metric("🚨 Postes en Riesgo", postes_criticos)
                        kpi3.metric("🔴 Fallas Críticas", fallas_a)
                        kpi4.metric("🟠 Fallas Medias", fallas_m)
                    
                    st.write("") # Pequeño espacio

                    # --- FILA DE GRÁFICOS 1 ---
                    col_dona, col_insp = st.columns(2)
                    
                    with col_dona:
                        # MARCO 2: Dona
                        with st.container(border=True):
                            st.markdown("**🍩 Salud General de la Línea**")
                            resumen_estados = df_melt['Estado'].value_counts().reset_index()
                            resumen_estados.columns = ['Estado', 'Cantidad']
                            
                            color_scale_pie = alt.Scale(
                                domain=['A', 'M', 'B', 'NT'],
                                range=['#CC0000', '#E67E22', '#2E7D32', '#95A5A6']
                            )
                            
                            dona_chart = alt.Chart(resumen_estados).mark_arc(innerRadius=60).encode(
                                theta=alt.Theta(field="Cantidad", type="quantitative"),
                                color=alt.Color(field="Estado", type="nominal", scale=color_scale_pie, legend=alt.Legend(title="Estado", orient="right")),
                                tooltip=['Estado', 'Cantidad']
                            ).interactive()
                            st.altair_chart(dona_chart, use_container_width=True)

                    with col_insp:
                        # MARCO 3: Productividad
                        with st.container(border=True):
                            st.markdown("**👷 Inspecciones por Personal**")
                            insp_counts = df_graf['Inspector'].value_counts().reset_index()
                            insp_counts.columns = ['Inspector', 'Postes']
                            
                            bar_insp = alt.Chart(insp_counts).mark_bar(color='#01305D').encode(
                                x=alt.X('Postes:Q', title='Nº de Postes'),
                                y=alt.Y('Inspector:N', sort='-x', title=''),
                                tooltip=['Inspector', 'Postes']
                            ).interactive()
                            st.altair_chart(bar_insp, use_container_width=True)

                    st.write("") 
                    col_g1, col_g2 = st.columns(2)
                    
                    with col_g1:
                        # MARCO 4: Top Fallas
                        with st.container(border=True):
                            st.markdown("**📉 Top Componentes con Problemas**")
                            df_problemas = df_melt[df_melt["Estado"].isin(["A", "M"])]
                            if not df_problemas.empty:
                                conteo_prob = df_problemas.groupby("Componente").size().reset_index(name="Fallas")
                                bar_chart = alt.Chart(conteo_prob).mark_bar(color='#CC0000').encode(
                                    x=alt.X('Fallas:Q', title='Nº de Observaciones'),
                                    y=alt.Y('Componente:N', sort='-x', title=''),
                                    tooltip=['Componente', 'Fallas']
                                ).interactive()
                                st.altair_chart(bar_chart, use_container_width=True)
                            else:
                                st.success("✅ No se detectaron fallas 'Alto' o 'Medio'.")

                    with col_g2:
                        # MARCO 5: Desglose por Componente
                        with st.container(border=True):
                            st.markdown("**📊 Desglose de Estado por Componente**")
                            if not df_melt.empty:
                                stacked_bar = alt.Chart(df_melt).mark_bar().encode(
                                    x=alt.X('count():Q', title='Cantidad de Obs.'),
                                    y=alt.Y('Componente:N', sort='-x', title=''),
                                    color=alt.Color('Estado:N', scale=color_scale_pie, legend=alt.Legend(title="Estado", orient="bottom")),
                                    tooltip=[alt.Tooltip('Componente'), alt.Tooltip('Estado'), alt.Tooltip('count()', title='Cantidad')]
                                ).interactive()
                                st.altair_chart(stacked_bar, use_container_width=True)
                pass
                
            with sub_pdf:

                def generar_reporte_pdf(df_filtrado, camp, zona_sel, der_sel, comps):
                    pdf = FPDF(orientation='P', unit='mm', format='A4')
                    pdf.set_margins(left=15, top=15, right=15)
                    pdf.add_page()
                    colores_rgb = {
                        'A': (204, 0, 0),    # Rojo
                        'M': (230, 126, 34), # Naranja
                        'B': (46, 125, 50),   # Verde
                        'NT': (127, 140, 141),# Gris
                        'DEFAULT': (0, 0, 0)  # Negro
                    }
                    # 1. ENCABEZADO
                    pdf.set_font("Arial", "B", 16)
                    pdf.set_text_color(1, 48, 93)
                    pdf.cell(0, 10, "REPORTE TECNICO DE INSPECCION DE LINEAS", ln=True, align='C')
                    
                    pdf.set_font("Arial", "", 10)
                    pdf.set_text_color(0, 0, 0)
                    pdf.cell(0, 7, f"Campaña: {camp} | Zona: {zona_sel} | Derivación: {der_sel}", ln=True, align='C')
                    pdf.ln(5)

                
                    # ==========================================
                    # 2. SECCIÓN DE GRÁFICOS Y TABLAS RESUMEN
                    # ==========================================
                    pdf.set_font("Arial", "B", 12)
                    pdf.cell(0, 10, "1. RESUMEN ESTADISTICO DE INSPECCION", ln=True)
                    
                    df_melt_pdf = df_filtrado.melt(value_vars=comps, value_name="Estado")
                    df_melt_pdf = df_melt_pdf[df_melt_pdf["Estado"].isin(["A", "M", "B", "NT"])]
                    
                    if not df_melt_pdf.empty:
                        # --- GENERACIÓN DE IMAGEN ---
                        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
                        
                        # Dona de Salud
                        counts = df_melt_pdf['Estado'].value_counts()
                        c_list = [colores_rgb.get(x, (200,200,200)) for x in counts.index]
                        ax1.pie(counts, labels=counts.index, colors=[(r/255, g/255, b/255) for r,g,b in c_list])
                        ax1.set_title("Salud General de Componentes", fontweight='bold', fontsize=10)
                        
                        # Top Fallas
                        df_probs = df_melt_pdf[df_melt_pdf["Estado"].isin(["A", "M"])]
                        if not df_probs.empty:
                            prob_counts = df_probs.groupby("variable").size().sort_values()
                            ax2.barh(prob_counts.index, prob_counts.values, color='#CC0000')
                            ax2.set_title("Fallas Detectadas (A/M)", fontweight='bold', fontsize=10)
                        else:
                            ax2.text(0.5, 0.5, "Sin fallas criticas", ha='center', va='center')
                            ax2.axis('off')

                        plt.tight_layout()
                        img_buf = io.BytesIO()
                        plt.savefig(img_buf, format='png', dpi=120)
                        plt.close(fig)
                        
                        # Insertar Gráficos
                        y_grafico = pdf.get_y()
                        pdf.image(img_buf, x=15, y=y_grafico, w=180)
                        pdf.set_y(y_grafico + 75) # Bajamos el cursor debajo de los dibujos

                        # --- TABLAS DE DATOS (DEBAJO DE LOS GRÁFICOS) ---
                        pdf.set_font("Arial", "B", 8)
                        y_tablas = pdf.get_y()
                        
                        # Tabla Izquierda (Resumen de Estados)
                        pdf.set_x(25)
                        pdf.cell(40, 6, "Estado", 1, 0, 'C', fill=True)
                        pdf.cell(20, 6, "Cant.", 1, 1, 'C', fill=True)
                        pdf.set_font("Arial", "", 8)
                        for est, cant in counts.items():
                            pdf.set_x(25)
                            pdf.cell(40, 5, f"Condicion {est}", 1, 0, 'L')
                            pdf.cell(20, 5, str(cant), 1, 1, 'C')

                        # Tabla Derecha (Ranking de Fallas) - La posicionamos al costado
                        if not df_probs.empty:
                            pdf.set_y(y_tablas) # Volvemos arriba de la seccion de tablas
                            pdf.set_font("Arial", "B", 8)
                            pdf.set_x(115) # Movemos a la derecha
                            pdf.cell(50, 6, "Componente Critico", 1, 0, 'C', fill=True)
                            pdf.cell(20, 6, "Fallas", 1, 1, 'C', fill=True)
                            pdf.set_font("Arial", "", 8)
                            for comp_f, cant_f in prob_counts.sort_values(ascending=False).items():
                                pdf.set_x(115)
                                pdf.cell(50, 5, str(comp_f), 1, 0, 'L')
                                pdf.cell(20, 5, str(cant_f), 1, 1, 'C')
                        
                        pdf.set_y(pdf.get_y() + 10) # Espacio antes del detalle de activos
                    else:
                        pdf.set_font("Arial", "I", 10)
                        pdf.cell(0, 10, "No hay datos suficientes para generar estadísticas.", ln=True)

                    pdf.ln(5)

                    # ==========================================
                    # 3. DETALLE DE HALLAZGOS Y ACTIVIDADES
                    # ==========================================
                    pdf.add_page()
                    pdf.set_font("Arial", "B", 14)
                    pdf.set_text_color(0, 0, 0)
                    pdf.cell(0, 10, "2. DETALLE POR ACTIVO", ln=True)
                    pdf.ln(3)

                    # Filtrar solo postes que tengan datos reales
                    df_hallazgos = df_filtrado[df_filtrado["Obs_Final"].astype(str).str.strip() != ""].copy()

                    for _, fila in df_hallazgos.iterrows():
                        # Control de salto de página: si queda menos de 5cm, página nueva
                        if pdf.get_y() > 240:
                            pdf.add_page()

                        # --- BARRA DE TÍTULO (AZUL) ---
                        pdf.set_fill_color(1, 48, 93)
                        pdf.set_text_color(255, 255, 255)
                        pdf.set_font("Arial", "B", 10)
                        
                        # Concatenamos Poste y Derivación en una sola línea ancha
                        info_cab = f" POSTE: {fila['Poste']} | DERIVACION: {fila.get('Derivación', 'N/A')}"
                        # multi_cell con ancho 0 ocupa todo el ancho y hace salto de línea automático
                        pdf.multi_cell(0, 8, info_cab, fill=True, align='L')
                        
                        # FORZAMOS SALTO DE LÍNEA DESPUÉS DE LA BARRA
                        pdf.set_y(pdf.get_y() + 2) 

                        # --- FUNCIÓN DE ESCRITURA BLINDADA ---
                        def escribir_seccion_segura(titulo, texto_campo):
                            if not str(texto_campo).strip() or str(texto_campo).lower() == "nan":
                                return
                            
                            # Título de la sección (Hallazgos o Actividades)
                            pdf.set_x(15) # Aseguramos margen izquierdo
                            pdf.set_text_color(0, 0, 0)
                            pdf.set_font("Arial", "B", 9)
                            pdf.cell(0, 6, titulo, ln=True) # ln=True obliga a bajar al siguiente renglón
                            
                            pdf.set_font("Arial", "", 8)
                            # Limpieza de caracteres prohibidos
                            texto_limpio = str(texto_campo).replace("•", "-").replace("\u2022", "-")
                            
                            for linea in texto_limpio.split('\n'):
                                linea_s = linea.strip()
                                if linea_s:
                                    # Lógica de colores por componente
                                    color_linea = (0, 0, 0) # Negro por defecto
                                    for cp in comps:
                                        if cp.lower() in linea_s.lower():
                                            # Obtenemos el estado (A, M, B) para pintar
                                            est_val = str(fila.get(cp, 'B')).upper()
                                            color_linea = colores_rgb.get(est_val, (0, 0, 0))
                                            break
                                    
                                    pdf.set_text_color(*color_linea)
                                    pdf.set_x(20) # Indentación (sangría)
                                    
                                    # ESCRIBIMOS LA LÍNEA
                                    # Usamos un ancho de 180 (seguro) y ln=True para que la siguiente línea vaya ABAJO
                                    pdf.multi_cell(0, 5, f"- {linea_s}", align='L')
                                    # Reseteo manual de X por seguridad
                                    pdf.set_x(15) 
                            
                            pdf.ln(2) # Espacio al terminar la sección

                        # Llamamos a las secciones
                        escribir_seccion_segura("[-] Hallazgos:", fila['Obs_Final'])
                        escribir_seccion_segura("[>] Actividades:", fila['Act_Final'])
                        
                        # Línea divisoria entre postes
                        pdf.set_draw_color(220, 220, 220)
                        pdf.line(15, pdf.get_y(), 195, pdf.get_y())
                        pdf.ln(5)

                    return bytes(pdf.output())

                # BOTÓN DE DESCARGA EN INTERFAZ (MEJORADO)
                # ==========================================
                # --- En tu Tab 1, desplázate hasta el final de la pestaña ---
                st.divider()
                st.subheader("📄 Generación de Reporte Técnico Oficial (PDF)")
                st.caption("Este documento incluye resumen ejecutivo, analítica visual mejorada con flechas y desglose técnico agrupado por sub-sistema.")

                # Usamos columnas para centrar el botón y hacerlo ver mejor
                c_pdf1, c_pdf2, c_pdf3 = st.columns([1, 2, 1])

                with c_pdf2:
                    if st.button("🛠️ Preparar Documento de Inspección PDF", type="secondary", use_container_width=True):
                        with st.spinner("Compilando datos, generando gráficos con flechas y formateando tabla agrupada..."):
                            try:
                                # OJO: Usamos df_master total y df_f filtrado para pasar a la función
                                # También le pasamos los textos de los selectores (camp_f, zona_f, der_f)
                                pdf_bytes = generar_reporte_pdf(df_f, camp_f, zona_f, der_f, comps_l)
                                
                                # Guardamos los bytes en session_state para que no se borren en el siguiente rerun
                                st.session_state.pdf_oficial_ready = pdf_bytes
                                st.success("✅ Documento PDF listo para descarga.")
                            except Exception as e:
                                st.error(f"Error técnico al generar el PDF: {e}")
                                st.error("Verifica que las columnas 'Latitud', 'Longitud', 'Obs_Final' y 'Act_Final' existan en la base de datos.")

                    # Si el PDF ya está listo, mostramos el botón de descarga verde
                    if "pdf_oficial_ready" in st.session_state:
                        st.write("")
                        st.download_button(
                            label="📥 Descargar Reporte de Inspección PDF",
                            data=st.session_state.pdf_oficial_ready,
                            file_name=f"Reporte_Tecnico_{zona_f}_{camp_f}.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                            type="primary" # Botón verde
                        )
                pass
                


            with sub_mapa:
                # 5. MAPA DE CRITICIDAD GEOREFERENCIADO
                st.divider()
                st.subheader("🗺️ Mapa de calor")
        
                if "Latitud" in df_f.columns and "Longitud" in df_f.columns:
                    df_map = df_f.copy()
                    df_map['lat'] = pd.to_numeric(df_map['Latitud'], errors='coerce')
                    df_map['lon'] = pd.to_numeric(df_map['Longitud'], errors='coerce')
                    df_map = df_map.dropna(subset=['lat', 'lon'])
                    df_map = df_map[(df_map['lat'] != 0) & (df_map['lon'] != 0)]

                    if not df_map.empty:
                        # --- TOOLBOX DE COMPONENTES ---
                        with st.expander("🛠️ Toolbox: Filtros de Capas del Mapa", expanded=True):
                            col_t1, col_t2 = st.columns([2, 1])
                            with col_t1:
                                componentes_visibles = st.multiselect(
                                    "Selecciona componentes para evaluar riesgo:",
                                    options=comps_l,
                                    default=[],
                                    help="El mapa calculará el color basado solo en los componentes seleccionados."
                                )
                            with col_t2:
                                estilo_mapa = st.selectbox(
                                    "Estilo del Mapa:",
                                    options=["satellite", "road", "dark", "light"],
                                    index=0
                                )

                        # --- LÓGICA DE CRITICIDAD DINÁMICA ---
                        def calcular_riesgo_selectivo(row):
                            peso = 0
                            detalles_criticos = []
                            for c in componentes_visibles:
                                estado = str(row.get(c, "B")).upper()
                                if estado == 'A': 
                                    peso += 10
                                    detalles_criticos.append(f"🔴 {c} (Crítico)")
                                elif estado == 'M': 
                                    peso += 3
                                    detalles_criticos.append(f"🟠 {c} (Medio)")
                            return pd.Series([peso, "<br>".join(detalles_criticos) if detalles_criticos else "✅ Sin fallas en selección"])

                        # Aplicamos el cálculo solo sobre lo que el usuario eligió en el Toolbox
                        df_map[['Riesgo_Total', 'Detalle_HTML']] = df_map.apply(calcular_riesgo_selectivo, axis=1)

                        # Asignación de colores (RGBA)
                        def color_dinamico(peso):
                            if peso >= 10: return [255, 0, 0, 200]    # Rojo (Falla crítica en selección)
                            if peso >= 3: return [255, 165, 0, 200]  # Naranja (Falla media en selección)
                            return [0, 255, 0, 150]                 # Verde (Todo OK en selección)

                        df_map['color_punto'] = df_map['Riesgo_Total'].apply(color_dinamico)

                        # --- CONFIGURACIÓN DEL DECK (MAPA) ---
                        # Usamos estilos de Mapbox que simulan Google Maps (Satellite)
                        # Nota: 'satellite' es muy útil para ver la ubicación real de las torres en la mina
                        map_style_url = f"mapbox://styles/mapbox/{estilo_mapa}-v9" if estilo_mapa != "road" else None

                        # --- CONFIGURACIÓN DEL MAPA CON FOLIUM (100% GRATIS) ---
                        # Usamos el satélite de ESRI que no requiere llaves ni tokens
                        esri_tiles = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
                
                        # 1. FIX DEL ZOOM: Agregamos max_zoom=17 para que no se borre el satélite
                        m = folium.Map(
                            location=[df_map['lat'].mean(), df_map['lon'].mean()],
                            zoom_start=15,
                            max_zoom=17, # 👈 Tope de seguridad
                            tiles=esri_tiles,
                            attr='Esri World Imagery'
                        )

                        # 2. VERDADERO MAPA DE CALOR (Las manchas difuminadas)
                        # Filtramos solo los postes que tienen algún riesgo según el Toolbox
                        df_calor = df_map[df_map['Riesgo_Total'] > 0]
                        if not df_calor.empty:
                            # Folium HeatMap pide una lista de [Latitud, Longitud, Peso/Criticidad]
                            datos_calor = df_calor[['lat', 'lon', 'Riesgo_Total']].values.tolist()
                            
                            HeatMap(
                                datos_calor,
                                radius=25,     # Tamaño de la mancha de calor
                                blur=15,       # Nivel de difuminado
                                max_zoom=17,
                                min_opacity=0.4
                            ).add_to(m)

                        # 3. PUNTOS INTERACTIVOS (Para poder hacer clic y leer el reporte)
                        for _, row in df_map.iterrows():
                            # Hacemos los círculos más pequeños y oscuros para que resalten sobre el mapa de calor
                            color_borde = 'white' if row['Riesgo_Total'] >= 10 else 'black'
                            
                            tooltip_html = f"""
                                <div style='font-family: Arial; font-size: 12px;'>
                                    <b>Poste:</b> {row['Poste']} <br/>
                                    <b>Derivación:</b> {row['Derivación']} <br/>
                                    <hr style='margin: 4px 0;'/>
                                    <b>Hallazgos:</b><br/>
                                    {row['Detalle_HTML']}
                                </div>
                            """

                            folium.CircleMarker(
                                location=[row['lat'], row['lon']],
                                radius=4, # Círculo más pequeño porque la mancha de calor ya indica el área
                                color=color_borde,
                                weight=1,
                                fill=True,
                                fill_color='black',
                                fill_opacity=0.6,
                                tooltip=folium.Tooltip(tooltip_html)
                            ).add_to(m)

                        # Renderizamos el mapa en Streamlit
                        st_folium(m, use_container_width=True, height=600)
                    else:
                        st.warning("📍 No hay coordenadas para mostrar en el mapa.")
                else:
                    st.info("💡 Asegúrate de que los datos tengan columnas de Latitud y Longitud.")
                pass
        else:
            st.info("⬆️ Selecciona y descarga al menos una campaña en el panel superior para comenzar.")


    with tab2:
        st.header("Dashboard Técnico de Gensets")
        df_g = st.session_state.df_genset
        if not df_g.empty:
            g1, g2 = st.columns(2)
            
            tipos = [x for x in df_g["Tipo"].unique() if x.strip() and x.upper() != "NO DEFINIDO"]
            with g1: g_tipo = st.selectbox("Tipo de Genset:", ["TODOS"] + sorted(tipos))
            df_gt = df_g if g_tipo == "TODOS" else df_g[df_g["Tipo"] == g_tipo]
            
            equipos = [x for x in df_gt["Equipo"].unique() if x.strip()]
            with g2: g_sel = st.selectbox("Seleccione Equipo:", sorted(equipos))
            
            if g_sel:
                df_h = df_gt[df_gt["Equipo"] == g_sel].sort_values(by="Fecha", ascending=False).head(10)
                
                # 1. Función para convertir texto a número para la gráfica
                def nivel_a_numero(texto):
                    if not texto: return None
                    t = str(texto).strip().upper()
                    
                    mapa = {
                        "FULL": 1.0, "3/4": 0.75, "1/2": 0.50, "1/4": 0.25, "VACÍO": 0.0, "VACIO": 0.0,
                        "LIMPIO": 1.0, "SUCIO": 0.25, 
                        "OPERATIVO": 1.0, "INOPERATIVO": 0.0,
                        "TIENE": 1.0, "NO TIENE": 0.0,
                        "BUENO": 1.0, "MALO": 0.0, "REGULAR": 0.50
                    }
                    return mapa.get(t, None)

                df_h['Nivel Combustible'] = df_h['Combustible'].apply(nivel_a_numero)
                df_h['Nivel Aceite'] = df_h['Aceite Motor'].apply(nivel_a_numero)
                df_h['Nivel Refrigerante'] = df_h['Refrigerante'].apply(nivel_a_numero)
                
                st.subheader(f"📈 Uso, Estado Operativo y Niveles")
                
                col_t1, col_t2, col_t3, col_t4 = st.columns(4)
                with col_t1: ver_horometro = st.toggle("⏱️ Horómetro", value=True)
                with col_t2: ver_combustible = st.toggle("⛽ Combustible", value=True)
                with col_t3: ver_aceite = st.toggle("🛢️ Aceite", value=True)
                with col_t4: ver_refrigerante = st.toggle("❄️ Refrigerante", value=True)
                
                base = alt.Chart(df_h).encode(x=alt.X('Fecha:T', title='Fecha de Inspección'))
                
                capas_activas = []
                
                if ver_horometro:
                    linea_horometro = base.mark_line(color='#01305D', strokeWidth=3).encode(
                        y=alt.Y('Horómetro:Q', title='Horómetro', scale=alt.Scale(zero=False))
                    )
                    puntos = base.mark_circle(size=120, opacity=1).encode(
                        y=alt.Y('Horómetro:Q'),
                        color=alt.Color('Estado_Op:N', 
                                        scale=alt.Scale(
                                            domain=['Operativo', 'Inoperativo'],
                                            range=['#28a745', '#dc3545']
                                        ),
                                        legend=None
                                       ),
                        tooltip=[alt.Tooltip('Fecha:T', format='%d/%m/%Y %H:%M'), 'Horómetro', 'Estado_Op', 'Combustible', 'Aceite Motor', 'Refrigerante', 'Inspector']
                    )
                    capas_activas.append(linea_horometro + puntos)
                
                fluidos_seleccionados = []
                if ver_combustible: fluidos_seleccionados.append('Nivel Combustible')
                if ver_aceite: fluidos_seleccionados.append('Nivel Aceite')
                if ver_refrigerante: fluidos_seleccionados.append('Nivel Refrigerante')
                
                if fluidos_seleccionados:
                    dominio_fluidos = ['Nivel Combustible', 'Nivel Aceite', 'Nivel Refrigerante']
                    rango_colores = ['#f39c12', '#8e44ad', '#3498db']
                    
                    lineas_fluidos = base.transform_fold(
                        fluidos_seleccionados,
                        as_=['Tipo de Fluido', 'Nivel']
                    ).mark_line(strokeWidth=2, strokeDash=[5,5]).encode(
                        y=alt.Y('Nivel:Q', title='Nivel de Fluidos (0 a 1)', scale=alt.Scale(domain=[0, 1.1])),
                        color=alt.Color('Tipo de Fluido:N', 
                                        scale=alt.Scale(domain=dominio_fluidos, range=rango_colores),
                                        legend=alt.Legend(orient='bottom', title="Simbología de Fluidos")
                                       )
                    )
                    capas_activas.append(lineas_fluidos)
                
                if capas_activas:
                    if len(capas_activas) == 2:
                        grafico_final = alt.layer(*capas_activas).resolve_scale(
                            y='independent',
                            color='independent'  
                        ).interactive()
                    else:
                        grafico_final = capas_activas[0].interactive()
                        
                    st.altair_chart(grafico_final, use_container_width=True)
                else:
                    st.warning("⚠️ Activa al menos una capa para visualizar la gráfica.")
                st.divider()
                st.subheader(f"📊 Matriz de Inspección: {g_sel}")
                
                meta_cols = ["Tipo", "Equipo", "Fecha", "Horómetro", "Inspector", "Zona", "Estado_Op", "Nivel Combustible", "Nivel Aceite", "Nivel Refrigerante"]
                tech_cols = [c for c in df_h.columns if c not in meta_cols]
                
                if tech_cols:
                    df_tech = df_h[["Fecha"] + tech_cols].copy()
                    df_tech["Fecha_Str"] = df_tech["Fecha"].dt.strftime('%d/%m %H:%M:%S')
                    df_tech = df_tech.drop_duplicates(subset=["Fecha_Str"], keep='first')
                    df_tech = df_tech.drop(columns=["Fecha"]).set_index("Fecha_Str")
                    
                    df_transposed = df_tech.T
                    
                    orden_presente = [col for col in ORDEN_EXACTO_GENSET if col in df_transposed.index]
                    otros = [col for col in df_transposed.index if col not in ORDEN_EXACTO_GENSET]
                    df_transposed = df_transposed.loc[orden_presente + otros]
                    
                    st.dataframe(df_transposed.style.map(color_estado), use_container_width=True)
            
                out_g = BytesIO()
                with pd.ExcelWriter(out_g, engine='openpyxl') as writer:
                    df_ex_g = df_h.drop(columns=["Nivel Combustible", "Nivel Aceite", "Nivel Refrigerante"]).copy()
                    if 'Fecha' in df_ex_g.columns: df_ex_g['Fecha'] = df_ex_g['Fecha'].dt.tz_localize(None)
                    df_ex_g.to_excel(writer, index=False)
                st.download_button(f"📥 Descargar Historial {g_sel}", out_g.getvalue(), f"Historial_{g_sel}.xlsx")
        else:
            st.info("⬆️ Dale clic a 'Descargar Seleccionadas' arriba para traer el historial de Gensets.")

    with tab3:
        st.header("Comparativa de Evolución (Líneas)")
        df_l = st.session_state.df_master
        if not df_l.empty:
            camps_list = sorted(df_l["Campaña"].unique().tolist())
            if len(camps_list) >= 2:
                col_a, col_b = st.columns(2)
                with col_a: c1_s = st.selectbox("Campaña Base (A):", camps_list)
                with col_b: c2_s = st.selectbox("Campaña Reciente (B):", sorted(camps_list, reverse=True))
                
                comunes = sorted(list(set(df_l[df_l["Campaña"]==c1_s]["Poste"]) & set(df_l[df_l["Campaña"]==c2_s]["Poste"])))
                if comunes:
                    p_s = st.selectbox("Seleccione Poste a comparar:", comunes)
                    r1 = df_l[(df_l["Poste"]==p_s) & (df_l["Campaña"]==c1_s)].iloc[0]
                    r2 = df_l[(df_l["Poste"]==p_s) & (df_l["Campaña"]==c2_s)].iloc[0]
                    
                    st.divider()
                    st.subheader(f"Comparación Técnica - Poste: {p_s}")
                    
                    comps_l = ["Estructura", "Aislador", "Cable", "Drenaje", "Ferreteria", "Guarda", "Inclinacion", "PAT", "Pararrayos", "Retenida", "Seccionador","Señalética","Otros"]
                    comp_data = []
                    for cp in comps_l:
                        comp_data.append({
                            "Componente": cp,
                            f"Estado {c1_s}": r1[cp],
                            f"Estado {c2_s}": r2[cp],
                            f"Obs. {c1_s}": r1[f"obs_{cp}"],
                            f"Obs. {c2_s}": r2[f"obs_{cp}"]
                        })
                    
                    df_comp = pd.DataFrame(comp_data)
                    st.dataframe(df_comp.style.map(color_estado, subset=[f"Estado {c1_s}", f"Estado {c2_s}"]), use_container_width=True, hide_index=True)
            else:
                st.info("Sincroniza al menos 2 campañas para comparar evolución.")
        else:
            st.info("⬆️ Necesitas descargar campañas primero para usar la comparativa.")