"""
Configuración central del scraper de remesas.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Monto fijo a cotizar por el CRON Automático ---
# Este monto es el fallback que usan los scrapers cuando corren de forma programada a ciertas horas.
# El scrapeo manual ingresado desde la interfaz web ignora esto y usa el monto digitado por el usuario.
CRON_DEFAULT_AMOUNT_CLP = 100_000

# --- Países destino ---
DESTINATIONS = [
    {"country_code": "PE", "country_name": "Perú",      "local_currency": "PEN"},
    {"country_code": "CO", "country_name": "Colombia",   "local_currency": "COP"},
    {"country_code": "AR", "country_name": "Argentina",  "local_currency": "ARS"},
    {"country_code": "BO", "country_name": "Bolivia",    "local_currency": "BOB"},
    {"country_code": "HT", "country_name": "Haití",      "local_currency": "HTG"},
    {"country_code": "VE", "country_name": "Venezuela",  "local_currency": "VES"},
    {"country_code": "BR", "country_name": "Brasil",     "local_currency": "BRL"},
    {"country_code": "EC", "country_name": "Ecuador",    "local_currency": "USD"},
    {"country_code": "ES", "country_name": "España",     "local_currency": "EUR"},
    {"country_code": "US", "country_name": "EE.UU.",     "local_currency": "USD"},
]

# --- Map código país → nombre ---
COUNTRY_NAMES = {d["country_code"]: d["country_name"] for d in DESTINATIONS}

# --- Normalización de nombres entre proveedores ---
# Los proveedores a veces usan nombres distintos para el mismo país/moneda.
# Estas tablas normalizan al nombre estándar en español.
COUNTRY_NAME_NORMALIZE = {
    # Variaciones comunes
    "Peru": "Perú",
    "PERU": "Perú",
    "Perú": "Perú",
    "Colombia": "Colombia",
    "COLOMBIA": "Colombia",
    "Argentina": "Argentina",
    "ARGENTINA": "Argentina",
    "Bolivia": "Bolivia",
    "BOLIVIA": "Bolivia",
    "Haiti": "Haití",
    "HAITI": "Haití",
    "Haití": "Haití",
    "Venezuela": "Venezuela",
    "VENEZUELA": "Venezuela",
    "Brazil": "Brasil",
    "Brasil": "Brasil",
    "BRAZIL": "Brasil",
    "BRASIL": "Brasil",
    "EE.UU.": "EE.UU.",
    "Estados Unidos": "EE.UU.",
    "USA": "EE.UU.",
    "Ecuador": "Ecuador",
    "ECUADOR": "Ecuador",
    "España": "España",
    "Spain": "España",
    "ESPAÑA": "España",
}

CURRENCY_NAME_NORMALIZE = {
    "PEN": "PEN", "SOL": "PEN", "Soles": "PEN",
    "COP": "COP", "Peso colombiano": "COP",
    "ARS": "ARS", "Peso argentino": "ARS",
    "BOB": "BOB", "Boliviano": "BOB",
    "HTG": "HTG", "Gourde": "HTG",
    "VES": "VES", "Bolívar": "VES", "VEF": "VES",
    "BRL": "BRL", "Real": "BRL",
    "USD": "USD", "Dólar": "USD", "Dollar": "USD",
    "EUR": "EUR", "Euro": "EUR",
    "CLP": "CLP", "Peso chileno": "CLP",
}


def normalize_country(name: str, code: str = "") -> str:
    """Normaliza nombre de país. Si tiene código, usa el mapa canónico."""
    if code and code.upper() in COUNTRY_NAMES:
        return COUNTRY_NAMES[code.upper()]
    return COUNTRY_NAME_NORMALIZE.get(name, name)


def normalize_currency(code: str) -> str:
    """Normaliza código de moneda."""
    return CURRENCY_NAME_NORMALIZE.get(code.upper(), code.upper()) if code else code

# --- Credenciales ---
RIA_EMAIL = os.getenv("RIA_EMAIL", "")
RIA_PASSWORD = os.getenv("RIA_PASSWORD", "")
WU_EMAIL = os.getenv("WU_EMAIL", "")
WU_PASSWORD = os.getenv("WU_PASSWORD", "")
AFEX_USERNAME = os.getenv("AFEX_USERNAME", "")
AFEX_PASSWORD = os.getenv("AFEX_PASSWORD", "")

# --- Rutas ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
BROWSER_PROFILES_DIR = os.path.join(BASE_DIR, "browser_profiles")

# Crear directorios si no existen
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BROWSER_PROFILES_DIR, exist_ok=True)

# --- Timeouts y reintentos ---
REQUEST_TIMEOUT = 30  # segundos
MAX_RETRIES = 3
RETRY_DELAY = 5  # segundos entre reintentos


# --- Normalización de métodos de recaudación y dispersión ---
# Mapea los valores crudos de cada proveedor a categorías universales.

def normalize_metodo_recaudacion(raw: str) -> str:
    """Normaliza método de recaudación a categoría universal."""
    if not raw or raw == "N/D":
        return "N/D"
    r = raw.strip().lower()

    # --- Efectivo (Pago en Persona / Sucursal) ---
    # --- Efectivo (Pago en Persona / Sucursal) ---
    if (
        r in ("ca",)
        or "presencial" in r
        or "cash" in r
        or "efectivo" in r
        or "sucursal" in r
        or "tienda" in r
        or "agente" in r
        or "ventanilla" in r
        or "pago en punto" in r
        or "paga en persona" in r
        or "pago en persona" in r
    ):
        return "Efectivo"

    # --- Tarjeta de Débito / Webpay ---
    if (
        r in ("dc", "webpay")
        or "tarjeta de débito" in r
        or "tarjeta débito" in r
        or "debit card" in r
        or "débito" in r
        or "debito" in r
        or "redcompra" in r
        or ("visa" in r and ("debito" in r or "débito" in r))
        or ("mastercard" in r and ("debito" in r or "débito" in r))
    ):
        return "Tarjeta de Débito"

    # --- Tarjeta de Crédito ---
    if (
        r in ("cc",)
        or "tarjeta de crédito" in r
        or "credit card" in r
        or "crédito" in r
        or "credito" in r
        or ("visa" in r and "debito" not in r and "débito" not in r)
        or ("mastercard" in r and "debito" not in r and "débito" not in r)
    ):
        return "Tarjeta de Crédito"

    # --- Pago Online (Portales) ---
    if (
        "sencillito" in r
        or "servipag" in r
        or "multicaja" in r
    ):
        return "Pago Online"

    # --- Transferencia bancaria ---
    # Códigos cortos + descripciones típicas en ES/EN.
    if (
        r in ("bb", "transferencia bancaria", "banco directo", "khipu")
        or "transfer" in r
        or "bank" in r
        or "banco" in r
        or "cuenta bancaria" in r
        or "account" in r
        or "cta" in r
        or "deposito en cuenta" in r
        or "depósito en cuenta" in r
    ):
        return "Transferencia Bancaria"

    return raw  # fallback: valor original


def normalize_metodo_dispersion(raw: str) -> str:
    """Normaliza método de dispersión a categoría universal."""
    if not raw or raw == "N/D":
        return "N/D"
    r = raw.strip().lower()

    # --- Billetera digital (wallet / mobile) ---
    if (
        r.startswith("wallet")
        or r.startswith("800")
        or "mobile" in r
        or "billetera" in r
        or "moncash" in r
        or "yape" in r
        or "yapear" in r
        or "yolo" in r
        or "nequi" in r
        or "plin" in r
        or "send2wal" in r
        or "wallet" in r
        or "monedero" in r
        or "cartera digital" in r
        or "m-wallet" in r
    ):
        return "Billetera Digital"

    # --- Retiro en efectivo ---
    if (
        r.startswith("000")
        or "efectivo" in r
        or "cash" in r
        or "pickup" in r
        or "retirar" in r
        or "retiro" in r
        or "agent" in r
        or "agency" in r
        or "agente" in r
        or "money in minutes" in r
        or "office" in r
        or "branch" in r
        or "sucursal" in r
        or "recogida" in r
        or "ventanilla" in r
    ):
        return "Retiro en Efectivo"

    # --- Depósito bancario ---
    if (
        r.startswith("depósito")
        or r.startswith("deposito")
        or r.startswith("500")
        or "bank" in r
        or "banco" in r
        or "cuenta" in r
        or "account" in r
        or "cta" in r
        or "pix" in r
        or "direct to bank" in r
        or "bank account" in r
        or "deposit to" in r
        or "abono" in r
        or "acreditar" in r
    ):
        return "Depósito Bancario"

    return raw  # fallback: valor original
