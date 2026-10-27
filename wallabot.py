#!/usr/bin/env python3
"""
WallaBot - Alertas de Wallapop en Telegram (uso personal)
Requisitos: Python 3.8+  y  pip install requests
Uso:        TOKEN=tu_token python wallabot.py
"""
VERSION = "2026.10.27-2"
REPO = "itzzpauu/wallabot"
import os, sys, json, time, html, re, statistics, threading, unicodedata, requests
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import shutil
# Alertas y token en una carpeta fija (~/.wallabot): las actualizaciones nunca la tocan
CARPETA = os.path.dirname(os.path.abspath(__file__))
DATOS_DIR = os.path.join(os.path.expanduser("~"), ".wallabot")
os.makedirs(DATOS_DIR, exist_ok=True)
DATA_FILE = os.path.join(DATOS_DIR, "wallabot_data.json")
TOKEN_FILE = os.path.join(DATOS_DIR, "wallabot_token.txt")

def _recuperar_antiguos():
    """Trae alertas/token de versiones anteriores que los guardaban junto al script."""
    casa = os.path.expanduser("~")
    sitios = [CARPETA, casa, os.path.join(casa, "downloads"), os.path.join(casa, "storage", "downloads")]
    for nombre, destino in (("wallabot_data.json", DATA_FILE), ("wallabot_token.txt", TOKEN_FILE)):
        if os.path.exists(destino):
            continue
        candidatos = [os.path.join(x, nombre) for x in sitios if os.path.exists(os.path.join(x, nombre))]
        if candidatos:
            mejor = max(candidatos, key=os.path.getmtime)
            try:
                shutil.copy2(mejor, destino)
                print(f"Recuperado {nombre} de {mejor}")
            except OSError:
                pass

_recuperar_antiguos()
PUERTO = 8080

# El token se guarda la primera vez; después basta con: python wallabot.py
TOKEN = os.environ.get("TOKEN", "").strip()
if TOKEN:
    with open(TOKEN_FILE, "w") as f:
        f.write(TOKEN)
elif os.path.exists(TOKEN_FILE):
    TOKEN = open(TOKEN_FILE).read().strip()
else:
    TOKEN = "PEGA_AQUI_TU_TOKEN_DE_BOTFATHER"
LOCK = threading.RLock()
MAX_VISTOS = 6000      # anuncios recordados por alerta
MAX_ENVIADOS = 30000   # anuncios enviados en total (nunca se repiten)

# Vinted: dominio, bandera, país, símbolo de moneda
VINTED_PAISES = [
    ("vinted.es", "🇪🇸", "España", "€"), ("vinted.fr", "🇫🇷", "Francia", "€"), ("vinted.it", "🇮🇹", "Italia", "€"),
    ("vinted.pt", "🇵🇹", "Portugal", "€"), ("vinted.de", "🇩🇪", "Alemania", "€"), ("vinted.be", "🇧🇪", "Bélgica", "€"),
    ("vinted.nl", "🇳🇱", "Países Bajos", "€"), ("vinted.lu", "🇱🇺", "Luxemburgo", "€"), ("vinted.at", "🇦🇹", "Austria", "€"),
    ("vinted.ie", "🇮🇪", "Irlanda", "€"), ("vinted.co.uk", "🇬🇧", "Reino Unido", "£"), ("vinted.pl", "🇵🇱", "Polonia", "zł"),
    ("vinted.cz", "🇨🇿", "Chequia", "Kč"), ("vinted.sk", "🇸🇰", "Eslovaquia", "€"), ("vinted.hu", "🇭🇺", "Hungría", "Ft"),
    ("vinted.ro", "🇷🇴", "Rumanía", "lei"), ("vinted.lt", "🇱🇹", "Lituania", "€"), ("vinted.lv", "🇱🇻", "Letonia", "€"),
    ("vinted.ee", "🇪🇪", "Estonia", "€"), ("vinted.fi", "🇫🇮", "Finlandia", "€"), ("vinted.se", "🇸🇪", "Suecia", "kr"),
    ("vinted.dk", "🇩🇰", "Dinamarca", "kr"), ("vinted.gr", "🇬🇷", "Grecia", "€"), ("vinted.hr", "🇭🇷", "Croacia", "€"),
    ("vinted.si", "🇸🇮", "Eslovenia", "€"), ("vinted.com", "🇺🇸", "EE. UU.", "$"), ("vinted.com.au", "🇦🇺", "Australia", "A$"),
]
VINTED_INFO = {dom: (flag, pais, sim) for dom, flag, pais, sim in VINTED_PAISES}
FUENTES_DEFECTO = {"wallapop": True, "wallapop_it": True, "vinted": [x[0] for x in VINTED_PAISES]}
TG = f"https://api.telegram.org/bot{TOKEN}"
WALLA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
    "X-DeviceOS": "0",
    "Accept": "application/json",
    "Accept-Language": "es-ES,es;q=0.9",
}

AYUDA = """🎯 <b>WallaBot</b> — alertas de Wallapop al instante

📱 <b>Lo más fácil:</b> abre <b>localhost:8080</b> en Chrome del móvil y crea tus alertas desde el panel.

<b>Crear alerta</b>
/nueva iphone 13 max=400 excluir=roto,funda
(añade vinted=fr,it,de · vinted=todos · wallapop=no)

<b>Buscar ahora (con Chollómetro)</b>
/buscar ps5 max=350

<b>Gestionar</b>
/lista — ver alertas (⏸ = pausada)
/pausar 2 · /activar 2 — una alerta concreta
/borrar 2 — borrar la alerta nº 2
/pausa · /reanudar — todas
/estado — qué países de Vinted funcionan
/silenciados — ver y quitar silenciados
/bloquear cash converters — bloquear una cadena entera (todas sus tiendas)
/solonuevos — cortar la avalancha: solo lo nuevo desde ahora (/limpiar para vaciar)
/intervalo 60 — revisar cada 60 s (mín. 30)
/ubicacion 28.12 -15.43 — fijar zona (o envíame tu 📍)
/probar 1 — ver ahora los 3 últimos de la alerta 1

Cada aviso trae botones: <i>Ver anuncio · Pausar alerta · Silenciar vendedor</i>
"""

# ---------------- Datos ----------------
def cargar():
    base = {"owner": None, "lat": 41.3874, "lon": 2.1686, "zona": "Barcelona", "intervalo": 20, "max_edad": 0, "feed": [], "notif_movil": True,
            "pausa": False, "busquedas": [], "offset": 0, "next_id": 1, "silenciados": [], "bloq": []}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            guardado = json.load(f)
        if "zona" not in guardado:          # datos antiguos: el centro pasa a Barcelona
            guardado.update(lat=41.3874, lon=2.1686, zona="Barcelona")
        for b in guardado.get("busquedas", []):
            if "fuentes" not in b:          # alertas antiguas: solo Wallapop, ids con prefijo
                b["fuentes"] = {"wallapop": True, "vinted": []}
                b["vistos"] = ["w:" + v for v in b.get("vistos", [])]
            b["fuentes"].setdefault("wallapop_it", b["fuentes"].get("wallapop", False))
            completo = {"wallapop": True, "wallapop_it": True, "vinted": [x[0] for x in VINTED_PAISES]}
            if b["fuentes"] != completo or b.get("km"):
                b.update(fuentes=completo, km=None, inicial=True)
                for k in ("lat", "lon", "zona"):
                    b.pop(k, None)
        if guardado.get("max_edad") in (2, 15):   # versiones anteriores: ahora sin límite
            guardado["max_edad"] = 0
        if guardado.get("intervalo", 60) >= 60 and not guardado.get("rapido"):   # pasar a 20 s una vez
            guardado.update(intervalo=20, rapido=True)
        base.update(guardado)
    return base

def guardar(d):
    with LOCK:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, DATA_FILE)

# ---------------- Telegram ----------------
def tg(metodo, **params):
    try:
        r = requests.post(f"{TG}/{metodo}", json=params, timeout=40)
        return r.json()
    except Exception as e:
        print("Error Telegram:", e)
        return {}

def enviar(chat, texto):
    tg("sendMessage", chat_id=chat, text=texto, parse_mode="HTML", disable_web_page_preview=True)

def edad_min(it):
    """Minutos desde que se publicó (None si la plataforma no lo dice)."""
    c = it.get("creado")
    try:
        c = float(c)
    except (TypeError, ValueError):
        return None
    if c > 1e11:
        c /= 1000
    return max(0.0, (time.time() - c) / 60)

def hace(ms):
    if not ms:
        return "—"
    try:
        seg = max(0, time.time() - float(ms) / (1000 if float(ms) > 1e11 else 1))
    except (TypeError, ValueError):
        return "—"
    if seg < 60: return "hace unos segundos"
    if seg < 3600: return f"hace {int(seg // 60)} min"
    if seg < 86400: return f"hace {int(seg // 3600)} h"
    return f"hace {int(seg // 86400)} días"

def chollometro(item):
    p, med = item["precio_num"], item.get("mediana")
    if not p or not med:
        return ""
    r, m = p / med, item.get("simbolo", "€")
    if r <= 0.7:  return f"🔥 <b>CHOLLAZO</b> ({int((1 - r) * 100)}% bajo el precio típico ~{med:.0f} {m})"
    if r <= 0.9:  return f"✅ Buen precio (típico ~{med:.0f} {m})"
    if r >= 1.15: return f"💸 Caro (típico ~{med:.0f} {m})"
    return f"➖ Precio normal (típico ~{med:.0f} {m})"

def detectado_txt(item):
    e = edad_min(item)
    if e is None:
        return ""
    if e < 1:
        return "menos de 1 minuto después de publicación"
    if e < 60:
        return f"{int(e)} minuto{'s' if int(e) != 1 else ''} después de publicación"
    return f"{int(e // 60)} h después de publicación"

def alerta_corta(b):
    t = html.escape(b.get("texto", ""))
    if b.get("min") is not None and b.get("max") is not None:
        t += f" · {b['min']:g}–{b['max']:g} €"
    elif b.get("max") is not None:
        t += f" · hasta {b['max']:g} €"
    elif b.get("min") is not None:
        t += f" · desde {b['min']:g} €"
    return t

MAX_FEED = 2000   # anuncios encontrados que se guardan para verlos en la web

def add_feed(d, it, b):
    cho = chollometro(it)
    t = {"id": it.get("id"), "titulo": it.get("titulo"), "precio": it.get("precio"),
         "origen": it.get("origen"), "ciudad": it.get("ciudad"), "foto": it.get("foto"), "url": it.get("url"),
         "vendedor_nombre": it.get("vendedor_nombre"), "vendedor": it.get("vendedor"), "creado": it.get("creado"),
         "chollo": re.sub("<[^>]+>", "", cho) if cho else "",
         "alerta_id": b.get("id"), "alerta": b.get("texto"), "visto_ts": time.time()}
    with LOCK:
        feed = d.setdefault("feed", [])
        feed.insert(0, t)
        del feed[MAX_FEED:]

def _chollo_corto(item):
    p, med = item.get("precio_num"), item.get("mediana")
    if not p or not med:
        return ""
    r = p / med
    if r <= 0.7:  return f"🔥 CHOLLAZO -{int((1 - r) * 100)}%"
    if r <= 0.9:  return "✅ Buen precio"
    if r >= 1.15: return "💸 Caro"
    return ""

def enviar_anuncio(chat, item, b, titulo=None):
    """Aviso compacto: la foto manda; plataforma y precio en la primera línea."""
    origen = item.get("origen", "🟢 Wallapop")
    cabecera = origen.replace("Wallapop", "WALLAPOP").replace("Vinted", "VINTED")
    if titulo:                                   # /probar, /buscar
        cabecera = f"{titulo} · {cabecera}"
    precio = f"💶 <b>{html.escape(str(item['precio']))}</b>"
    if item.get("proteccion"):
        precio += f" ({html.escape(item['proteccion'])} c/protección)"
    vend = ""
    if item.get("vendedor_nombre"):
        n = html.escape(item["vendedor_nombre"])
        vend = f'<a href="{item["perfil_url"]}">{n}</a>' if item.get("perfil_url") else n
    e = edad_min(item)
    extra = [x for x in (
        _chollo_corto(item),
        "📦 Envío" if item.get("envio") == "Disponible" else ("🤝 En mano" if item.get("envio") else ""),
        f"⏱ {int(e)} min" if e is not None else "",
    ) if x]
    lineas = [f"{cabecera} · {precio}",
              f"<b>{html.escape(item['titulo'])}</b>",
              f"📍 {html.escape(item['ciudad'] or '—')}" + (" · " + " · ".join(extra) if extra else ""),
              (f"👤 {vend} · " if vend else "") + f"🔔 {alerta_corta(b)}",
              f"👉 {html.escape(item['url'])}"]
    cap = "\n".join(lineas)
    fila = []
    if b.get("id"):
        fila.append({"text": "✏️ Editar", "callback_data": f"e:{b['id']}"})
        fila.append({"text": "⏸ Pausar", "callback_data": f"p:{b['id']}"})
    if item.get("vendedor"):
        fila.append({"text": "🔇 Silenciar", "callback_data": f"s:{item['vendedor']}"[:64]})
    filas = [fila] if fila else []
    filas.append([{"text": "👀 VER ANUNCIO", "url": item["url"]}])
    teclado = {"inline_keyboard": filas}
    if item["foto"]:
        r = tg("sendPhoto", chat_id=chat, photo=item["foto"], caption=cap,
               parse_mode="HTML", reply_markup=teclado)
        if r.get("ok"):
            return
    tg("sendMessage", chat_id=chat, text=cap, parse_mode="HTML", reply_markup=teclado,
       disable_web_page_preview=True)

# ---------------- Wallapop ----------------
def _precio(it):
    p = it.get("price", it.get("sale_price"))
    if isinstance(p, dict):
        p = p.get("amount")
    try:
        p = float(p)
        return p, (f"{p:.0f} €" if p == int(p) else f"{p:.2f} €")
    except (TypeError, ValueError):
        return None, "¿? €"

# Provincia a partir de los 2 primeros dígitos del código postal español
PROVINCIAS = {"01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería", "05": "Ávila", "06": "Badajoz",
    "07": "Baleares", "08": "Barcelona", "09": "Burgos", "10": "Cáceres", "11": "Cádiz", "12": "Castellón",
    "13": "Ciudad Real", "14": "Córdoba", "15": "A Coruña", "16": "Cuenca", "17": "Girona", "18": "Granada",
    "19": "Guadalajara", "20": "Gipuzkoa", "21": "Huelva", "22": "Huesca", "23": "Jaén", "24": "León",
    "25": "Lleida", "26": "La Rioja", "27": "Lugo", "28": "Madrid", "29": "Málaga", "30": "Murcia",
    "31": "Navarra", "32": "Ourense", "33": "Asturias", "34": "Palencia", "35": "Las Palmas", "36": "Pontevedra",
    "37": "Salamanca", "38": "Santa Cruz de Tenerife", "39": "Cantabria", "40": "Segovia", "41": "Sevilla",
    "42": "Soria", "43": "Tarragona", "44": "Teruel", "45": "Toledo", "46": "Valencia", "47": "Valladolid",
    "48": "Bizkaia", "49": "Zamora", "50": "Zaragoza", "51": "Ceuta", "52": "Melilla"}
PAISES_WALLA = {"ES": "🇪🇸 España", "IT": "🇮🇹 Italia", "PT": "🇵🇹 Portugal", "FR": "🇫🇷 Francia", "AD": "🇦🇩 Andorra"}

def ubicacion_wallapop(loc):
    """'La Línea de la Concepción, Cádiz · 🇪🇸 España'"""
    if not isinstance(loc, dict):
        return "🇪🇸 España"
    ciudad = (loc.get("city") or "").strip()
    cp = str(loc.get("postal_code") or loc.get("zip") or "").strip()
    pais_cod = str(loc.get("country_code") or "ES").upper()
    provincia = ""
    if pais_cod == "ES" and len(cp) >= 2:
        provincia = PROVINCIAS.get(cp.zfill(5)[:2], "")
    provincia = provincia or (loc.get("region2") or loc.get("region") or "").strip()
    partes = [ciudad] if ciudad else []
    if provincia and provincia.lower() != ciudad.lower():
        partes.append(provincia)
    pais = PAISES_WALLA.get(pais_cod, pais_cod)
    return (", ".join(partes) + " · " if partes else "") + pais

def _envio_wallapop(it):
    sh = it.get("shipping")
    v = None
    if isinstance(sh, dict):
        v = sh.get("item_is_shippable", sh.get("user_allows_shipping"))
    if v is None:
        v = it.get("is_shippable", it.get("supports_shipping"))
    if v is None:
        return ""
    return "Disponible" if v else "Solo en mano"

