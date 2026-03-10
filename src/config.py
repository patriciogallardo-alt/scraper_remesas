"""
Configuración central del scraper de remesas.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Monto fijo a cotizar ---
SEND_AMOUNT_CLP = 100_000

# --- Países destino ---
DESTINATIONS = [
    {"country_code": "PE", "country_name": "Perú",      "local_currency": "PEN"},
    {"country_code": "CO", "country_name": "Colombia",   "local_currency": "COP"},
    {"country_code": "AR", "country_name": "Argentina",  "local_currency": "ARS"},
    {"country_code": "BO", "country_name": "Bolivia",    "local_currency": "BOB"},
    {"country_code": "HT", "country_name": "Haití",      "local_currency": "HTG"},
    {"country_code": "VE", "country_name": "Venezuela",  "local_currency": "VES"},
    {"country_code": "BR", "country_name": "Brasil",     "local_currency": "BRL"},
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
