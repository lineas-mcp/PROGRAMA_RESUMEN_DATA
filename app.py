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
# ==========================================
# 1. CONFIGURACIÓN Y ESTILO JSJSJSJS
# ==========================================
st.set_page_config(page_title="Chinalco - Control de Mantenimiento", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #FFFFFF; }
    h1, h2, h3 { color: #01305D; border-bottom: 2px solid #01305D; padding-bottom: 10px; }
    .stTabs [aria-selected="true"] { background-color: #01305D !important; color: white !important; font-weight: bold; }
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
                # Extraemos los secretos a un diccionario mutable
                creds_dict = dict(st.secrets["firebase"])
                
                # --- LIMPIEZA DE LLAVE PRIVADA ---
                raw_key = creds_dict["private_key"]
                
                # 1. Si la llave tiene los caracteres '\' y 'n' literales, los convertimos a saltos reales
                if "\\n" in raw_key:
                    clean_key = raw_key.replace("\\n", "\n")
                else:
                    # 2. Si ya tiene saltos reales pero quizás espacios extra por el formato TOML, 
                    # aseguramos que las líneas estén limpias
                    clean_key = raw_key.strip()
                
                creds_dict["private_key"] = clean_key
                
                cred = credentials.Certificate(creds_dict)
            else:
                # Caso local con archivo físico
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
    
    if not texto: 
        return res | obs_dict | act_dict | {"Obs_Final": "", "Act_Final": ""}

    bloques = re.findall(r'\[(.*?)\]', texto)
    resumen_obs = []
    resumen_act = []
    
    # Filtros de exclusión total (Cualquier cosa que contenga esto se borra)
    omitir = ["", "N/A", "NINGUNA", "SIN OBS", "SIN OBSERVACION", "SIN OBSERVACIONES", "SIN ACT", "SIN ACTIVIDAD"]
    conv = {"ALTO": "A", "MEDIO": "M", "BAJO": "B", "BUENO": "B", "REGULAR": "M", "MALO": "A", "NT": "NT"}

    for b in bloques:
        p = b.split(" | ")
        if len(p) >= 2:
            c_nom = p[0].strip()
            if c_nom in res:
                # 1. Estado (A, M, B...)
                res[c_nom] = conv.get(p[1].strip().upper(), p[1].strip().upper())
                
                # 2. Extraer Observación (p[2])
                if len(p) >= 3:
                    obs_val = p[2].strip()
                    # FILTRO: Si es un mensaje de FOTO o está en omitir, no entra
                    if obs_val.upper() not in omitir and "FOTO:" not in obs_val.upper():
                        obs_dict[f"obs_{c_nom}"] = obs_val
                        resumen_obs.append(f"• {c_nom}: {obs_val}")
                
                # 3. Extraer Actividad (p[3])
                if len(p) >= 4:
                    act_val = p[3].replace("ACT:", "").strip()
                    # FILTRO: Si es un mensaje de FOTO o está en omitir, no entra
                    if act_val.upper() not in omitir and "FOTO:" not in act_val.upper():
                        act_dict[f"act_{c_nom}"] = act_val
                        resumen_act.append(f"• {c_nom}: {act_val}")

    # Columnas finales de resumen totalmente limpias
    res["Obs_Final"] = "\n".join(resumen_obs)
    res["Act_Final"] = "\n".join(resumen_act)
    
    return res | obs_dict | act_dict

def color_estado(val):
    if isinstance(val, str):
        v = val.strip().upper()
        # Colores Líneas
        if v == "A": return 'background-color: #FFDADA; color: #CC0000; font-weight: bold; text-align: center;'
        if v == "M": return 'background-color: #FFF4E5; color: #E67E22; font-weight: bold; text-align: center;'
        if v == "NT": return 'background-color: #FFF4E5; color: #E67E22; font-weight: bold; text-align: center;'
        if v == "B": return 'background-color: #E8F5E9; color: #2E7D32; font-weight: bold; text-align: center;'
        
        # Colores Genset
        if v in ["CAMBIAR", "INOPERATIVO", "VACÍO", "1/4", "SUCIO"]: 
            return 'background-color: #FFDADA; color: #CC0000; font-weight: bold; text-align: left;'
        if v in ["NO TIENE", "1/2", "STAND BY"]: 
            return 'background-color: #FFF4E5; color: #E67E22; font-weight: bold; text-align: left;'
        if v in ["TIENE", "OPERATIVO", "FULL", "3/4", "LIMPIO", "TRABAJANDO", "INSPECCIÓN", "INSPECCION Y ARRANQUE"]: 
            return 'background-color: #E8F5E9; color: #2E7D32; font-weight: bold; text-align: left;'
    return ''

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
st.title("🏔️ Gestión de Activos - Toromocho")

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
        
        with c1:
            seleccionados = st.multiselect("Agregar nuevas campañas a la memoria:", camps_pendientes)
        
        # Variables de control para unificar la descarga
        ejecutar_descarga = False
        campanas_a_descargar = []

        with c2:
            if st.button("📥 Descargar Sel.", use_container_width=True):
                if seleccionados or not st.session_state.gensets_descargados:
                    ejecutar_descarga = True
                    campanas_a_descargar = seleccionados
                else:
                    st.info("Selecciona una campaña de la lista.")
                    
        with c3:
            # Opción 1: Buscar nuevas inspecciones en la nube
            if st.button("🔄 Buscar Nuevas", use_container_width=True):
                obtener_campanas.clear() # Limpia la caché de la función
                st.rerun()
                
        with c4:
            # Opción 2: Descargar de golpe todo lo que falta
            if st.button("⚡ Descargar Faltantes", use_container_width=True):
                if camps_pendientes or not st.session_state.gensets_descargados:
                    ejecutar_descarga = True
                    campanas_a_descargar = camps_pendientes
                else:
                    st.info("Ya tienes todas las campañas descargadas.")

        # Botón general para vaciar la memoria (fuera de las columnas para más limpieza visual)
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
            with st.spinner("Sincronizando con Firebase... (Solo lo necesario)"):
                
                # 1. ACUMULAR NUEVAS LÍNEAS
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
                                "Fecha": dt, 
                                "Zona": d.get("zona", "N/A").strip(), 
                                "Derivación": d.get("equipo", "N/A").strip(), 
                                "Poste": d.get("poste"),
                                "Latitud": d.get("latitud"),   
                                "Longitud": d.get("longitud")  
                            }
                            row.update(info)
                            data_l.append(row)
                    
                    nuevo_df_l = pd.DataFrame(data_l)
                    st.session_state.df_master = pd.concat([st.session_state.df_master, nuevo_df_l], ignore_index=True)
                    st.session_state.campanas_descargadas.extend(campanas_a_descargar)

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
            
            with c3: der_f = st.selectbox("Derivación:", ["TODAS"] + sorted(df_f["Derivación"].unique().tolist()))
            df_f = df_f[df_f["Derivación"] == der_f] if der_f != "TODAS" else df_f
            
            comps_l = ["Estructura", "Aislador", "Cable", "Drenaje", "Ferreteria", "Guarda", "Inclinacion", "PAT", "Pararrayos", "Retenida", "Seccionador","Señalética","Otros"]
            
            cols_visibles = ["Campaña", "Zona", "Derivación", "Inspector", "Poste"] + comps_l + ["Obs_Final", "Act_Final"]
            
            st.info("💡 Ahora puedes editar la **Campaña** o el **Poste** directamente en la tabla. El sistema usa el ID interno para no perder el rastro.")

            editor_key = f"ed_lin_{camp_f}"
            df_con_estilo = df_f[["ID_Doc"] + cols_visibles].style.applymap(color_estado, subset=comps_l)
            
            df_editado = st.data_editor(
                df_con_estilo, 
                column_config={
                    "ID_Doc": st.column_config.TextColumn("ID Documento", disabled=True),
                    "Campaña": st.column_config.TextColumn("Campaña", help="Puedes mover este registro a otra campaña")
                },
                use_container_width=True, 
                hide_index=True,
                key=editor_key
            )

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
                        with st.spinner("Actualizando Firebase..."):
                            for id_f, f_orig, f_mods in validos_para_subir:
                                update_dict = {}
                                if "Campaña" in f_mods: update_dict["campana"] = f_mods["Campaña"]
                                if "Inspector" in f_mods: update_dict["inspector"] = f_mods["Inspector"]
                                if "Zona" in f_mods: update_dict["zona"] = f_mods["Zona"]
                                if "Derivación" in f_mods: update_dict["equipo"] = f_mods["Derivación"]
                                if "Poste" in f_mods: update_dict["poste"] = f_mods["Poste"]
                                
                                if any(c in f_mods for c in comps_l):
                                    f_nueva = f_orig.copy()
                                    for c, v in f_mods.items(): f_nueva[c] = v
                                    
                                    detalles_lista = []
                                    for cp in comps_l:
                                        est = f_nueva.get(cp, "N/A")
                                        obs = str(f_nueva.get(f"obs_{cp}", "")).strip()
                                        act = str(f_nueva.get(f"act_{cp}", "")).strip()
                                        if pd.notna(est) and est != "N/A":
                                            p = f"[{cp} | {est}"
                                            if obs and obs not in ["nan", "None", ""]: p += f" | {obs}"
                                            if act and act not in ["nan", "None", ""]: p += f" | ACT: {act}"
                                            p += "]"
                                            detalles_lista.append(p)
                                    update_dict["detalles_tecnicos"] = " ".join(detalles_lista)

                                try:
                                    db.collection("reportes_inspeccion_lineas").document(id_f).update(update_dict)
                                
                                    idx_master = st.session_state.df_master[st.session_state.df_master["ID_Doc"] == id_f].index
                                    for col_m, val_m in f_mods.items():
                                        st.session_state.df_master.loc[idx_master, col_m] = val_m
                                except Exception as e:
                                    st.error(f"Error al actualizar {id_f}: {e}")

                            st.success("✅ Firebase y Memoria Local sincronizados.")
                            del st.session_state[editor_key]
                            st.rerun()

                with c_btn2:
                    if st.button("🚩 Cancelar Edición", use_container_width=True):
                        st.rerun()
            
            st.divider()
            
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
            st.divider()
            
            # Texto dinámico reflejando los filtros exactos
            st.subheader(f"📊 Analítica de Inspección: {camp_f}")
            st.markdown(f"**Filtros aplicados:** Zona: `{zona_f}` | Derivación: `{der_f}` | **Postes en pantalla:** `{len(df_f)}`")
            
            if not df_f.empty:
                # 1. PREPARACIÓN DE DATOS MAESTROS
                df_graf = df_f[["Poste", "Inspector"] + comps_l].copy()
                df_melt = df_graf.melt(id_vars=["Poste", "Inspector"], value_vars=comps_l, var_name="Componente", value_name="Estado")
                df_melt = df_melt[df_melt["Estado"].isin(["A", "M", "B", "NT"])] # Filtrar valores válidos

                # 2. TARJETAS DE INDICADORES (KPIs)
                st.markdown("### 🎯 Indicadores Clave de Riesgo (KPIs)")
                kpi1, kpi2, kpi3, kpi4 = st.columns(4)
                
                # Cálculos rápidos
                total_postes = len(df_graf)
                # Un poste es crítico si tiene al menos UN componente en 'A'
                postes_criticos = df_graf[comps_l].apply(lambda row: 'A' in row.values, axis=1).sum() 
                fallas_a = len(df_melt[df_melt["Estado"] == 'A'])
                fallas_m = len(df_melt[df_melt["Estado"] == 'M'])
                
                kpi1.metric("📌 Total Postes Revisados", total_postes)
                kpi2.metric("🚨 Postes en Riesgo", postes_criticos)
                kpi3.metric("🔴 Fallas Críticas", fallas_a)
                kpi4.metric("🟠 Fallas Medias", fallas_m)
                
                st.divider()

                # 3. FILA DE GRÁFICOS: DONA Y PRODUCTIVIDAD
                col_dona, col_insp = st.columns(2)
                
                with col_dona:
                    st.markdown("**🍩 Distribución de Salud General de la línea**")
                    st.caption("Proporción de estados evaluados en todos los componentes.")
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
                    st.markdown("**👷 Inspecciones por Personal**")
                    st.caption("Cantidad de postes reportados por cada inspector.")
                    insp_counts = df_graf['Inspector'].value_counts().reset_index()
                    insp_counts.columns = ['Inspector', 'Postes']
                    
                    bar_insp = alt.Chart(insp_counts).mark_bar(color='#01305D').encode(
                        x=alt.X('Postes:Q', title='Nº de Postes'),
                        y=alt.Y('Inspector:N', sort='-x', title=''),
                        tooltip=['Inspector', 'Postes']
                    ).interactive()
                    st.altair_chart(bar_insp, use_container_width=True)

                st.divider()

                # 4. FILA DE GRÁFICOS: PROBLEMAS TÉCNICOS
                col_g1, col_g2 = st.columns(2)
                
                with col_g1:
                    st.markdown("**📉 Top Componentes con Problemas (A y M)**")
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
                    st.markdown("**📊 Desglose de Estado por Componente**")
                    if not df_melt.empty:
                        stacked_bar = alt.Chart(df_melt).mark_bar().encode(
                            x=alt.X('count():Q', title='Cantidad de Observaciones'),
                            y=alt.Y('Componente:N', sort='-x', title=''),
                            color=alt.Color('Estado:N', scale=color_scale_pie, legend=alt.Legend(title="Estado", orient="bottom")),
                            tooltip=[alt.Tooltip('Componente'), alt.Tooltip('Estado'), alt.Tooltip('count()', title='Cantidad')]
                        ).interactive()
                        st.altair_chart(stacked_bar, use_container_width=True)
                def generar_reporte_pdf(df_filtrado, camp, zona_sel, der_sel, comps):
                    # Configuración de página segura
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
                # ==========================================
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

                # 5. MAPA DE CRITICIDAD GEOREFERENCIADO
                st.divider()
                st.markdown("**🗺️ Mapa de Calor: Criticidad de Activos**")
                
                # Verificamos si existen las columnas de coordenadas
                if "Latitud" in df_f.columns and "Longitud" in df_f.columns:
                    # Limpieza profunda de datos geográficos
                    df_map = df_f.copy()
                    
                    # Forzamos conversión a numérico y eliminamos lo que no sea una coordenada válida
                    df_map['lat'] = pd.to_numeric(df_map['Latitud'], errors='coerce')
                    df_map['lon'] = pd.to_numeric(df_map['Longitud'], errors='coerce')
                    df_map = df_map.dropna(subset=['lat', 'lon'])
                    
                    # Filtro de seguridad: eliminamos coordenadas que estén en 0,0
                    df_map = df_map[(df_map['lat'] != 0) & (df_map['lon'] != 0)]
                    
                    if not df_map.empty:
                        # Cálculo de criticidad para el color y tamaño
                        def calcular_criticidad(row):
                            peso = 0
                            for c in comps_l:
                                if row.get(c) == 'A': peso += 5 # Mayor peso a fallas críticas
                                elif row.get(c) == 'M': peso += 2
                            return peso
                        
                        df_map['Criticidad'] = df_map.apply(calcular_criticidad, axis=1)
                        
                        # Colores basados en el estándar de mantenimiento (RGB)
                        def asignar_color(peso):
                            if peso >= 5: return [255, 0, 0, 160]    # Rojo intenso
                            if peso >= 2: return [255, 165, 0, 160]  # Naranja
                            return [0, 128, 0, 160]                  # Verde
                        
                        df_map['color'] = df_map['Criticidad'].apply(asignar_color)
                        
                        # Definición de la capa de puntos (Scatterplot)
                        # Usamos 'radius_min_pixels' para que siempre sean visibles al hacer zoom out
                        layer = pdk.Layer(
                            'ScatterplotLayer',
                            data=df_map,
                            get_position='[lon, lat]',
                            get_color='color',
                            get_radius=30,  # Radio fijo en metros
                            radius_min_pixels=5,
                            radius_max_pixels=15,
                            pickable=True
                        )
                        
                        # Centrado automático en los activos de la zona seleccionada
                        view_state = pdk.ViewState(
                            latitude=df_map['lat'].mean(),
                            longitude=df_map['lon'].mean(),
                            zoom=15,
                            pitch=0
                        )
                        
                        # Renderizado del mapa con estilo libre de tokens
                        st.pydeck_chart(pdk.Deck(
                            map_style=None, # Usa el mapa base por defecto de Streamlit (OpenStreetMap)
                            initial_view_state=view_state,
                            layers=[layer],
                            tooltip={
                                "html": "<b>Poste:</b> {Poste} <br/> "
                                        "<b>Inspector:</b> {Inspector} <br/> "
                                        "<b>Riesgo Acumulado:</b> {Criticidad}",
                                "style": {"color": "white", "backgroundColor": "#01305D"}
                            }
                        ))
                    else:
                        st.warning("📍 No se encontraron coordenadas válidas (Lat/Lon) para los postes seleccionados.")
                else:
                    st.info("💡 Las coordenadas no están cargadas. Recuerda vaciar la memoria y descargar nuevamente la campaña.")

            
            else:
                st.success("🌟 No hay hallazgos críticos pendientes para reportar en esta selección.")
        else:
            st.info("⬆️ Selecciona y descarga al menos una campaña en el panel superior.")

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
                    
                    st.dataframe(df_transposed.style.applymap(color_estado), use_container_width=True)
            
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
                    st.dataframe(df_comp.style.applymap(color_estado, subset=[f"Estado {c1_s}", f"Estado {c2_s}"]), use_container_width=True, hide_index=True)
            else:
                st.info("Sincroniza al menos 2 campañas para comparar evolución.")
        else:
            st.info("⬆️ Necesitas descargar campañas primero para usar la comparativa.")