def _normalizar(it):
    imgs = it.get("images") or []
    foto = None
    if imgs:
        i0 = imgs[0]
        urls = i0.get("urls", i0) if isinstance(i0, dict) else {}
        foto = urls.get("medium") or urls.get("big") or urls.get("original") or urls.get("small")
    slug = it.get("web_slug") or it.get("id")
    valor, texto = _precio(it)
    loc = it.get("location") or {}
    user = it.get("user") or {}
    res = it.get("reserved")
    return {"id": "w:" + str(it.get("id")), "origen": "🟢 Wallapop", "simbolo": "€",
            "titulo": it.get("title", "Sin título"),
            "desc": it.get("description", "") or "", "precio_num": valor, "precio": texto,
            "url": f"https://es.wallapop.com/item/{slug}", "foto": foto,
            "ciudad": ubicacion_wallapop(loc),
            "vendedor": str(it.get("user_id") or (user.get("id") if isinstance(user, dict) else "") or ""),
            "vendedor_nombre": (user.get("micro_name") or user.get("name") or "") if isinstance(user, dict) else "",
            "creado": it.get("created_at") or it.get("creation_date") or it.get("modified_at"),
            "reservado": bool(res.get("flag")) if isinstance(res, dict) else bool(res),
            "envio": _envio_wallapop(it),
            "perfil_url": (f"https://es.wallapop.com/user/{user.get('web_slug')}"
                           if isinstance(user, dict) and user.get("web_slug") else ""),
            "proteccion": ""}

WALLA_ESTADO = {}
ROMA = (41.9028, 12.4964)

def buscar_wallapop_it(b):
    """Wallapop Italia: misma API, centro en Italia y enlaces a it.wallapop.com."""
    b2 = dict(b, km=None)
    res = buscar_wallapop(b2, ROMA[0], ROMA[1], pais="IT")
    for it in res or []:
        it["url"] = it["url"].replace("://es.wallapop.com", "://it.wallapop.com")
        it["perfil_url"] = (it.get("perfil_url") or "").replace("://es.wallapop.com", "://it.wallapop.com")
        it["origen"] = "🟢 Wallapop 🇮🇹"
    return res

def buscar_wallapop(b, lat, lon, pais="ES"):
    # Sin km = toda Wallapop. La zona propia de la alerta solo cuenta si limitas distancia.
    if b.get("km") and b.get("lat") is not None:
        lat, lon = b["lat"], b["lon"]
    params = {"source": "search_box", "keywords": b["texto"], "order_by": "newest",
              "latitude": lat, "longitude": lon}
    if b.get("km"):
        params["distance_in_km"] = b["km"]
        params["distance"] = int(b["km"]) * 1000
    if b.get("min") is not None:
        params["min_sale_price"] = b["min"]
    if b.get("max") is not None:
        params["max_sale_price"] = b["max"]

    data = None
    cab = dict(WALLA_HEADERS)
    if pais == "IT":
        cab["Accept-Language"] = "it-IT,it;q=0.9"
    for url in ("https://api.wallapop.com/api/v3/search",
                "https://api.wallapop.com/api/v3/general/search"):
        try:
            r = requests.get(url, params=params, headers=cab, timeout=20)
            if r.status_code == 200:
                data = r.json()
                WALLA_ESTADO[pais] = "ok"
                break
            WALLA_ESTADO[pais] = f"error {r.status_code}"
            print(f"Wallapop {r.status_code} en {url}")
        except Exception as e:
            print("Error Wallapop:", e)
    if not data:
        return None

    crudos = data.get("search_objects")
    if crudos is None:
        crudos = (((data.get("data") or {}).get("section") or {}).get("payload") or {}).get("items", [])
    return [_normalizar(x) for x in crudos if isinstance(x, dict)]

# ---------------- Vinted ----------------
VINTED_SES = {}
VINTED_CAIDOS = {}      # dominio -> hora hasta la que se salta (país que da 404 / no existe)
VINTED_ESTADO = {}      # dominio -> "ok" / "error 403" / ... (para /estado)

VINTED_UA = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/134.0.0.0 Mobile Safari/537.36")
VINTED_LOCALE = {"com": "en-US", "co.uk": "en-GB", "com.au": "en-AU", "at": "de-AT", "be": "fr-BE", "cz": "cs-CZ",
                 "de": "de-DE", "dk": "da-DK", "ee": "et-EE", "es": "es-ES", "fi": "fi-FI", "fr": "fr-FR",
                 "gr": "el-GR", "hr": "hr-HR", "hu": "hu-HU", "ie": "en-IE", "it": "it-IT", "lt": "lt-LT",
                 "lu": "fr-LU", "lv": "lv-LV", "nl": "nl-NL", "pl": "pl-PL", "pt": "pt-PT", "ro": "ro-RO",
                 "se": "sv-SE", "sk": "sk-SK", "si": "sl-SI"}
VINTED_FALLOS = {}      # dominio -> fallos seguidos (para esperar más entre intentos)

