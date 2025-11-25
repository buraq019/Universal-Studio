import streamlit as st
import zipfile
import io
import re
import os
import json
import streamlit.components.v1 as components
from openai import OpenAI
import google.generativeai as genai


CONFIG_FILE = "config.json"

def load_config():
    default = {
        "groq_key": "", "google_key": "", "or_key": "",
        "planner_prov": "Groq", "planner_mod": "llama-3.3-70b-versatile",
        "coder_prov": "Google (Native)", "coder_mod": "gemini-1.5-flash",
        "reviewer_prov": "Groq", "reviewer_mod": "llama-3.3-70b-versatile"
    }
    if os.path.exists(CONFIG_FILE):
        try: return {**default, **json.load(open(CONFIG_FILE))}
        except: return default
    return default

def save_config(config):
    json.dump(config, open(CONFIG_FILE, "w"))
    st.toast("✅ Ayarlar kaydedildi!", icon="💾")

config = load_config()

if "generated_code" not in st.session_state: st.session_state.generated_code = None
if "parsed_files" not in st.session_state: st.session_state.parsed_files = []


st.set_page_config(page_title="Universal AI Studio", page_icon="🛸", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0E1117; color: #FAFAFA; }
    [data-testid="stSidebar"] { background-color: #262730; }
    .stTextInput>div>div>input, .stTextArea>div>div>textarea, .stSelectbox>div>div>div {
        background-color: #1E1E1E; color: white; border: 1px solid #4A4A4A;
    }
    .stButton>button { width: 100%; background: linear-gradient(90deg, #4285F4, #9C27B0); color: white; border: none; padding: 12px; font-weight: bold; border-radius: 8px; }
    .revision-box { border: 2px solid #4285F4; padding: 20px; border-radius: 12px; margin-top: 20px; background-color: #161b22; }
    
    /* Terminal Görünümü İçin */
    .terminal-window {
        background-color: #1E1E1E; border-radius: 8px; padding: 15px; font-family: monospace; border: 1px solid #333;
    }
    .terminal-header { color: #888; margin-bottom: 10px; display: flex; gap: 10px; }
    .terminal-dot { width: 12px; height: 12px; border-radius: 50%; }
</style>
""", unsafe_allow_html=True)


with st.sidebar:
    st.header("🛸 Universal Studio")
    with st.expander("🔑 API Anahtarları"):
        groq_k = st.text_input("Groq Key", value=config["groq_key"], type="password")
        google_k = st.text_input("Google Key", value=config["google_key"], type="password")
        or_k = st.text_input("OpenRouter Key", value=config["or_key"], type="password")
    
    st.divider()
    
    
    c1, c2 = st.columns(2)
    with c1: p_prov = st.selectbox("Planlayıcı", ["Groq", "Google (Native)", "OpenRouter"], index=["Groq", "Google (Native)", "OpenRouter"].index(config["planner_prov"]))
    with c2: p_mod = st.text_input("Model", value=config["planner_mod"], key="p")
    
    c3, c4 = st.columns(2)
    with c3: c_prov = st.selectbox("Kodlayıcı", ["Groq", "Google (Native)", "OpenRouter"], index=["Groq", "Google (Native)", "OpenRouter"].index(config["coder_prov"]))
    with c4: c_mod = st.text_input("Model", value=config["coder_mod"], key="c")
    
    c5, c6 = st.columns(2)
    with c5: r_prov = st.selectbox("Testçi", ["Groq", "Google (Native)", "OpenRouter"], index=["Groq", "Google (Native)", "OpenRouter"].index(config["reviewer_prov"]))
    with c6: r_mod = st.text_input("Model", value=config["reviewer_mod"], key="r")

    if st.button("💾 Kaydet"):
        save_config({"groq_key": groq_k, "google_key": google_k, "or_key": or_k, 
                     "planner_prov": p_prov, "planner_mod": p_mod, 
                     "coder_prov": c_prov, "coder_mod": c_mod, 
                     "reviewer_prov": r_prov, "reviewer_mod": r_mod})
        st.rerun()


def run_agent(role, prompt, agent, prov, model):
    key, base, client = None, None, None
    if prov == "Groq": key, base = groq_k, "https://api.groq.com/openai/v1"
    elif prov == "OpenRouter": key, base = or_k, "https://openrouter.ai/api/v1"
    elif prov == "Google (Native)": key = google_k
    
    if not key: st.error(f"{agent} için {prov} anahtarı yok!"); return None

    try:
        with st.spinner(f"⚡ {agent} çalışıyor..."):
            if prov == "Google (Native)":
                genai.configure(api_key=key)
                m = genai.GenerativeModel(model, system_instruction=role)
                return m.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.4, max_output_tokens=8192)).text
            else:
                client = OpenAI(api_key=key, base_url=base)
                return client.chat.completions.create(model=model, messages=[{"role":"system","content":role},{"role":"user","content":prompt}], temperature=0.5).choices[0].message.content
    except Exception as e: st.error(f"Hata: {str(e)}"); return None

def parse_robust(text):
    files = []
    matches = re.findall(r"(?:###|::|\*\*)\s*(?:DOSYA|FILE|FILENAME|Dosya)[:\s]*\**`?([a-zA-Z0-9_\-\.]+)[`*]*\**\s*\n(.*?)(?=(?:###|::|\*\*)\s*(?:DOSYA|FILE|FILENAME|Dosya)|$)", text, re.DOTALL | re.IGNORECASE)
    for f, c in matches: files.append((f.strip(), re.sub(r"^```\w*\n|\n```$", "", c.strip())))
    return files

def create_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f, c in files: z.writestr(f, c)
    return buf

def detect_project_type(files):
    """Projenin Web mi yoksa Kod mu olduğunu anlar."""
    for f, _ in files:
        if f.endswith(".html") or f.endswith(".htm"): return "web"
    return "code"

def get_run_instruction(files):
    """Dosya türüne göre çalıştırma talimatı verir."""
    main_file = files[0][0]
    ext = main_file.split('.')[-1]
    if ext == "py": return f"python {main_file}"
    elif ext == "js": return f"node {main_file}"
    elif ext == "java": return f"javac {main_file} && java {main_file.replace('.java','')}"
    elif ext == "cpp": return f"g++ {main_file} -o app && ./app"
    return f"Dosyayı çalıştır: {main_file}"


st.title("🛸 Universal AI Studio")
st.caption("Web, Python, Java, C++... Ne istersen kodla.")

project_input = st.text_area("Ne inşa edelim?", height=100, placeholder="Örn: Python ile yılan oyunu veya HTML ile portfolyo sitesi.")

if st.button("🚀 Başlat"):
    pm_out = run_agent("PM. Gereksinimler.", f"Proje: {project_input}", "PM", p_prov, p_mod)
    if pm_out:
        with st.expander("1️⃣ Plan", expanded=False): st.markdown(pm_out)
        arch_out = run_agent("Mimar. Dosya yapısı.", f"Plan: {pm_out}", "Mimar", p_prov, p_mod)
        if arch_out:
            with st.expander("2️⃣ Mimari", expanded=False): st.markdown(arch_out)
            coder_out = run_agent("Coder. Sadece kod.", f"Mimari: {arch_out}\nGörev: Kodla.\nFormat: ### DOSYA: ad\n```kod```", "Coder", c_prov, c_mod)
            if coder_out:
                with st.expander("3️⃣ Kodlama", expanded=False): st.markdown(coder_out)
                final_out = run_agent("Paketleyici.", f"Birleştir ve formatı koru: ### DOSYA: ad\n```kod```\n\nGirdi: {coder_out}", "Testçi", r_prov, r_mod)
                if final_out:
                    st.session_state.generated_code = final_out
                    st.session_state.parsed_files = parse_robust(final_out)
                    st.rerun()


if st.session_state.generated_code:
    st.divider()
    files = st.session_state.parsed_files
    project_type = detect_project_type(files)
    
    
    tab1_name = "🖥️ CANLI ÖNİZLEME" if project_type == "web" else "📟 TERMİNAL / KOD"
    tab1, tab2 = st.tabs([tab1_name, "📂 DOSYA GEZGİNİ"])
    
    with tab1:
        if project_type == "web":
            
            html, css, js = "", "", ""
            for f, c in files:
                if f.endswith(".html"): html = c
                elif f.endswith(".css"): css += c
                elif f.endswith(".js"): js += c
            
            if html:
                
                if css: html = html.replace("</head>", f"<style>{css}</style></head>")
                if js: html = html.replace("</body>", f"<script>{js}</script></body>")
                components.html(html, height=600, scrolling=True)
            else:
                st.warning("HTML dosyası bulunamadı.")
        else:
            
            run_cmd = get_run_instruction(files)
            st.markdown(f"""
            <div class="terminal-window">
                <div class="terminal-header">
                    <div class="terminal-dot" style="background:#ff5f56"></div>
                    <div class="terminal-dot" style="background:#ffbd2e"></div>
                    <div class="terminal-dot" style="background:#27c93f"></div>
                    <span style="margin-left:10px">Terminal</span>
                </div>
                <div style="color: #00D26A; margin-bottom: 10px;">$ {run_cmd}</div>
                <div style="color: #ccc;">(Bu bir sunucu/konsol uygulamasıdır. Çalıştırmak için indirin.)</div>
            </div>
            """, unsafe_allow_html=True)
            
            st.info("💡 Bu proje bir Web Sitesi olmadığı için tarayıcıda doğrudan çalışmaz. Kodları inceleyebilir veya indirip bilgisayarında çalıştırabilirsin.")
            
            
            for f, c in files:
                st.markdown(f"### 📄 {f}")
                st.code(c)

    with tab2:
        c1, c2 = st.columns([3, 1])
        with c1:
            for f, c in files:
                with st.expander(f"📄 {f}", expanded=False): st.code(c)
        with c2:
            st.download_button("📥 İNDİR (.zip)", create_zip(files).getvalue(), "project.zip", "application/zip", use_container_width=True)

    
    st.markdown("<div class='revision-box'>", unsafe_allow_html=True)
    st.subheader("🛠️ Düzenleme İste")
    req = st.text_area("Neyi değiştirelim?", placeholder="Örn: Rengi değiştir veya Python koduna hata yakalama ekle...")
    if st.button("✨ Güncelle", use_container_width=True):
        if req:
            upd = run_agent("Revize Uzmanı.", f"KOD: {st.session_state.generated_code}\nİSTEK: {req}\nGÖREV: Revize et. Formatı koru: ### DOSYA: ad", "Revize", c_prov, c_mod)
            if upd:
                st.session_state.generated_code = upd
                st.session_state.parsed_files = parse_robust(upd)
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)