def _sesion_vinted(dom, nueva=False):
    """Identidad anónima que da la web de Vinted: cookie access_token_web + cabecera X-Anon-Id."""
    ses = VINTED_SES.get(dom)
    if ses and not nueva and time.time() - ses["t"] < 1800:
        return ses
    loc = VINTED_LOCALE.get(dom.split("vinted.", 1)[1], "en-US")
    s = requests.Session()
    r = s.get(f"https://www.{dom}/", timeout=20, headers={
        "User-Agent": VINTED_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": f"{loc},en;q=0.5", "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1"})
    m = re.search(r"<html\b[^>]*?\blang=[\"']([A-Za-z]{2}(?:-[A-Za-z0-9]+)?)[\"']", r.text[:20000])
    ses = {"s": s, "t": time.time(), "loc": m.group(1) if m else loc,
           "anon": (r.headers.get("X-Anon-Id") or s.cookies.get("anon_id") or "").strip(),
           "token": s.cookies.get("access_token_web") or ""}
    VINTED_SES[dom] = ses
    return ses

def _api_host_vinted(dom):
    return f"api.{dom}"

def _cabeceras_api(dom, ses):
    base = f"https://www.{dom}"
    cab = {"User-Agent": VINTED_UA, "Accept": "application/json, text/plain, */*",
           "Accept-Language": f"{ses['loc']},en;q=0.5", "Cache-Control": "no-cache", "Pragma": "no-cache",
           "Origin": base, "Referer": base, "Locale": ses["loc"], "Platform": "web",
           "X-Next-App": "marketplace-web", "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
           "Sec-Fetch-Site": "same-site"}
    if ses["token"]:
        cab["Cookie"] = f"access_token_web={ses['token']}"
    if ses["anon"]:
        cab["X-Anon-Id"] = ses["anon"]
    return cab

def _esperar_vinted(dom, minutos_base, motivo):
    n = VINTED_FALLOS[dom] = VINTED_FALLOS.get(dom, 0) + 1
    espera = min(60, minutos_base * (2 ** (n - 1)))
    VINTED_CAIDOS[dom] = time.time() + espera * 60
    VINTED_ESTADO[dom] = f"{motivo} (reintento en {espera} min)"
    print(f"Vinted {dom}: {motivo}, lo vuelvo a intentar en {espera} min")

def _items_vinted(data):
    if isinstance(data, list):
        return data
    for ruta in (("items",), ("data", "items"), ("catalog_items",), ("results",), ("data",)):
        x = data
        for k in ruta:
            x = x.get(k) if isinstance(x, dict) else None
        if isinstance(x, list):
            return x
    return []

def _total_vinted(it, sim):
    t = it.get("total_item_price")
    if isinstance(t, dict):
        t = t.get("amount")
    try:
        t = float(t)
        return f"{t:.2f} {sim}".replace(".", ",")
    except (TypeError, ValueError):
        return ""

def buscar_vinted(b, dom):
    flag, pais, sim = VINTED_INFO.get(dom, ("🌍", dom, ""))
    if VINTED_CAIDOS.get(dom, 0) > time.time():
        return None
    params = {"search_text": b["texto"], "order": "newest_first", "per_page": 30, "page": 1}
    if b.get("min") is not None: params["price_from"] = b["min"]   # vacíos no: la API da 400
    if b.get("max") is not None: params["price_to"] = b["max"]
    data = None
    for intento in range(2):
        try:
            ses = _sesion_vinted(dom, nueva=intento > 0)
            r = ses["s"].get(f"https://{_api_host_vinted(dom)}/svc-catalogue/items", params=params,
                             headers=_cabeceras_api(dom, ses), timeout=20)
        except Exception as e:                     # sin conexión / DNS: no insistir enseguida
            VINTED_SES.pop(dom, None)
            _esperar_vinted(dom, 2, "sin conexión")
            return None
        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                _esperar_vinted(dom, 5, "respuesta rara")
                return None
            VINTED_ESTADO[dom] = "ok"
            VINTED_FALLOS[dom] = 0
            break
        if r.status_code == 401 and intento == 0:   # caducó la identidad: pedir otra
            continue
        if r.status_code == 404:
            _esperar_vinted(dom, 60, "no disponible (404)")
        elif r.status_code in (403, 429, 503):      # Vinted frena: esperar y bajar el ritmo
            VINTED_SES.pop(dom, None)
            _esperar_vinted(dom, 5, f"bloqueo temporal ({r.status_code})")
        else:
            _esperar_vinted(dom, 3, f"error {r.status_code}")
        return None
    if data is None:
        return None
    lista = _items_vinted(data)
    if lista and not VINTED_ESTADO.get("_avisado") and not any(isinstance(x, dict) and x.get("id") for x in lista[:3]):
        VINTED_ESTADO["_avisado"] = True
        print("Vinted: formato desconocido, claves:", list(lista[0].keys())[:20] if isinstance(lista[0], dict) else type(lista[0]))
    res = []
    for it in lista:
        if not isinstance(it, dict):
            continue
        pr = it.get("price") if it.get("price") is not None else it.get("price_numeric")
        if isinstance(pr, dict):
            sim2 = {"EUR": "€", "GBP": "£", "USD": "$", "PLN": "zł", "CZK": "Kč", "HUF": "Ft",
                    "RON": "lei", "SEK": "kr", "DKK": "kr", "AUD": "A$"}.get(pr.get("currency_code"), sim)
            pr = pr.get("amount")
        else:
            sim2 = sim
        try:
            pv = float(pr)
            ptxt = f"{pv:.0f} {sim2}" if pv == int(pv) else f"{pv:.2f} {sim2}"
        except (TypeError, ValueError):
            pv, ptxt = None, "¿?"
        foto = it.get("photo") or ((it.get("photos") or [{}])[0]) or {}
        if not isinstance(foto, dict):
            foto = {"url": str(foto)}
        user = it.get("user") or it.get("seller") or {}
        url = it.get("url") or it.get("path") or f"/items/{it.get('id')}"
        if url.startswith("/"):
            url = f"https://www.{dom}{url}"
        res.append({"id": "v:" + str(it.get("id")), "origen": f"🟣 Vinted {flag}", "simbolo": sim2,
                    "titulo": it.get("title") or (it.get("item_box") or {}).get("title") or "Sin título",
                    "desc": it.get("description", "") or "",
                    "precio_num": pv, "precio": ptxt,
                    "url": url,
                    "foto": foto.get("url") or it.get("image_url"), "ciudad": f"{flag} {pais}",
                    "vendedor": ("v" + str(user.get("id"))) if user.get("id") else "",
                    "vendedor_nombre": user.get("login") or "",
                    "perfil_url": f"https://www.{dom}/member/{user.get('id')}" if user.get("id") else "",
                    "envio": "Disponible",
                    "proteccion": _total_vinted(it, sim2),
                    "creado": (foto.get("high_resolution") or {}).get("timestamp"),
                    "reservado": bool(it.get("is_reserved"))})
    return res

# ---------------- Búsqueda combinada ----------------
def buscar(b, d, solo=None):
    """Busca en las fuentes de la alerta (solo='walla' o 'vinted' para una sola). None si todas fallan."""
    f = dict(b.get("fuentes") or FUENTES_DEFECTO)
    if solo == "walla":
        f["vinted"] = []
    elif solo == "vinted":
        f["wallapop"] = f["wallapop_it"] = False
    grupos, alguna_ok = [], False
    if f.get("wallapop"):
        r = buscar_wallapop(b, d["lat"], d["lon"])
        if r is not None:
            alguna_ok = True; grupos.append(r)
    if f.get("wallapop_it"):
        r = buscar_wallapop_it(b)
        if r is not None:
            alguna_ok = True; grupos.append(r)
    doms = f.get("vinted", [])
    if doms:
        with ThreadPoolExecutor(max_workers=3) as ex:   # suave: no saturar el móvil ni Vinted
            for r in ex.map(lambda dom: buscar_vinted(b, dom), doms):
                if r is not None:
                    alguna_ok = True; grupos.append(r)
    if not alguna_ok:
        return None
    sil = set(d.get("silenciados", []))
    actualizar_bloqueos(d)
    res, ids = [], set()
    sin_precio = dict(b, min=None, max=None)
    for g in grupos:
        base = filtrar(sin_precio, g, sil)
        precios = [i["precio_num"] for i in base if i["precio_num"]]
        med = statistics.median(precios) if len(precios) >= 5 else None
        filtrados = filtrar(b, base, sil)
        if b.get("solo_chollos") and med:
            # chollo = al menos un 10 % por debajo del precio típico de esa búsqueda
            filtrados = [i for i in filtrados if i["precio_num"] is not None and i["precio_num"] <= med * 0.9]
        for i in filtrados:
            if i["id"] in ids:          # el mismo anuncio de Vinted sale en varios países
                continue
            ids.add(i["id"]); i["mediana"] = med; res.append(i)
    return res

def _norm(t):
    """minúsculas y sin acentos: 'Nintendo 3DS XL' -> 'nintendo 3ds xl'"""
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")

def _palabras(t):
    return set(re.findall(r"[a-z0-9ñ]+", _norm(t)))

def contiene_todas(b, it):
    """Modo palabras exactas: el título debe tener TODAS las palabras buscadas, en cualquier orden."""
    buscadas = _palabras(b.get("texto", ""))
    if not buscadas:
        return True
    return buscadas <= _palabras(it.get("titulo", ""))   # solo el título: lo más estricto

BLOQ = {"nombres": set(), "frag": []}   # se rellena desde d antes de cada búsqueda

def actualizar_bloqueos(d):
    BLOQ["nombres"] = {_norm(n).strip() for n in d.get("silenciados_nombres", {}).values()
                       if n and not n.startswith("vendedor de ")}
    BLOQ["frag"] = [f for f in (_norm(x).strip() for x in d.get("bloq", [])) if f]

def bloqueado(it, silenciados=()):
    """True si el vendedor está silenciado (por cuenta, por nombre o por palabra bloqueada)."""
    if it.get("vendedor") and it["vendedor"] in silenciados:
        return True
    nombre = _norm(it.get("vendedor_nombre") or "").strip()
    if nombre and nombre in BLOQ["nombres"]:
        return True
    if BLOQ["frag"]:
        texto = nombre + " " + _norm((it.get("titulo") or "") + " " + (it.get("desc") or ""))
        junto = re.sub(r"[^a-z0-9ñ]", "", texto)
        if any(f in texto or re.sub(r"[^a-z0-9ñ]", "", f) in junto for f in BLOQ["frag"]):
            return True
    return False

def filtrar(b, items, silenciados):
    excl = [_norm(w.strip()) for w in b.get("excluir", []) if w.strip()]
    res = []
    for it in items:
        txt = _norm(it["titulo"] + " " + it["desc"])
        if any(w in txt for w in excl) or it["reservado"]:
            continue
        if b.get("exactas") and not contiene_todas(b, it):
            continue
        if bloqueado(it, silenciados):
            continue
        p = it["precio_num"]
        if p is not None:
            if b.get("min") is not None and p < b["min"]:
                continue
            if b.get("max") is not None and p > b["max"]:
                continue
        res.append(it)
    return res

def solo_nuevos(d):
    """Corta los avisos pendientes y marca como visto todo lo que hay ahora."""
    d["cortar"] = True
    d["corte_ts"] = time.time()
    try:
        while True:
            COLA.get_nowait()
    except Exception:
        pass
    with LOCK:
        for b in d["busquedas"]:
            b["inicial"] = True
    guardar(d)
    def tarea():
        for b in list(d["busquedas"]):
            res = buscar(b, d)
            with LOCK:
                if res is not None:
                    ids = [it["id"] for it in res]
                    b["vistos"] = list(dict.fromkeys(ids + b.get("vistos", [])))[:MAX_VISTOS]
                    d["enviados"] = list(dict.fromkeys(ids + d.get("enviados", [])))[:MAX_ENVIADOS]
                b["inicial"] = False
            guardar(d)
    threading.Thread(target=tarea, daemon=True).start()

def sembrar(d, b):
    """Marca como vistos los anuncios que ya existen, para avisar solo de lo nuevo."""
    def tarea():
        res = buscar(b, d)
        with LOCK:
            if res is not None:
                b["vistos"] = list(dict.fromkeys([it["id"] for it in res] + b.get("vistos", [])))[:MAX_VISTOS]
                b["inicial"] = False
        guardar(d)
    threading.Thread(target=tarea, daemon=True).start()

# ---------------- Comandos ----------------
def parse_nueva(arg):
    b = {"texto": "", "min": None, "max": None, "km": None, "excluir": [],
         "fuentes": {"wallapop": True, "wallapop_it": True, "vinted": list(FUENTES_DEFECTO["vinted"])}}
    palabras = []
    for tok in arg.split():
        m = re.match(r"^(vinted|wallapop|italia)=(.+)$", tok, re.I)
        if m:
            k, v = m.group(1).lower(), m.group(2).lower()
            if k == "wallapop":
                b["fuentes"]["wallapop"] = b["fuentes"]["wallapop_it"] = v not in ("no", "0", "off")
            elif k == "italia":
                b["fuentes"]["wallapop_it"] = v not in ("no", "0", "off")
            elif v in ("todos", "all"):
                b["fuentes"]["vinted"] = [x[0] for x in VINTED_PAISES]
            elif v in ("no", "0", "off"):
                b["fuentes"]["vinted"] = []
            else:
                cods = [c.strip().lstrip(".") for c in v.split(",")]
                b["fuentes"]["vinted"] = [dom for dom in VINTED_INFO if dom.split("vinted.")[1] in cods]
            continue
        m = re.match(r"^exactas?=(.+)$", tok, re.I)
        if m:
            b["exactas"] = m.group(1).lower() in ("si", "sí", "1", "on", "yes")
            continue
        m = re.match(r"^(min|max|km|excluir)=(.+)$", tok, re.I)
        if not m:
            palabras.append(tok)
            continue
        k, v = m.group(1).lower(), m.group(2)
        if k == "excluir":
            b["excluir"] += v.split(",")
        else:
            try:
                b[k] = float(v.replace(",", "."))
            except ValueError:
                pass
    b["texto"] = " ".join(palabras)
    return b

def describir(b):
    s = ("⏸ " if b.get("pausada") else "") + f"<b>{html.escape(b['texto'])}</b>"
    if b.get("min") is not None: s += f" · desde {b['min']:g}€"
    if b.get("max") is not None: s += f" · hasta {b['max']:g}€"
    if b.get("excluir"): s += f" · sin: {html.escape(', '.join(b['excluir']))}"
    if b.get("exactas"): s += " · 🎯 palabras exactas"
    if b.get("prioridad"): s += " · ⚡ prioritaria"
    if b.get("solo_chollos"): s += " · 💰 solo chollos"
    return s + " · " + donde_txt(b)

def donde_txt(b):
    f = b.get("fuentes") or FUENTES_DEFECTO
    donde = []
    banderas = ("🇪🇸" if f.get("wallapop") else "") + ("🇮🇹" if f.get("wallapop_it") else "")
    if f.get("wallapop") and b.get("km"):
        donde.append(f"Wallapop ({b['km']:g} km de {html.escape(b.get('zona') or 'tu zona')}){'🇮🇹' if f.get('wallapop_it') else ''}")
    elif banderas:
        donde.append("Wallapop " + banderas)
    v = f.get("vinted", [])
    if len(v) == len(VINTED_PAISES):
        donde.append("Vinted 🌍 todos")
    elif v:
        donde.append("Vinted " + "".join(VINTED_INFO[x][0] for x in v if x in VINTED_INFO))
    return " + ".join(donde) or "⚠️ sin fuentes"

def alerta_por_num(d, arg):
    try:
        return d["busquedas"][int(arg) - 1]
    except (ValueError, IndexError):
        return None

def menu_alerta(chat, b, msg_id=None):
    txt = (f"✏️ <b>Editar alerta</b>\n\n🔤 Búsqueda: <b>{html.escape(b['texto'])}</b>\n"
           f"💶 Precio mín.: {('%g €' % b['min']) if b.get('min') is not None else 'sin mínimo'}\n"
           f"💶 Precio máx.: {('%g €' % b['max']) if b.get('max') is not None else 'sin límite'}\n"
           f"🚫 Excluir: {html.escape(', '.join(b.get('excluir') or [])) or '—'}\n"
           f"🎯 Palabras exactas: {'Sí' if b.get('exactas') else 'No'}\n"
           f"⚡ Prioritaria (cada {PRIORIDAD_CADA} s): {'Sí' if b.get('prioridad') else 'No'}\n"
           f"💰 Solo chollos: {'Sí' if b.get('solo_chollos') else 'No'}\n"
           f"Estado: {'⏸ pausada' if b.get('pausada') else '▶️ activa'}\n\n¿Qué quieres cambiar?")
    i = b["id"]
    teclado = {"inline_keyboard": [
        [{"text": "🔤 Búsqueda", "callback_data": f"ec:{i}|texto"}],
        [{"text": "💶 Precio mín.", "callback_data": f"ec:{i}|min"}, {"text": "💶 Precio máx.", "callback_data": f"ec:{i}|max"}],
        [{"text": "🚫 Excluir palabras", "callback_data": f"ec:{i}|excluir"},
         {"text": f"🎯 Exactas: {'Sí ✅' if b.get('exactas') else 'No'}", "callback_data": f"ec:{i}|exactas"}],
        [{"text": f"⚡ Prioritaria: {'Sí ✅' if b.get('prioridad') else 'No'}", "callback_data": f"ec:{i}|prioridad"},
         {"text": f"💰 Solo chollos: {'Sí ✅' if b.get('solo_chollos') else 'No'}", "callback_data": f"ec:{i}|solo_chollos"}],
        [{"text": "▶️ Activar" if b.get("pausada") else "⏸ Pausar", "callback_data": f"ec:{i}|pausa"},
         {"text": "🗑 Borrar", "callback_data": f"ec:{i}|borrar"}],
    ]}
    if msg_id:
        r = tg("editMessageText", chat_id=chat, message_id=msg_id, text=txt, parse_mode="HTML", reply_markup=teclado)
        if r.get("ok"):
            return
    tg("sendMessage", chat_id=chat, text=txt, parse_mode="HTML", reply_markup=teclado)

PREGUNTAS = {
    "texto": "🔤 Escribe la nueva búsqueda (por ejemplo: <i>nintendo 3ds xl</i>).",
    "min": "💶 Escribe el nuevo precio mínimo en euros (por ejemplo: <i>50</i>). Escribe <b>0</b> para quitar el mínimo.",
    "max": "💶 Escribe el nuevo precio máximo en euros (por ejemplo: <i>120</i>). Escribe <b>0</b> para quitar el límite.",
    "excluir": "🚫 Escribe las palabras que no quieres, separadas por comas (por ejemplo: <i>juego, funda, roto</i>). Escribe <b>0</b> para no excluir nada.",
}

def aplicar_edicion(d, b, campo, valor):
    """Cambia un campo de la alerta y la hace reaprender lo que ya existe (sin avalancha de viejos)."""
    with LOCK:
        if campo == "texto":
            b["texto"] = valor.strip()
        elif campo in ("min", "max"):
            v = float(valor.replace(",", ".").replace("€", "").strip())
            b[campo] = None if v <= 0 else v
        elif campo == "excluir":
            b["excluir"] = [] if valor.strip() == "0" else [w.strip() for w in valor.split(",") if w.strip()]
        elif campo == "exactas":
            b["exactas"] = not b.get("exactas")
        b["inicial"] = True
    guardar(d)
    sembrar(d, b)

def nombre_vendedor(d, vid):
    for x in d.get("feed", []):
        if x.get("vendedor") == vid and x.get("vendedor_nombre"):
            return x["vendedor_nombre"]
    return d.get("silenciados_nombres", {}).get(vid) or ("vendedor de Vinted" if vid.startswith("v") else "vendedor de Wallapop")

def lista_silenciados(d, chat, msg_id=None):
    sil, bloq = d.get("silenciados", []), d.get("bloq", [])
    if not sil and not bloq:
        txt, teclado = ("🔇 Vendedores silenciados: ninguno.\n\nPara bloquear una cadena entera escribe, "
                        "por ejemplo: /bloquear cash converters"), {"inline_keyboard": []}
    else:
        txt = (f"🔇 Vendedores silenciados ({len(sil)}) y bloqueos por nombre ({len(bloq)}).\n"
               "Toca uno para quitarlo:")
        filas = [[{"text": f"🚫 «{f}» (todas sus cuentas)"[:60], "callback_data": ("ub:" + f)[:64]}] for f in bloq]
        filas += [[{"text": f"🔊 {nombre_vendedor(d, v)}", "callback_data": f"u:{v}"[:64]}] for v in sil[-40:]]
        teclado = {"inline_keyboard": filas}
    if msg_id:
        r = tg("editMessageText", chat_id=chat, message_id=msg_id, text=txt, reply_markup=teclado)
        if r.get("ok"):
            return
    tg("sendMessage", chat_id=chat, text=txt, reply_markup=teclado)

def manejar_boton(d, cq):
    chat = cq["message"]["chat"]["id"]
    if chat != d["owner"]:
        tg("answerCallbackQuery", callback_query_id=cq["id"], text="Bot privado")
        return
    tipo, _, valor = (cq.get("data") or "").partition(":")
    aviso = ""
    if tipo == "p":
        for b in d["busquedas"]:
            if str(b.get("id")) == valor:
                b["pausada"] = True
                aviso = f"⏸ Alerta «{b['texto']}» pausada. Usa /lista y /activar para reanudar."
                break
        else:
            aviso = "Esa alerta ya no existe."
    elif tipo == "s":
        if valor and valor not in d["silenciados"]:
            d["silenciados"].append(valor)
        nombre = nombre_vendedor(d, valor)
        d.setdefault("silenciados_nombres", {})[valor] = nombre
        tg("answerCallbackQuery", callback_query_id=cq["id"], text=f"🔇 {nombre} silenciado")
        botones = [[{"text": "↩️ Deshacer", "callback_data": f"u:{valor}"[:64]}]]
        sugerencia = " ".join(nombre.split()[:2]) if not nombre.startswith("vendedor de ") else ""
        if sugerencia:
            botones.insert(0, [{"text": f"🚫 Bloquear todo «{sugerencia}»"[:60],
                                "callback_data": ("bq:" + sugerencia)[:64]}])
        tg("sendMessage", chat_id=chat, parse_mode="HTML",
           text=f"🔇 <b>{html.escape(nombre)}</b> silenciado. No te llegará nada más de esta cuenta."
                + (f"\n\nSi es una cadena con varias tiendas (como Cash Converters), pulsa "
                   f"<b>Bloquear todo «{html.escape(sugerencia)}»</b> para silenciar todas sus cuentas."
                   if sugerencia else ""),
           reply_markup={"inline_keyboard": botones})
        return
    elif tipo == "bq":
        frag = valor.strip()
        if frag and _norm(frag) not in [_norm(x) for x in d.setdefault("bloq", [])]:
            d["bloq"].append(frag)
        tg("answerCallbackQuery", callback_query_id=cq["id"], text=f"🚫 Bloqueado «{frag}»")
        tg("editMessageText", chat_id=chat, message_id=cq["message"]["message_id"], parse_mode="HTML",
           text=f"🚫 Bloqueado todo lo que contenga <b>«{html.escape(frag)}»</b> (nombre del vendedor o anuncio).",
           reply_markup={"inline_keyboard": [[{"text": "↩️ Deshacer", "callback_data": ("ub:" + frag)[:64]}]]})
        return
    elif tipo == "ub":
        d["bloq"] = [x for x in d.get("bloq", []) if _norm(x) != _norm(valor)]
        tg("answerCallbackQuery", callback_query_id=cq["id"], text=f"✅ «{valor}» desbloqueado")
        if (cq["message"].get("text") or "").startswith("🔇 Vendedores silenciados"):
            lista_silenciados(d, chat, cq["message"]["message_id"])
        else:
            tg("editMessageText", chat_id=chat, message_id=cq["message"]["message_id"], parse_mode="HTML",
               text=f"✅ «{html.escape(valor)}» ya no está bloqueado.")
        return
    elif tipo == "u":
        if valor in d["silenciados"]:
            d["silenciados"].remove(valor)
        nombre = d.get("silenciados_nombres", {}).pop(valor, None) or nombre_vendedor(d, valor)
        tg("answerCallbackQuery", callback_query_id=cq["id"], text=f"🔊 {nombre} ya no está silenciado")
        if cq.get("message", {}).get("message_id"):
            if (cq["message"].get("text") or "").startswith("🔇 Vendedores silenciados"):
                lista_silenciados(d, chat, cq["message"]["message_id"])
            else:
                tg("editMessageText", chat_id=chat, message_id=cq["message"]["message_id"], parse_mode="HTML",
                   text=f"🔊 <b>{html.escape(nombre)}</b> ya no está silenciado.")
        return
    elif tipo in ("e", "ec"):
        idtxt, _, campo = valor.partition("|")
        b = next((x for x in d["busquedas"] if str(x.get("id")) == idtxt), None)
        tg("answerCallbackQuery", callback_query_id=cq["id"])
        if not b:
            enviar(chat, "Esa alerta ya no existe.")
            return
        msg_id = cq["message"]["message_id"] if tipo == "ec" else None
        if tipo == "e":
            menu_alerta(chat, b)
        elif campo in PREGUNTAS:
            d["esperando"] = {"id": b["id"], "campo": campo}
            enviar(chat, PREGUNTAS[campo] + "\n\nO escribe <b>cancelar</b>.")
        elif campo == "exactas":
            aplicar_edicion(d, b, "exactas", "")
            menu_alerta(chat, b, msg_id)
        elif campo in ("prioridad", "solo_chollos"):
            b[campo] = not b.get(campo)
            guardar(d)
            menu_alerta(chat, b, msg_id)
        elif campo == "pausa":
            b["pausada"] = not b.get("pausada")
            menu_alerta(chat, b, msg_id)
        elif campo == "borrar":
            with LOCK:
                if b in d["busquedas"]:
                    d["busquedas"].remove(b)
            tg("editMessageText", chat_id=chat, message_id=cq["message"]["message_id"],
               text=f"🗑 Alerta «{html.escape(b['texto'])}» borrada.", parse_mode="HTML")
        return
    tg("answerCallbackQuery", callback_query_id=cq["id"], text=aviso[:190], show_alert=False)
    if aviso:
        enviar(chat, aviso)

def manejar(d, msg):
    chat = msg["chat"]["id"]
    if d["owner"] is None:
        d["owner"] = chat
        enviar(chat, "✅ Bot vinculado a ti. Nadie más podrá usarlo.")
    if chat != d["owner"]:
        enviar(chat, "⛔ Este bot es privado.")
        return

    if "location" in msg:
        d["lat"], d["lon"] = msg["location"]["latitude"], msg["location"]["longitude"]
        enviar(chat, "📍 Ubicación guardada.")
        return

    texto = (msg.get("text") or "").strip()
    esp = d.get("esperando")
    if esp and texto and not texto.startswith("/"):
        d["esperando"] = None
        if texto.lower() == "cancelar":
            enviar(chat, "Cancelado."); return
        b = next((x for x in d["busquedas"] if x.get("id") == esp["id"]), None)
        if not b:
            enviar(chat, "Esa alerta ya no existe."); return
        try:
            aplicar_edicion(d, b, esp["campo"], texto)
        except ValueError:
            d["esperando"] = esp
            enviar(chat, "No he entendido el número. Escribe solo el precio, por ejemplo <b>120</b>, o <b>cancelar</b>.")
            return
        enviar(chat, "✅ Guardado.")
        menu_alerta(chat, b)
        return
    if not texto.startswith("/"):
        enviar(chat, AYUDA); return
    cmd, _, arg = texto.partition(" ")
    cmd = cmd.split("@")[0].lower()
    arg = arg.strip()
    sil = set(d["silenciados"])

    if cmd in ("/start", "/ayuda", "/help"):
        enviar(chat, AYUDA)

    elif cmd == "/nueva":
        b = parse_nueva(arg)
        if not b["texto"]:
            enviar(chat, "Escribe qué buscar. Ej: /nueva bici montaña max=200"); return
        with LOCK:
            b["id"] = d["next_id"]; d["next_id"] += 1
            b["vistos"], b["inicial"] = [], True
            d["busquedas"].append(b)
        guardar(d); sembrar(d, b)
        enviar(chat, f"✅ Alerta creada: {describir(b)}\nTe avisaré en cuanto salga algo nuevo.")

    elif cmd == "/buscar":
        b = parse_nueva(arg)
        if not b["texto"]:
            enviar(chat, "Ej: /buscar ps5 max=350"); return
        res = buscar(b, d)
        if res is None:
            enviar(chat, "⚠️ Wallapop no respondió."); return
        if not res:
            enviar(chat, "Sin resultados con esos filtros."); return
        orden = sorted(res, key=lambda i: (i["precio_num"] or 1e9) / (i.get("mediana") or 1))
        for it in orden[:5]:
            enviar_anuncio(chat, it, b, titulo="🔍 Resultado")

    elif cmd == "/lista":
        if not d["busquedas"]:
            enviar(chat, "No tienes alertas. Crea una con /nueva"); return
        lineas = [f"{i+1}. {describir(b)}" for i, b in enumerate(d["busquedas"])]
        estado = "⏸ Todo en pausa" if d["pausa"] else f"▶️ Revisando cada {d['intervalo']} s"
        enviar(chat, "\n".join(lineas) + f"\n\n{estado}")

    elif cmd in ("/pausar", "/activar"):
        b = alerta_por_num(d, arg)
        if not b:
            enviar(chat, f"Ej: {cmd} 1"); return
        b["pausada"] = cmd == "/pausar"
        enviar(chat, ("⏸ Pausada: " if b["pausada"] else "▶️ Activada: ") + describir(b))

    elif cmd == "/borrar":
        try:
            b = d["busquedas"].pop(int(arg) - 1)
            enviar(chat, f"🗑 Borrada: {describir(b)}")
        except (ValueError, IndexError):
            enviar(chat, "Usa /borrar seguido del número de /lista")

    elif cmd == "/pausa":
        d["pausa"] = True; enviar(chat, "⏸ Todas las alertas en pausa.")
    elif cmd == "/reanudar":
        d["pausa"] = False; enviar(chat, "▶️ Alertas activas.")

    elif cmd == "/estado":
        if not VINTED_ESTADO:
            enviar(chat, "Aún no he revisado Vinted. Espera un minuto y vuelve a escribir /estado."); return
        ok = [VINTED_INFO[x][0] for x, v in VINTED_ESTADO.items() if v == "ok" and x in VINTED_INFO]
        estado_walla = "✅" if WALLA_ESTADO.get("ES") == "ok" else f"❌ {WALLA_ESTADO.get('ES', '—')}"
        estado_it = "✅" if WALLA_ESTADO.get("IT") == "ok" else f"❌ {WALLA_ESTADO.get('IT', '—')}"
        enviar(chat, f"🟢 <b>Wallapop</b>  🇪🇸 {estado_walla}   🇮🇹 {estado_it}")
        mal = [f"{VINTED_INFO[x][0]} {VINTED_INFO[x][1]}: {v}" for x, v in VINTED_ESTADO.items() if v != "ok" and x in VINTED_INFO]
        enviar(chat, f"🟣 <b>Vinted</b>\n✅ Funcionan ({len(ok)}): {''.join(ok) or '—'}\n"
                     + (f"❌ Fallan ({len(mal)}):\n" + "\n".join(mal) if mal else "❌ Ninguno falla"))

    elif cmd == "/actualizar":
        enviar(chat, "🔄 Buscando actualizaciones…")
        threading.Thread(target=actualizar, args=(d, True), daemon=True).start()

    elif cmd == "/version":
        enviar(chat, f"WallaBot versión <b>{VERSION}</b>")

    elif cmd == "/notificacion":
        if not shutil.which("termux-notification"):
            enviar(chat, "⚠️ Falta Termux:API. Instala la app Termux:API y en Termux escribe: <code>pkg install termux-api</code>"); return
        notificar_movil(dict(d, notif_movil=True), {"titulo": "Prueba de WallaBot", "precio": "0 €", "origen": "✅ Funciona",
                        "url": "https://es.wallapop.com"}, {"texto": "prueba"})
        enviar(chat, "📲 Te he mandado una notificación de prueba al móvil.")

    elif cmd == "/silenciados":
        lista_silenciados(d, chat)

    elif cmd == "/bloquear":
        if not arg:
            enviar(chat, "Escribe qué nombre bloquear. Ej: <code>/bloquear cash converters</code>"); return
        if _norm(arg) not in [_norm(x) for x in d.setdefault("bloq", [])]:
            d["bloq"].append(arg)
        enviar(chat, f"🚫 Bloqueado todo lo que contenga <b>«{html.escape(arg)}»</b> en el nombre del vendedor o en el anuncio.\n"
                     "Para quitarlo: /silenciados")

    elif cmd == "/desbloquear":
        d["bloq"] = [x for x in d.get("bloq", []) if _norm(x) != _norm(arg)]
        enviar(chat, f"✅ «{html.escape(arg)}» desbloqueado.")

    elif cmd == "/solonuevos":
        solo_nuevos(d)
        enviar(chat, "🧹 Avisos pendientes cortados. Desde ahora solo te llegará lo que se publique nuevo.")
    elif cmd == "/limpiar":
        d["silenciados"] = []; d["silenciados_nombres"] = {}; enviar(chat, "Lista de silenciados vaciada.")

    elif cmd == "/intervalo":
        try:
            d["intervalo"] = max(15, int(arg)); enviar(chat, f"⏱ Revisaré Wallapop cada {d['intervalo']} s (Vinted cada minuto).")
        except ValueError:
            enviar(chat, "Ej: /intervalo 60")

    elif cmd == "/ubicacion":
        try:
            lat, lon = [float(x.replace(",", ".")) for x in arg.split()[:2]]
            d["lat"], d["lon"] = lat, lon; enviar(chat, "📍 Ubicación guardada.")
        except ValueError:
            enviar(chat, f"Actual: {d['lat']}, {d['lon']}\nEnvíame tu ubicación 📍 o escribe /ubicacion LAT LON")

    elif cmd == "/probar":
        b = alerta_por_num(d, arg)
        if not b:
            enviar(chat, "Ej: /probar 1"); return
        res = buscar(b, d)
        if res is None:
            enviar(chat, "⚠️ Wallapop no respondió.")
        elif not res:
            enviar(chat, "Sin resultados con esos filtros.")
        for it in (res or [])[:3]:
            enviar_anuncio(chat, it, b, titulo="🧪 Prueba")
    else:
        enviar(chat, AYUDA)

# ---------------- Panel web (http://localhost:8080) ----------------
PANEL_HTML = r"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#13C1AC">
<title>WallaBot</title>
<link rel="manifest" href="/manifest.json">
<link rel="icon" type="image/png" href="/icon-192.png">
<link rel="apple-touch-icon" href="/icon-192.png">
<style>
:root{--verde:#13C1AC;--verde2:#0E9C8B;--fondo:#F4F6F8;--tarjeta:#fff;--texto:#1D2A33;--suave:#6B7B86;--borde:#E2E8EC;--rojo:#E5484D}
@media (prefers-color-scheme:dark){:root{--fondo:#0F1418;--tarjeta:#1A2228;--texto:#E8EEF1;--suave:#8FA0AA;--borde:#2A353D}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;font-family:system-ui,-apple-system,Roboto,sans-serif;background:var(--fondo);color:var(--texto)}
header{background:var(--verde);color:#fff;padding:22px 16px 18px}
header h1{margin:0;font-size:22px}header p{margin:4px 0 0;opacity:.9;font-size:14px}
main{padding:16px;max-width:560px;margin:0 auto}
.tabs{display:flex;background:var(--verde);padding:0 12px;position:sticky;top:0;z-index:5}
.tabs button{flex:1;border:0;background:none;color:rgba(255,255,255,.75);font-size:15px;font-weight:600;padding:12px 0;border-bottom:3px solid transparent}
.tabs button.on{color:#fff;border-bottom-color:#fff}
.tabs b{background:#fff;color:var(--verde2);border-radius:99px;font-size:11px;padding:1px 7px;margin-left:4px}
.tabs b:empty{display:none}
.link{border:0;background:none;color:var(--verde);font-size:14px;font-weight:600}
.anuncio{display:flex;gap:12px;background:var(--tarjeta);border:1px solid var(--borde);border-radius:14px;padding:10px;margin-bottom:10px;text-decoration:none;color:var(--texto)}
.anuncio img,.anuncio .sinfoto{width:88px;height:88px;border-radius:10px;object-fit:cover;flex-shrink:0;background:var(--fondo)}
.anuncio .sinfoto{display:flex;align-items:center;justify-content:center;font-size:28px}
.anuncio .cuerpo{flex:1;min-width:0}
.anuncio .tit{font-size:15px;font-weight:600;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.anuncio .pre{font-size:18px;font-weight:800;margin:3px 0}
.anuncio .meta{font-size:12px;color:var(--suave);line-height:1.5}
.anuncio .cho{font-size:12px;font-weight:600;color:var(--verde2)}
.anuncio{cursor:pointer;flex-wrap:wrap}
.comprar{flex-basis:100%;margin-top:8px;border:0;border-radius:10px;padding:12px;font-size:16px;font-weight:800;background:var(--verde);color:#fff}
.comprar:active{background:var(--verde2)}
.card{background:var(--tarjeta);border:1px solid var(--borde);border-radius:16px;padding:16px;margin-bottom:16px}
h2{font-size:16px;margin:0 0 12px}
.check{display:flex;gap:8px;align-items:center;color:var(--texto);font-size:15px}.check input{width:20px;height:20px;accent-color:var(--verde)}
label{display:block;font-size:13px;color:var(--suave);margin:12px 0 6px}
input[type=text],input[type=number],select{width:100%;padding:12px;border:1px solid var(--borde);border-radius:12px;font-size:16px;background:var(--fondo);color:var(--texto)}
.fila{display:flex;gap:10px}.fila>div{flex:1}
input[type=range]{width:100%;accent-color:var(--verde)}
.btn{display:block;width:100%;border:0;border-radius:12px;padding:14px;font-size:16px;font-weight:600;background:var(--verde);color:#fff;margin-top:16px}
.btn:active{background:var(--verde2)}
.btn.sec{background:transparent;color:var(--verde);border:1px solid var(--verde);margin-top:10px}
.alerta{border:1px solid var(--borde);border-radius:14px;padding:12px;margin-bottom:10px}
.alerta.off{opacity:.55}
.alerta b{font-size:16px}.chips{margin-top:6px;display:flex;flex-wrap:wrap;gap:6px}
.pais{font-size:14px;border:1px solid var(--borde);border-radius:99px;padding:6px 10px;background:var(--tarjeta);color:var(--texto)}
.pais.on{background:var(--verde);border-color:var(--verde);color:#fff}
.desp{margin-top:8px;border:1px solid var(--borde);border-radius:12px;padding:12px;background:var(--fondo)}
.desp summary{font-size:15px;cursor:pointer;list-style:none;display:flex;justify-content:space-between}
.desp summary::after{content:'▾';color:var(--suave)}.desp[open] summary::after{content:'▴'}
.desp summary::-webkit-details-marker{display:none}
.chip{font-size:12px;background:var(--fondo);border:1px solid var(--borde);border-radius:99px;padding:3px 9px;color:var(--suave)}
.acciones{display:flex;gap:8px;margin-top:10px}
.acciones{flex-wrap:wrap}.acciones button{flex:1 1 18%;min-width:56px;padding:9px 4px!important;font-size:13px!important;border:1px solid var(--borde);background:var(--tarjeta);color:var(--texto);border-radius:10px;padding:9px;font-size:14px}
.acciones .del{color:var(--rojo)}
.vacio{color:var(--suave);text-align:center;padding:10px 0}
.aviso{background:#FFF4D6;color:#6B4E00;border-radius:12px;padding:12px;font-size:14px;margin-bottom:16px}
.toast{position:fixed;left:16px;right:16px;bottom:20px;background:#1D2A33;color:#fff;padding:14px;border-radius:12px;text-align:center;opacity:0;transition:.3s;pointer-events:none}
.toast.ver{opacity:1}
.estado{display:flex;align-items:center;gap:8px;font-size:14px}
.punto{width:10px;height:10px;border-radius:50%;background:var(--verde)}
.punto.off{background:var(--rojo)}
</style></head><body>
<header><h1>🎯 WallaBot</h1><p>Wallapop + Vinted, al minuto</p></header>
<nav class="tabs">
 <button data-t="encontrados" class="on" onclick="tab('encontrados')">📰 Encontrados <b id="nfeed"></b></button>
 <button data-t="alertas" onclick="tab('alertas')">🔔 Alertas</button>
</nav>
<main>
<div id="hora" style="font-size:12px;color:var(--suave);text-align:right;margin:-6px 0 8px"></div>
<div id="aviso"></div>

<section id="t-encontrados">
 <select id="fAlerta" onchange="pintaFeed()"><option value="">Todas las alertas</option></select>
 <input type="text" id="fTexto" placeholder="🔎 Filtrar por palabra…" oninput="pintaFeed()" style="margin-top:10px">
 <div style="display:flex;justify-content:space-between;align-items:center;margin:10px 0">
  <span id="cuenta" style="font-size:13px;color:var(--suave)"></span>
  <button class="link" onclick="borrarFeed()">🗑 Borrar historial</button>
 </div>
 <div id="feed"><div class="vacio">Cargando…</div></div>
</section>

<section id="t-alertas" hidden>
<div class="card">
<h2 id="titForm">➕ Nueva alerta</h2>
<label>¿Qué buscas?</label>
<input type="text" id="texto" placeholder="Ej: nintendo switch, ps5, iphone 13…">
<div class="fila">
 <div><label>Precio mínimo (€)</label><input type="number" id="min" inputmode="decimal" placeholder="Sin mínimo"></div>
 <div><label>Precio máximo (€)</label><input type="number" id="max" inputmode="decimal" placeholder="Sin límite"></div>
</div>
<label>No quiero anuncios con estas palabras (separadas por comas)</label>
<input type="text" id="excluir" placeholder="Ej: juego, funda, roto">
<label class="check" style="margin-top:14px"><input type="checkbox" id="chollos"> 💰 Solo chollos: avisar solo si está al menos un 10 % por debajo del precio típico</label>
<label class="check" style="margin-top:14px"><input type="checkbox" id="prioridad"> ⚡ Prioritaria: revisar cada 8 segundos (para lo que más te importa)</label>
<label class="check" style="margin-top:14px"><input type="checkbox" id="exactas"> 🎯 Palabras exactas: el título debe decir <b>todas</b> las palabras que busco</label>
<p style="font-size:12px;color:var(--suave);margin:10px 0 0">Busca en Wallapop 🇪🇸🇮🇹 y Vinted en todos los países.</p>
<button class="btn" id="btnCrear" onclick="crear()">Crear alerta</button>
<button class="btn sec" id="btnCancelar" onclick="cancelarEdicion()" hidden>Cancelar</button>
</div>

<div class="card">
<h2>🔔 Mis alertas</h2>
<div id="lista"><div class="vacio">Cargando…</div></div>
</div>

<div class="card">
<h2>⚙️ Ajustes</h2>
<div class="estado"><span class="punto" id="punto"></span><span id="estadotxt"></span></div>
<button class="btn sec" id="btnpausa" onclick="pausaGeneral()"></button>
<label>Revisar cada</label>
<select id="intervalo" onchange="ajustes({intervalo:+this.value})">
 <option value="15">15 segundos (máxima velocidad)</option><option value="20">20 segundos (recomendado)</option>
 <option value="30">30 segundos</option><option value="60">1 minuto</option>
 <option value="120">2 minutos</option><option value="300">5 minutos</option>
</select>
<label class="check" style="margin-top:12px"><input type="checkbox" id="notifmovil" onchange="ajustes({notif_movil:this.checked})"> 📲 Notificaciones del móvil (además de Telegram)</label>
<p id="notifaviso" style="font-size:12px;color:var(--suave);margin:6px 0 0"></p>
<label>Avisarme solo de anuncios publicados hace menos de</label>
<select id="maxedad" onchange="ajustes({max_edad:+this.value})">
 <option value="0">Sin límite: todo lo nuevo que detecte (recomendado)</option>
 <option value="5">5 minutos</option><option value="10">10 minutos</option><option value="15">15 minutos</option><option value="30">30 minutos</option><option value="60">1 hora</option>
</select>
<label>Bloquear vendedores o cadenas por nombre (todas sus tiendas)</label>
<div class="fila"><div style="flex:3"><input type="text" id="nbloq" placeholder="Ej: cash converters"></div>
<div><button class="btn" style="margin:0;padding:12px" onclick="bloquearNombre()">Bloquear</button></div></div>
<div class="chips" id="lbloq" style="margin-top:8px"></div>
<label>Vendedores silenciados: <b id="nsil">0</b></label>
<div class="chips" id="lsil"></div>
<button class="btn sec" onclick="if(confirm('¿Quitar el silencio a todos?'))post('/api/limpiar').then(cargar)">Quitar silencio a todos</button>
<button class="btn sec" onclick="post('/api/solonuevos').then(r=>{toast(r.msg);cargar()})">🧹 Cortar avalancha: solo lo nuevo desde ahora</button>
</div>
</section>
</main>
<div class="toast" id="toast"></div>
<script>
const $=id=>document.getElementById(id);
function toast(t){const x=$('toast');x.textContent=t;x.classList.add('ver');setTimeout(()=>x.classList.remove('ver'),2500)}
async function post(url,body){
 try{const r=await fetch(url,{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});return await r.json()}
 catch(e){return {msg:'⚠️ No conecta con el bot. ¿Está abierto en Termux?'}}}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
let E={};
async function cargar(){
 try{E=await (await fetch('/api/estado?t='+Date.now(),{cache:'no-store'})).json()}
 catch(e){$('estadotxt').textContent='⚠️ No conecta con el bot. Ábrelo en Termux.';$('punto').className='punto off';return}
 $('aviso').innerHTML=E.owner?'':'<div class="aviso">Primero abre tu bot en Telegram y escríbele <b>/start</b> para vincularlo.</div>';
 const L=E.busquedas;
 $('lista').innerHTML=L.length?L.map(b=>{
  const ch=[];
  if(b.min!=null)ch.push('desde '+b.min+' €');
  if(b.max!=null)ch.push('hasta '+b.max+' €');
  if(b.exactas)ch.push('🎯 palabras exactas');
  if(b.prioridad)ch.unshift('⚡ prioritaria');
  if(b.solo_chollos)ch.push('💰 solo chollos');
  (b.excluir||[]).filter(x=>x.trim()).forEach(x=>ch.push('sin '+x.trim()));
  if(b.pausada)ch.unshift('⏸ pausada');
  return `<div class="alerta ${b.pausada?'off':''}"><b>${esc(b.texto)}</b>
  <div class="chips">${ch.map(c=>`<span class="chip">${esc(c)}</span>`).join('')}</div>
  <div class="acciones">
   <button onclick="accion(${b.id},'toggle')">${b.pausada?'▶️ Activar':'⏸ Pausar'}</button>
   <button onclick="verEncontrados(${b.id})">📰 Ver</button>
   <button onclick="editar(${b.id})">✏️ Editar</button>
   <button onclick="accion(${b.id},'probar')">🧪 Probar</button>
   <button class="del" onclick="if(confirm('¿Borrar esta alerta?'))accion(${b.id},'borrar')">🗑</button>
  </div></div>`}).join(''):'<div class="vacio">Aún no tienes alertas. Crea la primera arriba 👆</div>';
 $('punto').className='punto'+(E.pausa?' off':'');
 $('estadotxt').textContent=E.pausa?'Todas las alertas en pausa':'Funcionando · revisa cada '+(E.intervalo>=60?E.intervalo/60+' min':E.intervalo+' s');
 $('btnpausa').textContent=E.pausa?'▶️ Reanudar todo':'⏸ Pausar todo';
 $('intervalo').value=String(E.intervalo);
 $('maxedad').value=String(E.max_edad);
 $('notifmovil').checked=!!E.notif_movil;
 $('notifaviso').textContent=E.termux_api?'':'⚠️ Falta instalar Termux:API para que salgan.';
 $('nsil').textContent=E.silenciados;
 $('lbloq').innerHTML=(E.bloq||[]).map(f=>`<button class="pais" onclick="post('/api/desbloquear',{f:'${esc(f).replace(/'/g,"&#39;")}'}).then(r=>{toast(r.msg);cargar()})">🚫 ${esc(f)} ✕</button>`).join('');
 $('lsil').innerHTML=(E.lsil||[]).map(v=>`<button class="pais" onclick="post('/api/desilenciar',{id:'${esc(v.id)}'}).then(r=>{toast(r.msg);cargar()})">🔊 ${esc(v.nombre)} ✕</button>`).join('');
 $('hora').textContent='Actualizado '+new Date().toLocaleTimeString('es-ES');
 const vSel=$('fAlerta').value;
 $('fAlerta').innerHTML='<option value="">Todas las alertas</option>'+E.busquedas.map(b=>`<option value="${b.id}">${esc(b.texto)}</option>`).join('');
 $('fAlerta').value=vSel;
}
async function crear(){
 const texto=$('texto').value.trim();
 if(!texto){toast('Escribe qué buscas');return}
 const mx=$('max').value, mn=$('min').value;
 toast(EDIT?'Guardando…':'Creando alerta…');
 const r=await post(EDIT?'/api/editar':'/api/crear',{id:EDIT,texto,min:mn===''?null:+mn,max:mx===''?null:+mx,
   exactas:$('exactas').checked,prioridad:$('prioridad').checked,solo_chollos:$('chollos').checked,
   excluir:$('excluir').value.split(',').map(s=>s.trim()).filter(Boolean)});
 toast(r.msg);
 if(r.ok){cancelarEdicion();await cargar();
   $('lista').scrollIntoView({behavior:'smooth'})}
}
let EDIT=null;
function editar(id){
 const b=E.busquedas.find(x=>x.id===id);if(!b)return;
 EDIT=id;
 $('texto').value=b.texto;$('min').value=b.min??'';$('max').value=b.max??'';
 $('excluir').value=(b.excluir||[]).join(', ');$('exactas').checked=!!b.exactas;$('prioridad').checked=!!b.prioridad;$('chollos').checked=!!b.solo_chollos;
 $('titForm').textContent='✏️ Editar alerta';$('btnCrear').textContent='Guardar cambios';$('btnCancelar').hidden=false;
 $('titForm').scrollIntoView({behavior:'smooth'});
}
function cancelarEdicion(){
 EDIT=null;['texto','min','max','excluir'].forEach(i=>$(i).value='');$('exactas').checked=false;$('prioridad').checked=false;$('chollos').checked=false;
 $('titForm').textContent='➕ Nueva alerta';$('btnCrear').textContent='Crear alerta';$('btnCancelar').hidden=true;
}
async function bloquearNombre(){
 const f=$('nbloq').value.trim();if(!f){toast('Escribe un nombre');return}
 const r=await post('/api/bloquear',{f});toast(r.msg);$('nbloq').value='';cargar();
}
async function accion(id,a){const r=await post('/api/'+a,{id});toast(r.msg);cargar()}
async function ajustes(o){const r=await post('/api/ajustes',o);toast(r.msg);cargar()}
function pausaGeneral(){ajustes({pausa:!E.pausa})}
function tab(t,sinScroll){
 if(t!=='alertas')t='encontrados';
 document.querySelectorAll('.tabs button').forEach(b=>b.classList.toggle('on',b.dataset.t===t));
 $('t-alertas').hidden=t!=='alertas';$('t-encontrados').hidden=t!=='encontrados';
 try{localStorage.setItem('tab',t)}catch(e){}
 try{history.replaceState(null,'','?tab='+t)}catch(e){}
 if(t==='encontrados')cargarFeed();
 if(!sinScroll)window.scrollTo(0,0);
}
let FEED=[];
async function cargarFeed(){
 try{FEED=(await (await fetch('/api/feed?t='+Date.now(),{cache:'no-store'})).json()).items||[]}catch(e){return}
 $('nfeed').textContent=FEED.length||'';
 pintaFeed();
}
function hace(c,v){
 let t=c?(c>1e11?c/1000:c):v;if(!t)return '';
 const s=Math.max(0,Date.now()/1000-t);
 if(s<60)return 'ahora mismo';if(s<3600)return 'hace '+Math.floor(s/60)+' min';
 if(s<86400)return 'hace '+Math.floor(s/3600)+' h';return 'hace '+Math.floor(s/86400)+' días';
}
function pintaFeed(){
 const fa=$('fAlerta').value,q=$('fTexto').value.trim().toLowerCase();
 const L=FEED.map((x,i)=>[x,i]).filter(([x])=>(!fa||String(x.alerta_id)===fa)&&(!q||(x.titulo||'').toLowerCase().includes(q)))
  .sort((a,b)=>((b[0].visto_ts||0)-(a[0].visto_ts||0))||(a[1]-b[1])).map(a=>a[0]);
 $('cuenta').textContent=L.length+' anuncio'+(L.length===1?'':'s')+' · el más reciente arriba';
 $('feed').innerHTML=L.length?L.slice(0,300).map(x=>`<div class="anuncio" onclick="abrirApp('${esc(x.url)}')">
  ${x.foto?`<img loading="lazy" src="${esc(x.foto)}" alt="">`:'<div class="sinfoto">🛍</div>'}
  <div class="cuerpo"><div class="tit">${esc(x.titulo||'')}</div>
  <div class="pre">${esc(x.precio||'')}</div>
  ${x.chollo?`<div class="cho">${esc(x.chollo)}</div>`:''}
  <div class="meta">${esc(x.origen||'')} · ${esc(x.ciudad||'')}<br>📩 Encontrado ${hace(null,x.visto_ts)}${x.vendedor_nombre?' · 👤 '+esc(x.vendedor_nombre):''}<br>🔔 ${esc(x.alerta||'')}</div>
  <button class="comprar" onclick="event.stopPropagation();abrirApp('${esc(x.url)}')">🛒 VER ANUNCIO</button>
  </div></div>`).join(''):`<div class="vacio">${FEED.length?'Nada con este filtro':'Aquí verás todo lo que te envíe el bot, lo último arriba.'}</div>`;
}
// Abre el anuncio DIRECTAMENTE en la app de Wallapop o Vinted (sin pasar por Chrome ni preguntar)
function abrirApp(url){
 try{
  const u=new URL(url);let pkg=null;
  if(/(^|\.)wallapop\.com$/.test(u.hostname))pkg='com.wallapop';
  else if(/(^|\.)vinted\./.test(u.hostname))pkg='fr.vinted';
  if(pkg&&/Android/i.test(navigator.userAgent)){
   location.href='intent://'+u.host+u.pathname+u.search+'#Intent;scheme=https;package='+pkg+';S.browser_fallback_url='+encodeURIComponent(url)+';end';
   return;
  }
 }catch(e){}
 location.href=url;
}
function verEncontrados(id){tab('encontrados');$('fAlerta').value=String(id);$('fTexto').value='';pintaFeed()}
async function borrarFeed(){
 const fa=$('fAlerta').value;
 if(!confirm(fa?'¿Borrar el historial de esta alerta?':'¿Borrar todo el historial?'))return;
 const r=await post('/api/feed_borrar',fa?{alerta_id:+fa}:{});toast(r.msg);cargarFeed();
}
(function(){
 let t=new URLSearchParams(location.search).get('tab');
 if(!t){try{t=localStorage.getItem('tab')}catch(e){}}
 tab(t||'encontrados',true);
})();
cargar().then(()=>{if(!$('t-encontrados').hidden)cargarFeed()});
setInterval(()=>{cargar();if(!$('t-encontrados').hidden)cargarFeed()},15000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!$('t-encontrados').hidden)cargarFeed()});
</script></body></html>"""

import base64
ICONOS = {"/icon-192.png": "iVBORw0KGgoAAAANSUhEUgAAAMAAAADACAYAAABS3GwHAAAs80lEQVR42u19aZRU13Xut88dqmvqoXoEITUIEGIQSAZJlm0mRUhJjAdZEoqfI9lxLI9x/OLYfrafHVDkFQ+J/RLnxYMSO7blOBGDZMdKbIyeGoRHAZJAgECAAIGAnru6pq47nP1+3HuLbgR0VVPdVHefvVatJdE13HPv/s7+9j57IIyVMBO2btXQ2clYs8Yd9O9a3Y4n5mqCWjmdez2I5rChT4dla0S0CEQamKFkHAoRwOwy826Yhku2cwzMBykW/q0r+XjvjatfBNFZXVi/XkNjI2HFChdEY/LQadR/Ye1agRUrBFaudIJ/SrRtmgZD3EYavQmuvAnAbNL1KmgawAxI6WEjbyklmgg4CJnefwjhgcJ1wY4zAOAQNPEMu/xL2PLJnpV3nSx8qK1Nx9atEg8+KMcnANauFZg/n4Ldvuk3P2lm0B+67L4dLq8U0UgcAGDZYMsCpGQQyXOuSyj1mRASPFf2rb6AEESmCZiG94ZMNgWN2jTSfkzg/+645W3tBauwbx+PFhDKDwBmwoYNIlD8ul9tWqAJ/d3suvdRNNIMV4JzA4DrBmZO+NdBSk8mlbD/kmAmaJpG4SpAE+BMtp007RFXOt/vfeNdewtAuOceWW5qVF6la2vTA6pT17ZpgQiJj4PpXRQJm5zJAo7j+rxQgEgpvJLBG6fHAJgBXdcoGgFncxaI/03m5dd6V/pAGKRjlQMAZvKdHm7e/IMmJ1b9OQj6AIVMk1MZAOyAoSmlV1I8GOACpFM8Cs5bFiR/W0/3f6H9jvs7Buvbpf7UpXNsXq+BiEHEie2PvdeOxZ+jcNVHYdkm96ddz8yRrpRfSQnRIwJIB8Dcn3Zh2SaFqz5qx+LPJbY/9t5A38DrtctrAXxzVP/jH01FQ+S7FA3fwdksYDsuiITi9UrK5i8wSxi6RpEIOJPbjK7se7vf/j9OXSolohF/jplAJOue2niHCOn/SlXmFE5nFNVRMurUiGJRnQes0zLv/EnvrXdv9n3KwKkeZQq0dq0IlL/hl4+t1SLmz4kwhVMZV1EdJWNBjTiVcYkwRYuYP2/45WNrfeeZsHZtyfpMJSu/H4+t377pYVFb84Ds6XN9QKiYvZKxtAYSRCwStZrsS/5z99K73n+ujpYXAP4X1zzxb3V6ffRbFAqt4f6MDYKuuL6Sy+cbwKHqqMH5/HqnO/PB5Op39ZYCAq1o5V+3DjU3XlOrJSKbtWj0dk72OyAylPIruZykCAQN+bwjquPXQcet5p1v3Zh//0fzAAjbtvHwXzC8qfFOaYlk/dObNlJN9V3c22eByFT3X0kFUSKL6mpNTvZv6l52191gFgB4uLOCYni7AJGs37bxYYpF7uLeXkcpv5IKdJBN7u11KBa5q37bxof9vDIxvHJfTNradBC59W2PrhP1dQ94nF/o6m4rqUwQCJ37M7aor3ugvu3RdSBy0damj4wCrV+vYc0aN/Hk+lUiHv4F5/NejF9xfiWV7hgTXAqFdJnK3d5z25otgS4XbwHWrhVYs8ZtevJHzVSlP8Kuy5CsTnaVjA/HWLJg12Wq0h9pevJHzVizxr3QGcH5ATB/PoHXCtc0H6FwVTMsW6o4v5Jx5A8IWLakcFWza5qPgP3alKIoELMGIjfx1IZ3i0TN97gv6YBI8X4l45AMsUO1NbrsSb6n59Z7vh/o9oUBwExYt45qbrymRq8N7weJJjjO8M6yEiWVKRK6DrDscPpy85I7Xkpi3bohodGhir1hg8CDD0otajxE0UgLbJuV8isZxyJg20zRSIsWNR7Cgw9KbNggzm8B/IOD+qc2XIOIuRe2KwqHYEqUjGMiBCKGoUlkrQXdt97zEvyD3aEWYMMGAhFD0GcpFNIhJSvlVzIRXGJIyRQK6RD0WRAxNmygoRbA3/0T2x6/lkzxHBzXULu/kglnBXTNZkve0LP8zgOBFfAswNatAkRM7LyPIuEQWEql/EomlBVgKSkSDhE77wMRY+tW4f+BCUJwbNujjSHS94KoEY4DVdiiZGLZAGYvIsSdeXYWpJff2wkpSWDrVg3MCLtYTfFoExxHKuVXMvFsABEcR1I82hR2sRrMwNatmsCKTgYAF7gbjstQuq9k4oIAcFx2gbsBACs6vf4qjW3rW1xdP0RADK7LygIombA0SNOIgbTmOLM7V645IwBAamKVFovG/HaFSvmVTFwa5LquFovGpCZWAYVzAFoOZoCg+pArmeAgAHvt9mm5B4CdOw248hZp2QBUxqeSCY8AIS0bcOUt2LnTEHWp43OgiZmwrEEWQYmSCSsClgVoYmZd6vgcIYScSYYR8lMflCiZ+CIlk2GEhJAzBTMtgqFj0HAKJUomujMsYehgpkU6ga8LRhIpGc5/8m2oHygL/l9e1N56EphX6c87U+b2slsBEPg6nUGzyAOACn+eT4GJCkpsM8NhibwrIZnhMIMAmOLCrpMlJRiATgRBhJAQ0EnA8EEkB4FCyRjuZVKCQbN0gNX2fwGlt5mRdmxY/i1K6CE0mGHMDMfQaIYwL1oDnQiL4/XQyYshk7+7EwCHGbtS3XCYsT+TRKeVx5FcGr22hS47DwAwSSCs6TCIFBjGXFhS/daNDgjapFd6EAR5SptxHVgskdBNLIzVYkl1PRZEa3BTTT1azDBqdGPEv5N0bJyxcngm2Y29mSR29ndjT7oPPY4FkwSimg6dCJIBqYjSKOs/XB1ics/h1XwqknEdDEgXtbqJpbVNeHPDVNxRPwXXRqpfSx/9sxQ+xzc4/z0++x4ioEY3UKMbmDPoew9k+7G5+zT+q+sUnk31oMvOo0poiGpeLwJXWYXRMvUa1W/byJNz7QQwkHJtuMy4LlaLu5uuxJ2NV+LaaPUQBQ5oiafEdEnOEsNLSeFB1zH4+w5k+vF45wls7DiBF9J90IgQ1wyAFD0aFWdgsgGAQNAISLkOBICbaxrwnilXY03TVQVnlv1dV5BHjUY9IAGGZM8a0SDneX3HK/je6Zfxu2QXJIC4psNlrye4EgWAkkUnQk66yLguFscT+MLMhViVaCn83WUvG1xcxoBYQK+0QTmJW3rO4HNH9mBXqgdRTUNYaHCUNVAAKMXBZTB6HQszw3F8fsYC3Nt8FQwSBYojLpHalN8/G3pdNks82v4KHjq6F0dyKdTpJgikHGUFgOF3/ax04TDjI9Nm43+1zkODESrs+No4yP4efJ1ddh5fPr4f/3TyEHQiRJQ1UAC4mPL32Bamh6P41rU34da65oJCVdqOX6xFCIDwVG87PnjgGRzLZZAwTAWCEbODCenoes5uh5XH6oYrsH3xKtxa1wzHj75o40z5gzVp/mGbw4xb65qxffEqrG64Ah1WHgRSR/kKAF5Y0QUjKx38zaxFeGzhUjSbVXCZodP4VxLyLZvLjGazCo8tXIq/mbUIWenABRfylJRMQgBoRLCkhCMZ35pzIz7dOg/uoF1/oq01CNd+unUevjXnRjiSYUk54dY6qjR5IvH9jOuiVjewaeFS3FRdD5u5kHQ2Gpx88IEWX2C3LlCyUbA+AS2ymXHflBmYE63GXXu2o8+xEdWUczxpLIDmK3+NbuCni5bjpup6OGVW/mC3dZgh/SxQQQTNf+nneQV/CxzuIIPU5fIeZRlEcJhxU3U9frpoOWp0AxnXVZZgMkSBhE974pqOny5ajuvjdXB8vl8OkcyQvoUZLDnp4ngugzPWALKug91+2kIgLjMWxWoR0XS0mFVoDUcRFkNzDh1mCKBsvD1Y9/OpXrxl9zakXAemECqFYqICgAC4AGzpYuvi27A4niib8p8bKnWZsTPVg7aeduxIdeNQNoVT+RzSrgPAS104V4LUipimY2oojNmROG6M12NlohlL4okCYM4NcZYDBLtSPVix60kYQoMGVYAzMQFAhIzj4OG5N+GPW6aXRfml1x6mkA6xN53Ef7Qfw5aeM9if6UfGdWAIgRAJmEIUlJYuQJsC8FhSIs8StpSIajrmRauxKtGCP2qejgWxGu+34aWYXqpFCO7DD88cw/tffAZRXQcrKzCxAKATod3K4yuzrscnW+desvKf76DpH04cxPa+DiQdG2Hh5eAE0RdZYlIa+fUG5AMiJ13kpOe3LK1twseunFPWg7rgfvzt8RfxqcPPo9kMKad4ogBAJ0K3beGtDVdg08KlcFhCo5GnsA1ONdjW24GvvnIAT/aegWRGbJQKVAYX4KRdB4IIt9W14C+vuhbL65pec10jc9oldBK4a892/GfXq6hXJ8bjHwACwABLNBtV+PWS29FghnApg8yCnbLdGsCDR/fiB6ePwmYXNbpZ2K3HIorFAJKOBYM03D9lBtbOWIBms+qSLFsw5KHLyuMNO3+BdnsAVSSgamCH6tN4I/6wpcR35t2MRjPkZUxeAuXRidDW246lu7bgW68eQkTTUKubkH64cizE9UOrtbqJiKbhW68ewtJdW9DW2+5bn5GFTYW/xkYzhO/Muxm2lFDdv8cxADzqk8fHrpyDZbVNcEZIEYKdURDhS8f3Y/XubThjDaDZqBpTxb8QEJqNKpyxBrB69zZ86fj+s+cII7QuDjOW+X5Gt50vW4hYAWAsN34AOSkxKxzDZ6bPH3HYMLAYGdfBhw/uwGcOP4+opqOKNNgV0iDDZokq8mqCP3P4eXz44A5k/Aq2kcT0Nd+KfGb6fMwKx5CTUiXOjTcAaERIuzb++upFqNENjGSEpfR3/aRjY/XubfjmycNoMcNg5hE5uINPgy90EjzSWI5XGcZoMcP45snDWL17G5KODeG3Tyn1OhleQf5fX70IaddWp8TjCQCCCP2ugyXxBO5snFaolCqV85Mffrxzz9PY3teJKWYVbC5N9YP8Gy3IOnUd9DkWOq08Oga9uuw8ko6NvHQL9G0k12yzxBSzCtv7OnHnnqeRky5oBD6B8K3AnY3TsCSeQL8feZrsoo8npH551g0whfDi5CPg1zoRPvHSc2jr7UBLqOq8p7fDKX5eSmQcGwyg0QhhTqwaV4TCeF08AZ0EGAwCIelY2JPuwysDWbyaz6LTzg/p+1NKPpDFEo1mCG29HfjEoefwT3OWlBwdCnwIUwh8edYNWL17q9r+xwMANCIkHQdLaxuwoq5pRNx/8KHQN068hJZQ2IuIlOB8D0gXvY6DqaEw7qifgrc0XIFltU2YGgpf9Hpy0sXxgcxr+v7U6GYBCEX5BVKixazCN068hOlV0REd/gW+wIq6JtxS04DtfV2o0fVJ3Xeo4s8BNL+s8Qfzb8E7m1tLPhwK3v90Xwd+/7k2xHSjaEcyKKbvc2xcVRXBA1Nn4f4pMzA1FH6NYy0vYLXOpRn7Mkl84+QhPNp+HGnXQa1ulGQNBBHSjo2f37ASy2qbRnw//r39OO7f9xskDFMBoJJpT1ZKzInE8Zslt3vpzSWkCEgAYEaXbeGNu36Bdqv4gyDNb6HiMOPPpl2DT141F41mqKDwDC+kPpyby/BSJs7t+/Niph//+8hu/GfXSdTqJkSRHR4KB4FmFX61+HY0GCYwqIFvMX4FmGEz45adv8DBbAoRMXkPxyraCRZEyLkO7m1u9bh/iZEf9p3lh46+gCPZNKJCK+pB60Tod2y0mFV4YtFyfGXW9Wj0c2l4UORHFBHjId+S6INqAlxmzI1W47GFS/GP13h83uLi8vclgKjQcCSbxkNHX4AgKinRLcigNYXAvc2tyE1yZ7iiAWAzo84wcU/TlQVAlGrqf53swndPv4wGMwS7CEUxSKDLtvD6mgb88pxi+nLUFAfgkf6h14emzcYvbliJuGYg67pFcXqbGQ1mCN89/TJ+nezyIlIlgCC4j/c0XYk6wyzqvigAXAbun3VdLKlOoDUcLTnlIVCjrxzfD9uv4Cpm5++y81ha24gfL1yGpkG5OOXeI4UfFj23kitdZCUX+UD4yvH9Q9Zb7EOXzGgNR7GkOoHsJK4eq1gAEIC8dLG64QqfHxcvQTrxr/o6sbn7dMHRHD7aZONNvvLX+J8Z7bQB3QfB9fE6PLFoORKGgbyUwz4Ylxm1uoHN3afxq75OrxtGCTu59KnZ6oYrkJfupD0ZrlgA2MyoN0z8Qf3UkulP8M6/e+XFQt7PsI6ldDEtFMHG65YWlH+sdkXdL2y/Pl6HH85/Ayzpgou0AtJfZ8lWwP/+P6ifivpJTIMqEgDCpz/Xx+twdTjmObOl7GxEOJDpx9beDr+j8sUfLvt1xd+Zd3MhZ36sKYFBBJslltU24cGrF6LbGj5pzWVGXNOxtbcDBzL9JaVJCD9IcHU4huvjdci67qR0hkWlXpQlXdxYXV+IWhRt2n1l//f240g69rBKpBOh17aGZJhermxJnbxT7r+46lqsqGtCvzN8hEb3qdu/tx8fsv6iqKJvNW6srocl3Uk5JLoi1xwkui2I1o7IebZZYnPPKUQ0/aIKQQAGpMRVVZFLyjAtp98TKPUXZi4q6lxAMiOi6djccwo2j6wp1oJobSFhTgGgAsRhRsIw8fqa+pL4v+tHe3an+rAvnURYu3jcXyNCyrHxoStmo0Y3ivIXxiL65TLjDTUN+MP6qUg6F8/clADCmoZ96SR2p/pKqmIL7uvra+onbYPdigMAFQAQQpNZVZJzFzy+LT1nvMZQw0WZWGJqKIz3TLm6ItsnfnjabBQzv00DkHFdbOk5M+Q+FGtxmswqJIxQYeyrAsBldoDz0sXV4RgimlbowlbKYp5N9cAQ4qKKIIiQcVy8qbYRjWYIXEEPX/g1wq+vacDMyPAFLAzAEALPpnpKeqhUoFAarg7HkJeTzxGuSAokmdFkVvnJaMXv/sLP2jyUTcEkMWyKAIPxtsZpBSpRSVYw6EhxW2IKsq5zUevEzDBJ4FA2hQFfiUu6byA0mVWTsoNcxVKg+b4DXMqDBIDjAxmczGe9loAX+Q3bLxZf4ffiqTT6E6zn9xNThnVQgzz/k/ksjg9kRnTf5kdrFQWqJBCIEp9EsNt3Wnmkh9kxyadZ06uiSOjmiMorx4IGAcA1kWrU6cawDqpXMuqg08oPuR/F/x4m5WlwxQEg2M0WxxMlOcCB9Dt2UQCzmXFlVQSmEBXZNjBY95RQaQ5qMes/3+8sjicuajUVAMZYjBHUzwLA7nQfrGFyaQiAIyUWxuoqjv+f6weENQ2zI/FhHVTv8FBid7qvJAo00vutADBGHLhUKeUU1yQxDh6QV0vAo7D+ctxvBYBxDJzxYu6lUmQFgFI57WjulmMt2ggyYZWMcwCM9EEWe5xPROix8xWtNEFIuN9viMVlXL8CToUDoNT89OABLorVDhvNCMob92aSFfvw2QdpxnXwci6N0DAHe0H0bFGsdkRrUvUAFXRBlpTY5R/rl/pYqnVjeOXyT05fGch4ndZKcDLHDAC+Qr4ykEGvbRXtCBez/vP5DLtSPcNGzxQAxnD3kyVqJPk8udEMITZMEUywW54YyOJUPleRqcCBBduXSSJVRC9P10+dCFq3UIn+jTfxRlmAilB+nQj7Mn0lmfLgfa1VUUwLRYbdzQy/4dbPuk/5CsAV+WB+0nkSYpjHFFjNaaEIWquiI7pv+zJ9JYVbFQBG86KI0GENQIJLepCSGVXCOziyWF50F2QAIaHhia5XL2nCzGhtAoIInVYev0p2IqprFy/sIYLFErMjcVSJ0jJovbpiRoc1oEoiK8L0MyMkNLycSxfqVIvdlQLa8Lp4AvYwKcQuM6Kahh393TicTYH8Xj2VIAF9+0XPaZzK57zM1mGU2JYSr/PTR2SJQMu6rudoC23SZYRWLAXqsfPosAZKcoQDhV+VaEFU04atJdb9xrtfP3GwYvwAHkRp/vHkSwgJbdhcJRdAVNOwKtFSEv0JvrXDGkCPPzlGUaAKEN3n579NdpfEz4Nhc4vitZgfq0HOvXiht8OMGt3Aj9qP4UguXejYdrl3f0GExztPYkeyG3FNv+iOLgDkXBfzYzVYFK8tqbItWOtvk93o8SNNigJVgAS78V7fES5VgQwSuCMxFVm3uK4KadfFJw89VxJ9GK3Ij+bPQfvcy7sRK6Khl0dhHNyRmArD7ypRquzN9FVkSvikBYAXpvT4OQMXre09n0IAwDubW1FTRB590GHtJ10n8fCrh/0mVWMPg2CuLwH4xKHncDSXQXiYss7BVuydza1D1l+UxfR/d0d/N8wiGwcrAIyRIxzRNDyf6sXLubTnoJawIMmMa6PVWFHXhNQwxTHB79XpJj55+DnsSvXAIDHmHRIcljBI4NuvHsb3Tx9FQxFdGjQipFwHK+qacG20uqT+qdKPHr2cS+P5VG+h/loBoELE8KfBjyROH7zzE1fN9TqgFeV4ep3+3777aTyf6i307BwLsX3lf+TMUfzPl3ah3m/FXqzD/Imr5pYULBh8P3/WfQrdtqXqASoxGhTE6SVK6wwdOLNvrG3EHfVT0OcMf5IqwQgJgT5/gmQAglKH6JVOezyf5ZHTR/G+F59BVNOLa4VChD7Hxh31U/DG2saSm3oJf81PdL3qRZoABYBKEtenQTv7e3A8lyl5PGjwQD/VOg9GkeG94Gygz7Hx1j1Po623HYZfNFPuMUJBiaNGhG+cPIQPHHgGcU0vymIF6zOI8KnWeaXv/r6vcDyXwc7+HkQ0bdKOSaro3CfD79u5oeNEyTRocIe19065Gl1Wvigz7/gg6PctwZeO7S/srhJc0jyvC+34QfSp3RrAe/b/Fh89uBNRTS96GrxBhC4rj/dOuRpvqGkouZN1cB83dJxA7ySmPxUPAK8mVsej7cdhSVmIWhQrwenu52dch5mRGDJFNoB1/WzRiNDw2SO7seq5p9DW2w4BKsz5cv1RR/IigGCcHYkkB+34Nkv88MwxLNv1JH545qjXmKvItQkAGeliZiSGz8+4zvveEhQ4iKpZUuLR9uMID9M/VQHgcgIA3gnnnnQfNnWeKDldIaATTWYI35l7Mxwpvcl2Rf02Fz772/5uvPn5rbhzz9P47+5TSPk+heZPeQnyaYKxR4Uhehg0T4wIp/I5fP/0USzd9STes/+3OGPl0GCESnO2ieBIie/MvRlNPnBEiZsKEWFT5wnsSfchqmmTdkAeME4GZWsk8N1TR/DO5taSD2s0P5oT9N3/1KHnvDnBRcb6HT/NGAz8rPs0ftZ9GjPCMdxa14zbEy24NlqNKWbYy8M/5+J6bQvHBjLYl0niia5X8etkJ07nBxASAg3+eNJSlN8ggTP5HL4y+4YRt3IP3v3dU0egkcBkl4qfEwycPe18YtEKrKhrGtH0lkBZPnJwJ75x8hBaQlUlDcsOwAR402SyrjdWqFY3UWsYmBOpHnJNGdfB4WwavY6FtOtAAIhquteHCKWnXxtC4Ex+AB+eNntEk+IDaqcRYWtvB1bv3jps+3gFgAoCQNp1cF20BtsXr/KG1pU4uC6YjzvAEm9+fiue7utEkxGCNYJT34DaBMByWCIvh4ZLNXin2YZPfwL6MZKbbZJAh53HstpG/Nf1K1BFoqR5ycH62bc4S3dtwQuZJGIKAOOjAk4yo1rTsTPVg8c7T3oh0RHUDDMRwkLD4wuXYWltI05bAzBIlEyreJATLHwFrdEN1A56xXSjEH4N3ssjAJpBAqetASytbcTjC5chLDTwCKZWykFJdjtTPahWyj9+ABCY75hm4K9e3o2kY48ofTlIk6jRDTyxaDk+NG0Wzlg5kD/0eiTC5wCimOhQcdfqWbkzVg4fmjYLT/hjVEsdFxtcIwFIOjb+6uXdiGnGEH9AAWAcCAMIC4HDuTS+eGxfyWNBB9Mp6fPxb8y5EV+cdT0yroMBdguHXpdbDBIYYBcZ18EXZ12Pb8y5EVE/LXokVVtBivUXj+3D4VwaUU1D0rEnbQbouARAwLfrjRD+4cRBPN3XAX2kIMDZGP2nW+fhiUXL0WJWod0eKIQtL0+0y/MX2u0BtJhVeGLRcny6dV7BmozkYQWzjp/u7cDXTxxEo1GFHtvCHfVTIOBFyIQCwDgSZhhC4E/3/w6dVr7kFIlzHVmHGSvrmrF98Sp88IrZyLou+hxrTIEQKH6fYyHruvjgFbOxffEqrKxr9hR0hJPqA4vRaeXxpwd+h7Cmo8MewPuvmIUfL1yGr86+AVnX8YdmT07RIn+yZt240n8AIeE5hoeyKdzb3Orl0Y9QSQIqFdcNvLlhKt5Y04gOK48D2X4MSBemEH64sbzlgsGpsgSQch3YzLg9MQX/d84SfGTa7EJrl0tpdiv9qZH37/8Nnk31IOe6+Oi0a/AP1yyGzYwb4nWYHo5hY8cJmEIUnYekAHC5o0IAYpqOnaleRDUdS2ubCjwXIwRBQIlmhGN4Z0srbqlpQJedx/GBDHocq8DNgxBsqeyZfIUPyjZz0kXStRESArcmWvD1axbjs9PnY3o46k27HBQ+HWnQQCeBvz3+Ir558hBcBj4ybTb+/prFhfMAtwCC6KQFwbg4B7jgxRMh4zh4eO5N+OOW6WUZci2ZAUIhKrQ3ncR/tB/Dlp4z2J/pR8Z1YAiBEAmYQhRoEl1gFw6U0ZISeZawpURU0zEvWo1ViRb8UfN0LIjV+MD2ulNdanuS4D788MwxfPjADqRdBx+7cg7+zzWvK2wUdM57HznjpWMHGalSAWAcXDy8jgi2dLF18W1YHE+UbdL7uYriMmNnqgdtPe3YkerGoWwKp/I5pF0HgJdcdq6YwmPWMU3H1FAYsyNx3Bivx8pEM5bEEwXwBNanHD5HsP5nU734vWf/H/ocC39x5bX42nmUHwoE4xsAAX2xpERc0/HTRctxfbyubCAILILEa1up56SL47kMzlgDyLoOdqf7hiiwy4xFsVpENB0tZhVaw1GEhfYaxRNA2RpSBevenerF2/dsx7FcCh9vnYevzr7hgso/2UEw7gEQRFGyrls44Co3CAbv0kE4ciRKG4ApiECVM8YUrPf5VC/u3LMdx7L9+Pj0+UUp/2QGwYSIfgWVXEnHxlt2b8Mz/d1+OWP5sB3k8uu+czo41z/I6jz3de6psPA/r5VZ+W1fcZ/p78Y7XvCU/y9LVH74Vs5hxn0tM/Avc29CahKESCfM2hy/hDLlOrjt2afwyOmjMPxIx2iYuMG5/gEwzn2dWzNQbjlbU0x45PRR/P5zbTiaTeHj0+fj70pU/skKggm1LpfZi9sLwgcP7sCXju8fUsE10dYaWKUvH9+PP3tpJ3rtPD7eOrfknX8yg2DCrUkyQwMhInR89vBuvGPPdrRbA4XCmPEOA/atnebXFL9jz3Z8/sgLSDkO/qJ1Lr46+3WXpPyTDQQT0rJ5GZqMJjOEJ7pexdJdW/BUb7t3iOXvnjwO1xTs+joRnuptx9JdW/Dz7tNgMD525Rx8rUzKP5lAMKFTQBxmJAwTZ6wBrN69DZ88/By67Py4o0WD6U6XnccnDz+Ht+zehm47D5slPjJt9nkPuaBAMLwvNxHCoMOjnMBg9DoWZobj+PyMBbi3+SoYdLY8cbQc1UvZ8Qdfl80Sj7a/goeO7sWRXAoNRggdVh5/fuU1hfSG0VzDRA2RTgoADN7NctJFxnWxOJ7AF2YuLPTUL+y0g9IgLosPAwbz0BbnW3rO4HNH9mBXqgdRTUNU09FjW3j/FbPw9TFQ/okMgkkFACBISvMyMAWAm2sa8J4pV2NN01WF1IWAb4sxAoPXUgVDzgcsKbG+4xV87/TL+F2yCxJAXPOaeCQdB7cnWvCTRctgs4ROYwfZiQaCSQeAAi0iAhhIuTZcZlwXq8XdTVfizsYrcW20+jVUxAMPRpx2PcRBH+SEn7tzH8j04/HOE9jYcQIv+OkVcc1ruRI012IfyF+dfQPunzKj7KfekwkEkxYAgQRUI+M6GJAuanUTr4sn8OaGqbijfgqujVRfkKZwwapcXOHPguf8FuVAth+bu0/jv7pO4dlUD/ocC1XCozo4j7MeTJDPSgf/Mvdm3NeiQKAAUAZHWZD3YDOuA4slErqJhbFaLKmux4JoDW6qqUeLGUZNicOoB0vSsXHGyuGZZDf2ZpLY2d+NPek+9DgWTBKIajp0Ikj206MveL0oFNP8y9ybFAgUAMpLjwS8HJucDwYASOgh1BkmZoZjaDRDmBetgU6ExfH6woC5sxTFU5BdqW44zNifSaLTyuNILo1e20KPkwfgtVQJazoMvzqs1NaPCgSXGBhR6n4ep3RQ1mZMNwoxb5sZZ6wcjg9kIP2EN8LZvP/zieU3zAqS6EJCQCeBBiPk0ykUvqt059kDQVzT8b4XnwGAMQfB4HMCAOMOBAoARYIh2HFNEqjStSHcf7gpjoN9gWCHL9f0GQUCBYAxk8EljqUo6KiDVIHgEnw/JRPDUp0DgkfOHB3TOWfngmC8pE0oACgQTGoQKAAoEExqECgAKBBMahAoACgQTGoQKAAoEExqECgAKBBMahAoACgQTGoQKAAoEExqECgAKBBMahAoACgQTGoQKAAoEExqECgAKBBMahAoACgQTGoQqHRoBYKKTaUeySxoZQGUTAhLkHEdjMUUYwUAJRUFApsl7muZgb+/ZjF6nPyoj6oVIFJPX0kFgUDAYYkPXDELb2uYhqRjjx4IiCAg2VWPXkmlgIBwtnfSV2Zdj7DQRq+JsWRXMHg3hcxg7UqUXHYQCCJIZsyMxLGyrhkp1ym3FZAUMsHg3QIg5QcoqTgQBG1p7m1uhSNHa28mIQh8GF5fG9UgS0nFgCDYledFqxHXjXLTIIYQIPBhwaAXIJQRUFJZICCf8rRWRdFgmIUmZOVDmACDXhBEvBu2AzArFCipOEsgR4OaMAvYDoh4t5BSHGHbzkMIFQ9VUnEgEBiF4zAhiG07L6U4InrjrQfhyiMwVSRISeWAgP3vPD6QQZdtFZoPl2UZpgm48khvvPWgwJIlNjTxG2EaAFgBQElFgCBQxP2ZfqTKehjGUpgGoInfYMkS2+f9vA3exBRFg5RUBAiEz/0fbT8OvZxBGgZ52Q+8LfgdCFducdOZNDRNK9geJUouEwiC6ZhHsim09bYjrunlCYMyMzRNc9OZtHDlFg8AvF7rXLnmDBznaQpXMYgUDVJy2UDAODsZ51OHn0dOuuWjP0SSwlUMx3m6c+WaM+D1msDWRgIADdgIXSMoA6CkDCCwR+hOOtKbevntVw/jJ10nUVPOQzBmQNdIAzYCALY2EoGZIATHtj3aGCJ9L4ga4ThnTyKUKCmSsxfGNV17E+6bMqMw4V4UoUrSn5ypEeEHp4/iAweeQUwzwCib8jN0HWDuzLOzIL383k5ISQJEjKee0tPL1nTCcX5IsQiBoDJElYzYEnzgwDP45slD0PyxUBIMl7mg5MFLsv/v8Di/RoRvnjyEDx54BhFNR1mPwAguxSIEx/lhetmaTjz1lA4iJh8dAgAntj1+LZniOTiuAWYCVFRISal65kmvY+FtDdPw1zMXYn60ZtjP7csk8VdH9uAnXSdRp5sFf6B8sR9i6JrNlryhZ/mdBwAQiORZBV+/XsOaNW5924bvU03sfu5PuyDS1CNVMhLRiJB0bESEhmV1Tbi76SrMi1bj6nCs8J6Xc2nsz/RjY8creLq3A1nplpfzn6U/LlXHNE6mf9C98p53B7qOITu8bwXqn9pwDSLmXtiuUFZAyaWCwGVG2nXgMiOq6ag3zMLfu20LGT/XP6bphfeXWbzd39AkstaC7lvveSnY/QPfpRAiwoYNovv31hzkAevbFI8KsDoZVjJyCZS5RjeQMEwYROi2rcLLIELCMAuDx0el8otZUjwqeMD6dvfvrTmIDRvE4FA/nfNmwrp1VHPjNTV6bXg/SDTBcYYCRYmSMvgIZeb4F/bNdR1g2eH05eYld7yUxLp1nkXwZWhfICIGs0gS9Sae2vBpkYh9j/uSDkhVjSkpFx8Zyx9jSdGILnuSn06uflcvmLVzD3pfq9hELtav13pW7n2E+/u3UDyqg1XhvJLxhjR2KR7Vub9/S8/KvY9g/XoNRK/R4/Pv7Pv2MehBqVnWfZwbaIdpKH9AyXhSfgnTEJwbaNcs6z7QgxL79vFwlGyo+KGixJPrV4l4+BeczztgaFBRISWVzrIILoVCukzlbu+5bc2WwWHP4iwAAKxZ46KtTe+5bc0WzmYfFIk6HQxH3V8lFa7+jkjU6ZzNPthz25otaGvTL6T8KGo39xwHt37bxocpHn2A+1MOSKimukoqUPmlQ9VxnVOZf+5efvf7A9292EeKAYB3GEYk65/etJFqqu/i3j4LRKa640oqiPdbVFdrcrJ/U/eyu+4ODnYHhzxLo0AFiBBj3TqAWTj9Aw/ITHqHqKsxwVLRISUVs/OLuhpTZtI7nP6BB8AssG4dhlN+ACgu12fbNgZA+Q/8ec68860byaAZFI1ch7xtg0ancF+JkqIYP8Oh6pjBAwPr3Z7sHyVXv6sXAOHBB4uKWpamuGvXiuCL67dveljU1jwge/pcMJM6LFMyxpRHgohFolaTfcl/7l561/vP1dFipLRsz23bGGvXCmzdSrnWef8ZedfbQaZxKwlBcF1XgUDJGCm/S6ahkaEL5HLrupfe9Qmf81Mpyl+6BRj8OW/Xl3VPbbxDhPR/pSpzCqcz3lmBqiZTMjqK78X4Y1GdB6zTMu/8Se+td28Gs/D5fsmZFiPdsb3i+bY2vffWuzejM7uEc9Zmqq7WYejkp06o4mIlZeT67MLQiaqrdc5Zm9GZXdJ7692b0dam+/k9I9K3S9+peb0G8g4aEtsfey8EPSTC4amcSgPMAS1SFkHJSBVfgkijeAwylzsFyZ/vWfqO756reyOV8igm+6WVRNy8+QdNTqz6cxD0AQqZJqcyAFhRIyUlUx2AdIpHwXnLguRv6+n+L7TfcX/HYH271J8qr0K2telYudIBgLq2TQtESHwcTO+iSNjkTBZwHNfrQMdCgUHJa5WepNe6RNcoGgFncxaI/03m5dd6V96191wdK4fQKCyEsGGDCPIv6n61aYEm9Hez695H0UgzXAnODcCPGjHONgBWgJhs9KbQB4sJmqZRuArQBDiTbSdNe8SVzvd73+gr/vr1Gu65R5Zj1x9dAASydq3A/PkUAKHpNz9pZtAfuuy+HS6vFNFIHABg2WDLAqQc3JWOLtFJV1JZIgcpvccAhCAyTcD0yiFlJpuCRm0aaT8m8H933PK29oLi79vHpYY3Lz8ABgNhxQox2Gwl2jZNgyFuI43eBFfeBGA26XoVNM3r3uXPhOK8pVRnAog/hBEQAiACXBfsOAMADkETz7DLv4Qtn+xZedfJIXR661Y5Woo/dgAYTI22btXQ2clD0lOZtbodT8zVBLVyOvd6EM1hQ58Oy9aIaBGINNWucbxqPgHMLjPvhmm4ZDvHwHyQYuHfupKP9964+sUh2Zrr12tobCSsWOGWm+pcSP4/xXQfGf2UdrsAAAAASUVORK5CYII=",
          "/icon-512.png": "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"}
MANIFEST = json.dumps({"name": "WallaBot", "short_name": "WallaBot", "start_url": "/?tab=encontrados", "display": "standalone",
                       "background_color": "#13C1AC", "theme_color": "#13C1AC",
                       "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                                 {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]})

def crear_panel(d):
    class Panel(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            data = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.startswith("/api/feed"):
                with LOCK:
                    self._json({"items": list(d.get("feed", []))})
                return
            if self.path.startswith("/api/estado"):
                with LOCK:
                    self._json({"owner": bool(d["owner"]), "lat": d["lat"], "lon": d["lon"],
                                "intervalo": d["intervalo"], "pausa": d["pausa"], "max_edad": d.get("max_edad", 0), "notif_movil": d.get("notif_movil", True),
                                "termux_api": bool(shutil.which("termux-notification")),
                                "silenciados": len(d["silenciados"]),
                                "bloq": list(d.get("bloq", [])),
                                "lsil": [{"id": v, "nombre": nombre_vendedor(d, v)} for v in d["silenciados"]],
                                "paises": [{"dom": x[0], "flag": x[1], "pais": x[2]} for x in VINTED_PAISES],
                                "busquedas": [dict({k: b.get(k) for k in ("id", "texto", "min", "max", "km", "zona", "lat", "lon", "excluir", "pausada", "fuentes", "exactas", "prioridad", "solo_chollos")},
                                                   donde=donde_txt(b))
                                              for b in d["busquedas"]]})
                return
            ruta = self.path.split("?")[0]
            if ruta in ICONOS or ruta == "/favicon.ico":
                data = base64.b64decode(ICONOS.get(ruta, ICONOS["/icon-192.png"]))
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if ruta == "/manifest.json":
                data = MANIFEST.encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/manifest+json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            data = PANEL_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            try:
                self._post()
            except Exception as e:
                print("Error panel:", e)
                try:
                    self._json({"msg": f"⚠️ Error: {e}"}, 500)
                except Exception:
                    pass

        def _post(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                body = {}
            ruta = self.path.split("?")[0]

            def alerta():
                with LOCK:
                    return next((b for b in d["busquedas"] if b.get("id") == body.get("id")), None)

            if ruta in ("/api/crear", "/api/editar"):
                texto = str(body.get("texto") or "").strip()
                if not texto:
                    return self._json({"msg": "Escribe qué buscas"})
                def num(v):
                    try:
                        return None if v is None else float(v)
                    except (TypeError, ValueError):
                        return None
                # Siempre en todas las plataformas y países; solo precio máximo y palabras excluidas
                b = {"texto": texto, "min": num(body.get("min")), "max": num(body.get("max")), "km": None,
                     "excluir": [str(x) for x in body.get("excluir") or []],
                     "exactas": bool(body.get("exactas")),
                     "prioridad": bool(body.get("prioridad")),
                     "solo_chollos": bool(body.get("solo_chollos")),
                     "fuentes": json.loads(json.dumps(FUENTES_DEFECTO))}
                if ruta == "/api/editar":
                    vieja = alerta()
                    if not vieja:
                        return self._json({"msg": "Esa alerta ya no existe"})
                    with LOCK:
                        for k in ("lat", "lon", "zona"):
                            vieja.pop(k, None)
                        vieja.update(b)          # conserva id, pausa y lo ya visto
                        vieja["inicial"] = True  # reaprende lo que ya existe con los filtros nuevos
                    guardar(d); sembrar(d, vieja)
                    if d["owner"]:
                        enviar(d["owner"], f"✏️ Alerta editada: {describir(vieja)}")
                    return self._json({"msg": "✅ Cambios guardados", "ok": True})
                with LOCK:
                    b["id"] = d["next_id"]; d["next_id"] += 1
                    b["vistos"], b["inicial"] = [], True
                    d["busquedas"].append(b)
                guardar(d); sembrar(d, b)
                if d["owner"]:
                    enviar(d["owner"], f"✅ Alerta creada desde el panel: {describir(b)}")
                return self._json({"msg": "✅ Alerta creada", "ok": True})

            if ruta == "/api/feed_borrar":
                with LOCK:
                    if body.get("alerta_id") is None:
                        d["feed"] = []
                    else:
                        d["feed"] = [x for x in d.get("feed", []) if x.get("alerta_id") != body["alerta_id"]]
                guardar(d)
                return self._json({"msg": "Historial borrado", "ok": True})

            if ruta == "/api/geo":
                q = str(body.get("q") or "").strip()
                try:
                    r = requests.get("https://nominatim.openstreetmap.org/search",
                                     params={"q": q, "format": "json", "limit": 1, "countrycodes": "es"},
                                     headers={"User-Agent": "WallaBot-personal/1.0"}, timeout=15)
                    res = r.json()
                except Exception:
                    res = []
                if not res:
                    return self._json({"lat": None})
                nombre = ", ".join(res[0].get("display_name", q).split(", ")[:3])
                return self._json({"lat": float(res[0]["lat"]), "lon": float(res[0]["lon"]), "nombre": nombre})

            if ruta == "/api/toggle":
                b = alerta()
                if not b:
                    return self._json({"msg": "No existe"})
                b["pausada"] = not b.get("pausada")
                guardar(d)
                return self._json({"msg": "⏸ Pausada" if b["pausada"] else "▶️ Activada"})

            if ruta == "/api/borrar":
                b = alerta()
                with LOCK:
                    if b in d["busquedas"]:
                        d["busquedas"].remove(b)
                guardar(d)
                return self._json({"msg": "🗑 Borrada"})

            if ruta == "/api/probar":
                b = alerta()
                if not b or not d["owner"]:
                    return self._json({"msg": "Escribe /start al bot primero" if b else "No existe"})
                res = buscar(b, d)
                if res is None:
                    return self._json({"msg": "⚠️ Wallapop no respondió"})
                for it in res[:3]:
                    enviar_anuncio(d["owner"], it, b, titulo="🧪 Prueba")
                return self._json({"msg": f"Enviados {min(3, len(res))} a Telegram" if res else "Sin resultados con esos filtros"})

            if ruta == "/api/ajustes":
                with LOCK:
                    if "intervalo" in body:
                        d["intervalo"] = max(15, int(body["intervalo"]))
                    if "max_edad" in body:
                        d["max_edad"] = max(0, float(body["max_edad"]))
                    if "notif_movil" in body:
                        d["notif_movil"] = bool(body["notif_movil"])
                    if "pausa" in body:
                        d["pausa"] = bool(body["pausa"])
                    if "lat" in body and "lon" in body:
                        d["lat"], d["lon"] = float(body["lat"]), float(body["lon"])
                guardar(d)
                return self._json({"msg": "Guardado ✓"})

            if ruta in ("/api/bloquear", "/api/desbloquear"):
                f = str(body.get("f") or "").strip()
                with LOCK:
                    d["bloq"] = [x for x in d.get("bloq", []) if _norm(x) != _norm(f)]
                    if ruta == "/api/bloquear" and f:
                        d["bloq"].append(f)
                guardar(d)
                return self._json({"msg": f"🚫 Bloqueado «{f}»" if ruta == "/api/bloquear" else f"✅ «{f}» desbloqueado", "ok": True})

            if ruta == "/api/desilenciar":
                with LOCK:
                    if body.get("id") in d["silenciados"]:
                        d["silenciados"].remove(body["id"])
                    d.get("silenciados_nombres", {}).pop(body.get("id"), None)
                guardar(d)
                return self._json({"msg": "🔊 Silencio quitado", "ok": True})

            if ruta == "/api/solonuevos":
                solo_nuevos(d)
                return self._json({"msg": "🧹 Hecho: solo te llegará lo nuevo desde ahora", "ok": True})

            if ruta == "/api/limpiar":
                with LOCK:
                    d["silenciados"] = []
                    d["silenciados_nombres"] = {}
                guardar(d)
                return self._json({"msg": "Silenciados vaciados"})

            self._json({"msg": "?"}, 404)

    srv = ThreadingHTTPServer(("127.0.0.1", PUERTO), Panel)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

# ---------------- Bucle principal ----------------
# ---------------- Notificaciones de Android (Termux:API) ----------------
import subprocess
NOTIF_N = [0]

def notificar_movil(d, it, b):
    """Notificación nativa del móvil; al tocarla abre el anuncio. Requiere la app Termux:API."""
    if not d.get("notif_movil", True) or not shutil.which("termux-notification"):
        return
    def tarea():
        try:
            NOTIF_N[0] = (NOTIF_N[0] + 1) % 50
            url = str(it.get("url") or "").replace("'", "%27")
            args = ["termux-notification", "--id", f"wallabot{NOTIF_N[0]}", "--group", "wallabot",
                    "--priority", "high", "--sound", "--vibrate", "200,100,200",
                    "--icon", "manage_search",
                    "--title", f"WallaBot · {it.get('titulo', '')}"[:80],
                    "--content", f"💰 {it.get('precio', '')} · {it.get('origen', '')} · 🔔 {b.get('texto', '')}",
                    "--action", f"termux-open-url '{url}'",
                    "--button1", "Ver anuncio", "--button1-action", f"termux-open-url '{url}'",
                    "--button2", "Encontrados", "--button2-action", f"termux-open-url 'http://localhost:{PUERTO}/?tab=encontrados'"]
            if it.get("foto"):
                ruta = os.path.join(DATOS_DIR, f"foto{NOTIF_N[0]}.jpg")
                try:
                    r = requests.get(it["foto"], timeout=8)
                    if r.ok:
                        open(ruta, "wb").write(r.content)
                        args += ["--image-path", ruta]
                except Exception:
                    pass
            subprocess.run(args, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print("Notificación móvil:", e)
    threading.Thread(target=tarea, daemon=True).start()

MAX_TANDA = 15   # máximo de avisos seguidos por alerta en una revisión
import queue
COLA = queue.Queue()

def remitente(d):
    """Envía los avisos en cuanto se detectan, sin esperar a que acabe la búsqueda."""
    while True:
        it, b, t = COLA.get()
        try:
            if t < d.get("corte_ts", 0) or d.get("pausa") or b.get("pausada") or b not in d["busquedas"]:
                continue
            actualizar_bloqueos(d)
            if bloqueado(it, set(d["silenciados"])):
                continue
            enviar_anuncio(d["owner"], it, b)
            notificar_movil(d, it, b)
            time.sleep(0.25)
        except Exception as e:
            print("Error enviando:", e)

def revisar_alerta(d, b, solo):
    if b.get("pausada") or b.get("inicial"):
        return
    res = buscar(b, d, solo)
    if res is None or b.get("inicial"):
        return
    with LOCK:
        ya = set(b.get("vistos", [])) | set(d.setdefault("enviados", []))
        nuevos = [it for it in res if it["id"] not in ya]
        # Recuerda TODO lo que aparece y lo que se va a enviar: nunca se repite
        b["vistos"] = list(dict.fromkeys([it["id"] for it in res] + b.get("vistos", [])))[:MAX_VISTOS]
        d["enviados"] = list(dict.fromkeys([it["id"] for it in nuevos] + d["enviados"]))[:MAX_ENVIADOS]
    if float(d.get("max_edad", 0)) > 0:
        limite = max(float(d["max_edad"]), d["intervalo"] / 60 + 1)
        nuevos = [it for it in nuevos if (e := edad_min(it)) is None or e <= limite]
    if not nuevos:
        return
    for it in reversed(nuevos):
        add_feed(d, it, b)
    if len(nuevos) > MAX_TANDA:
        enviar(d["owner"], f"📦 <b>{len(nuevos)} anuncios nuevos</b> para «{html.escape(b['texto'])}». "
                           f"Te mando los {MAX_TANDA} más recientes; el resto está en la web, en 📰 Encontrados.")
    ahora = time.time()
    for it in reversed(nuevos[:MAX_TANDA]):       # del más antiguo al más nuevo
        COLA.put((it, b, ahora))

PRIORIDAD_CADA = 8   # segundos entre revisiones de las alertas ⚡ prioritarias (Wallapop)

def revisar(d, solo=None, hilos=4, solo_prioritarias=False):
    with LOCK:
        lista = [b for b in d["busquedas"] if not b.get("pausada") and not b.get("inicial")
                 and (b.get("prioridad") or not solo_prioritarias)]
    if not lista:
        return
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        list(ex.map(lambda b: revisar_alerta(d, b, solo), lista))
    guardar(d)

def bucle(d, solo, cada, hilos, solo_prioritarias=False):
    """Un ritmo de revisión: ⚡ prioritarias muy rápido, Wallapop rápido, Vinted más tranquilo."""
    while True:
        t0 = time.time()
        try:
            if d.get("owner") and not d.get("pausa"):
                revisar(d, solo, hilos, solo_prioritarias)
        except Exception as e:
            print(f"Error revisando {solo}:", e)
        time.sleep(max(3, cada() - (time.time() - t0)))

# ---------------- Paquetes de alertas preparados (se crean una sola vez) ----------------
_SIN_ROTAS = ["roto", "rota", "defectuosa", "defectuoso", "defecto", "averiada", "averiado", "no funciona",
              "no enciende", "piezas", "despiece", "reparar", "bisagra", "pantalla rota", "juego", "juegos",
              "funda", "carcasa", "cargador", "protector", "cartucho", "caja vacia", "solo caja"]
PAQUETES = [
    ("3dsxl-2026-10-21", "Nintendo 3DS XL (menos de 100 €, sin rotas)", [
        {"texto": "3ds xl", "exactas": True},
        {"texto": "3dsxl", "exactas": True},
        {"texto": "3 ds xl", "exactas": True},
        {"texto": "3ds ll", "exactas": True},
        {"texto": "nintendo 3ds grande", "exactas": False},
    ]),
]

def aplicar_paquetes(d):
    hechos = d.setdefault("paquetes", [])
    for clave, nombre, alertas in PAQUETES:
        if clave in hechos:
            continue
        creadas = []
        with LOCK:
            existentes = {_norm(b["texto"]): b for b in d["busquedas"]}
            for a in alertas:
                if _norm(a["texto"]) in existentes:      # ya la tenías: solo la hago prioritaria
                    existentes[_norm(a["texto"])]["prioridad"] = True
                    continue
                b = {"texto": a["texto"], "min": 40.0, "max": 100.0, "km": None, "excluir": list(_SIN_ROTAS),
                     "exactas": a["exactas"], "prioridad": True, "solo_chollos": False,
                     "fuentes": json.loads(json.dumps(FUENTES_DEFECTO)), "id": d["next_id"],
                     "vistos": [], "inicial": True}
                d["next_id"] += 1
                d["busquedas"].append(b)
                creadas.append(b)
            hechos.append(clave)
        guardar(d)
        for b in creadas:
            sembrar(d, b)
        if d.get("owner") and creadas:
            enviar(d["owner"], f"📦 <b>Alertas creadas: {html.escape(nombre)}</b>\n"
                   + "\n".join("• " + describir(b) for b in creadas)
                   + "\n\nPuedes editarlas o borrarlas en la web o con ✏️ Editar alerta.")

# ---------------- Actualización automática desde GitHub ----------------
def _version_de(src):
    m = re.search(r'^VERSION = "([^"]+)"', src, re.M)
    return m.group(1) if m else None

def descargar_ultima():
    urls = [f"https://api.github.com/repos/{REPO}/contents/wallabot.py?ref=main",
            f"https://raw.githubusercontent.com/{REPO}/main/wallabot.py?t={int(time.time())}"]
    for i, url in enumerate(urls):
        try:
            cab = {"Accept": "application/vnd.github.raw", "Cache-Control": "no-cache"} if i == 0 else {"Cache-Control": "no-cache"}
            r = requests.get(url, headers=cab, timeout=20)
            if r.status_code == 200 and "def main():" in r.text:
                return r.text
        except Exception:
            pass
    return None

def actualizar(d, avisar_si_igual=False):
    """Descarga la última versión; si es distinta y válida, la instala y reinicia el bot."""
    src = descargar_ultima()
    if not src:
        if avisar_si_igual and d.get("owner"):
            enviar(d["owner"], "⚠️ No pude conectar con GitHub. Lo intento más tarde.")
        return False
    nueva = _version_de(src)
    if not nueva or nueva == VERSION:
        if avisar_si_igual and d.get("owner"):
            enviar(d["owner"], f"✅ Ya tienes la última versión ({VERSION}).")
        return False
    try:
        compile(src, "wallabot.py", "exec")          # nunca instala un archivo roto
    except SyntaxError as e:
        print("Versión nueva con error, no se instala:", e)
        return False
    destino = os.path.abspath(__file__)
    tmp = destino + ".nuevo"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(src)
    os.replace(tmp, destino)
    guardar(d)
    if d.get("owner"):
        enviar(d["owner"], f"🔄 WallaBot actualizado a la versión <b>{nueva}</b>. Reiniciando…")
    print("Actualizado a", nueva, "- reiniciando")
    os.execv(sys.executable, [sys.executable, destino])

def vigilar_actualizaciones(d):
    time.sleep(60)
    while True:
        try:
            actualizar(d)
        except Exception as e:
            print("Actualizador:", e)
        time.sleep(600)          # cada 10 minutos

def main():
    if "PEGA_AQUI" in TOKEN:
        print("Falta el token. Ejecuta:  TOKEN=xxxx python wallabot.py"); return
    d = cargar()
    tg("setMyCommands", commands=[
        {"command": "nueva", "description": "Crear alerta"},
        {"command": "actualizar", "description": "Buscar actualización ahora"},
        {"command": "buscar", "description": "Buscar ahora con Chollómetro"},
        {"command": "lista", "description": "Ver alertas"},
        {"command": "pausar", "description": "Pausar una alerta"},
        {"command": "activar", "description": "Activar una alerta"},
        {"command": "borrar", "description": "Borrar alerta"},
        {"command": "probar", "description": "Ver últimos resultados"},
        {"command": "solonuevos", "description": "Cortar avalancha: solo lo nuevo desde ahora"},
        {"command": "silenciados", "description": "Ver y quitar vendedores silenciados"},
        {"command": "bloquear", "description": "Bloquear una cadena entera (ej. cash converters)"},
        {"command": "intervalo", "description": "Cada cuántos segundos revisar"},
        {"command": "ubicacion", "description": "Fijar zona"},
    ])
    for b in list(d["busquedas"]):
        if b.get("inicial"):
            sembrar(d, b)
    if d.get("owner"):
        aplicar_paquetes(d)
    try:
        crear_panel(d)
        print(f"Panel: abre http://localhost:{PUERTO} en Chrome del móvil")
    except OSError:
        print(f"⚠️ El puerto {PUERTO} está ocupado: ¿hay otro WallaBot abierto? Ciérralo con: pkill -f wallabot")
    print("WallaBot en marcha. Escríbele /start en Telegram.")
    # Aviso de encendido: si se acaba de actualizar, lo confirma; si estuvo apagado, dice cuánto tiempo
    if d.get("owner") and d.get("version") and d.get("version") != VERSION:
        enviar(d["owner"], f"✅ <b>Listo.</b> WallaBot actualizado a la versión <b>{VERSION}</b> y funcionando.")
    d["version"] = VERSION
    if d.get("owner"):
        lat = d.get("latido")
        if lat and time.time() - lat > 300:
            horas = (time.time() - lat) / 3600
            dur = f"{horas:.1f} h" if horas >= 1 else f"{int(horas * 60)} min"
            enviar(d["owner"], f"⚠️ <b>WallaBot estuvo apagado</b> desde las {time.strftime('%H:%M', time.localtime(lat))} "
                               f"({dur}). Ya está encendido otra vez y revisa lo que se publicó mientras tanto.")
        elif not lat:
            enviar(d["owner"], "🟢 WallaBot encendido.")
    def atender_telegram():
        while True:
            try:
                r = tg("getUpdates", offset=d["offset"], timeout=25)
                for u in r.get("result", []):
                    d["offset"] = u["update_id"] + 1
                    try:
                        if "message" in u:
                            manejar(d, u["message"])
                        elif "callback_query" in u:
                            manejar_boton(d, u["callback_query"])
                    except Exception as e:
                        print("Error:", e)
                    guardar(d)
                if not r.get("ok", True) or not r:
                    time.sleep(3)
            except Exception as e:
                print("Error Telegram:", e)
                time.sleep(5)
    threading.Thread(target=atender_telegram, daemon=True).start()
    threading.Thread(target=vigilar_actualizaciones, args=(d,), daemon=True).start()

    threading.Thread(target=remitente, args=(d,), daemon=True).start()
    threading.Thread(target=bucle, args=(d, "walla", lambda: d["intervalo"], 6), daemon=True).start()
    threading.Thread(target=bucle, args=(d, "walla", lambda: PRIORIDAD_CADA, 3, True), daemon=True).start()
    threading.Thread(target=bucle, args=(d, "vinted", lambda: max(60, d["intervalo"]), 2), daemon=True).start()
    while True:
        try:
            time.sleep(15)
            d["latido"] = time.time()
            guardar(d)
        except Exception as e:          # nunca se cae por un error puntual
            print("Error general:", e)
            time.sleep(5)

if __name__ == "__main__":
    main()
