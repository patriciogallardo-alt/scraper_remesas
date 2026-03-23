"""
Scraper de Western Union (westernunion.com/cl).
Usa Playwright con stealth patches + perfil persistente, luego GraphQL API /router/.
"""
import asyncio
import hashlib
import json
import logging
import random
import uuid
import time
from datetime import datetime
from playwright.async_api import async_playwright
from src.scrapers.base import BaseScraper
from src.models import QuoteResult
from src.config import (
    WU_EMAIL, WU_PASSWORD, SEND_AMOUNT_CLP,
    BROWSER_PROFILES_DIR, normalize_country, normalize_currency,
    REQUEST_TIMEOUT, normalize_metodo_recaudacion, normalize_metodo_dispersion
)

logger = logging.getLogger(__name__)

WU_BASE = "https://www.westernunion.com"
WU_LOGIN_URL = f"{WU_BASE}/cl/es/web/user/login"
WU_ROUTER_URL = f"{WU_BASE}/router/"

# GraphQL query for products (extraída del HAR real de WU)
PRODUCTS_QUERY = """
query products($req_products: ProductsInput) {
  products(input: $req_products) {
    __typename
    ...on ProductsResponse {
      products {
        code
        name
        routingCode
        pricingContext
        segment
        payIn
        payOut
        payInType
        deliverySpeed
        minAmount
        maxAmount
        feePercentage
        fees
        strikeFees
        feeDetails {
          wuFee
          processorFee
          processorFeePercent
        }
        processorFee
        processorFeeVAT
        wuFeeVat
        destinationFees
        exchangeRate
        strikeExchangeRate
        maxPayout
        speedIndicator
        location
        expectedPayoutLocation {
          stateCode
          stateName
          city
        }
        origination {
          principalAmount
          grossAmount
          currencyIsoCode
          countryIsoCode
        }
        destination {
          expectedPayoutAmountLong
          currencyIsoCode
          countryIsoCode
          splitPayOut {
            expectedPayoutAmount
            currencyIsoCode
            exchangeRate
            countryIsoCode
          }
        }
        promotion {
          code
          message
          discountFee
          name
          description
          status
          promoCode
        }
        isDirected
        fxBand
        questionIndicator
        taxes {
          taxAmount
          municipalTax
          stateTax
          countyTax
          taxableAmount
        }
        isPendingPromoApplied
        agentAccountType
        agentAccountId
        institutionList {
          institutionCode
          institutionName
        }
        type
      }
      categories {
        type
        orders {
          payIn
          payOut
        }
      }
    }
    ...on ErrorResponse {
      errorCode
      message
    }
  }
}
"""

# ── Stealth JavaScript ──────────────────────────────────────────────
# Patches inyectados ANTES de cualquier navegación para ocultar
# marcadores de automatización de Playwright/Chrome DevTools Protocol.
STEALTH_JS = """
() => {
    // 1. Eliminar navigator.webdriver
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true
    });

    // 2. Simular plugins reales de Chrome
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const plugins = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
            ];
            plugins.length = 3;
            return plugins;
        },
        configurable: true
    });

    // 3. Simular languages correctos
    Object.defineProperty(navigator, 'languages', {
        get: () => ['es-CL', 'es', 'en-US', 'en'],
        configurable: true
    });

    // 4. chrome.runtime debe existir (Chrome real lo tiene)
    if (!window.chrome) window.chrome = {};
    if (!window.chrome.runtime) {
        window.chrome.runtime = {
            id: undefined,
            connect: function() {},
            sendMessage: function() {},
            onMessage: { addListener: function() {} }
        };
    }

    // 5. Permissions API: override query para notification
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => {
        if (parameters.name === 'notifications') {
            return Promise.resolve({ state: Notification.permission });
        }
        return originalQuery(parameters);
    };

    // 6. WebGL vendor/renderer realistas
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Google Inc. (NVIDIA)';
        if (parameter === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)';
        return getParameter.call(this, parameter);
    };

    // 7. Ocultar que estamos en headless (por si acaso)
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => 8,
        configurable: true
    });

    Object.defineProperty(navigator, 'deviceMemory', {
        get: () => 8,
        configurable: true
    });

    // 8. Ocultar la propiedad de automatización del CDP
    delete navigator.__proto__.webdriver;
}
"""


class WesternUnionScraper(BaseScraper):
    name = "Western Union"

    # device-id persistente (se genera una vez y se reutiliza)
    DEVICE_ID = "99b8997b-93cc-1544-f38a-1058258c474b"

    def __init__(self, shared_context=None):
        self.playwright = None
        self.context = shared_context
        self.page = None
        self.session_headers = {}
        self.fingerprint_id = None
        self.device_id = self.DEVICE_ID

    async def _init_browser(self):
        """Inicia Playwright con Chrome real o reusa global."""
        if self.context:
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            await self.context.add_init_script(STEALTH_JS)
            await self.page.evaluate(STEALTH_JS)
            logger.info("[WU] Reutilizando contexto compartido global. Aplicando evasión bot.")
            return

        import os
        profile_dir = os.path.join(BROWSER_PROFILES_DIR, "wu")
        os.makedirs(profile_dir, exist_ok=True)

        self.playwright = await async_playwright().start()

        # Args que NO delatan automatización (sin flags que Chrome muestre en banner)
        chrome_args = [
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1280,800",
        ]

        # Eliminar flags que delatan automatización:
        # --enable-automation: agrega banner "Chrome is being controlled"
        # --no-sandbox: agrega banner "no-sandbox" que WU detecta
        # --enable-blink-features=IdleDetection: flag interno de Playwright
        is_cloud = os.getenv("RENDER") == "true"
        ignored_default_args = [
            "--enable-automation",
            "--enable-blink-features=IdleDetection",
        ]
        if not is_cloud:
            # En local quitamos --no-sandbox para evadir anti-bots, en Linux/Docker es obligatorio
            ignored_default_args.append("--no-sandbox")
        self.context = await self.playwright.chromium.launch_persistent_context(
            profile_dir,
            headless=is_cloud,
            viewport={"width": 1280, "height": 800},
            locale="es-CL",
            timezone_id="America/Santiago",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            ignore_default_args=ignored_default_args,
            args=chrome_args,
        )

        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

        # Inyectar stealth patches ANTES de cualquier navegación
        await self.context.add_init_script(STEALTH_JS)
        # También inyectar en la página actual
        await self.page.evaluate(STEALTH_JS)

        logger.info("[WU] Browser iniciado con stealth patches.")

    async def _human_delay(self, min_sec=1.0, max_sec=3.0):
        """Delay aleatorio que simula comportamiento humano."""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

    async def _simulate_human_activity(self):
        """Simula actividad humana: scroll, movimiento de mouse."""
        try:
            # Scroll suave aleatorio
            scroll_y = random.randint(100, 400)
            await self.page.evaluate(f"window.scrollBy(0, {scroll_y})")
            await self._human_delay(0.5, 1.5)

            # Mouse move a posición aleatoria
            x = random.randint(200, 1000)
            y = random.randint(200, 600)
            await self.page.mouse.move(x, y)
            await self._human_delay(0.3, 0.8)

            # Scroll de vuelta
            await self.page.evaluate(f"window.scrollBy(0, -{scroll_y // 2})")
            await self._human_delay(0.3, 0.8)
        except Exception:
            pass

    async def _login(self):
        """
        Login en WU usando perfil persistente.
        Estrategia:
        1. Ir directo a send-money para verificar si la sesión persistida es válida
        2. Si redirige a login → pedir login manual UNA VEZ (el perfil la guarda)
        3. Futuras ejecuciones reutilizan la sesión automáticamente
        """
        # Paso 1: Verificar si ya hay sesión válida navegando directo a send-money
        logger.info("[WU] Verificando sesión existente en perfil persistente...")
        try:
            await self.page.goto(
                f"{WU_BASE}/cl/es/web/send-money/start",
                wait_until="domcontentloaded", timeout=30000
            )
            await self._human_delay(3, 5)

            current_url = self.page.url
            if "send-money" in current_url or "estimate" in current_url or "start" in current_url:
                # Verificar que no nos redirigió al login
                if "login" not in current_url:
                    logger.info("[WU] Sesión persistente válida. Login no necesario.")
                    return
        except Exception as e:
            logger.warning(f"[WU] Error verificando sesión: {e}")

        # Paso 2: No hay sesión → login manual con credenciales en consola
        logger.info("[WU] No hay sesión válida. Abriendo página de login...")
        try:
            await self.page.goto(WU_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            await self._human_delay(2, 4)

            # Aceptar cookies si aparece el banner
            try:
                cookie_btn = await self.page.query_selector(
                    "button#onetrust-accept-btn-handler, [aria-label='Accept Cookies']"
                )
                if cookie_btn:
                    await cookie_btn.click()
                    await self._human_delay(0.5, 1.5)
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"[WU] Error navegando al login: {e}")

        # Mostrar credenciales para copy-paste manual
        print()
        print("=" * 60)
        print("  WESTERN UNION - LOGIN MANUAL REQUERIDO")
        print("=" * 60)
        print()
        print("  La ventana de Chrome está abierta.")
        print("  Copia y pega estas credenciales manualmente:")
        print()
        print(f"  Email:      {WU_EMAIL}")
        print(f"  Contraseña: {WU_PASSWORD}")
        print()
        print("  (Solo necesitas hacerlo UNA VEZ - la sesión")
        print("   se guardará para futuras ejecuciones)")
        print()
        print("  Esperando hasta 3 minutos...")
        print("=" * 60)
        print()

        # Esperar a que el usuario complete el login
        for i in range(90):
            await asyncio.sleep(2)
            try:
                current_url = self.page.url
                if any(x in current_url for x in ["send-money", "estimate", "start"]) and "login" not in current_url:
                    logger.info("[WU] Login manual exitoso. Sesión guardada en perfil persistente.")
                    return

                # Detectar 2FA
                if i == 15:  # Después de 30 segundos, verificar 2FA
                    await self._handle_2fa()
            except Exception:
                pass

        logger.warning("[WU] Timeout esperando login manual. Continuando sin login...")

    async def _handle_2fa(self):
        """Espera 2FA manual si es necesario."""
        await asyncio.sleep(2)
        page_content = await self.page.content()
        otp_indicators = ["verification", "verify", "code", "OTP", "sms", "2fa", "confirmar", "verificar"]

        if any(ind.lower() in page_content.lower() for ind in otp_indicators):
            logger.info("[WU] *** 2FA detectado. Ingrese el código SMS en el browser. ***")
            logger.info("[WU] Esperando hasta 120 segundos...")

            for _ in range(60):
                await asyncio.sleep(2)
                current_url = self.page.url
                if "send-money" in current_url or "estimate" in current_url or "start" in current_url:
                    logger.info("[WU] 2FA completado.")
                    return

    async def _capture_fingerprint_id(self):
        """Intenta capturar el fingerprint-id que WU genera en el browser."""
        try:
            # WU usa FingerprintJS u otro fingerprinting. Intentar extraerlo.
            fp = await self.page.evaluate("""
                () => {
                    // Buscar en localStorage
                    const fpLocal = localStorage.getItem('fingerprint-id')
                        || localStorage.getItem('fp')
                        || localStorage.getItem('fingerprintId');
                    if (fpLocal) return fpLocal;

                    // Buscar en sessionStorage
                    const fpSession = sessionStorage.getItem('fingerprint-id')
                        || sessionStorage.getItem('fp')
                        || sessionStorage.getItem('fingerprintId');
                    if (fpSession) return fpSession;

                    // Buscar en cookies
                    const cookies = document.cookie.split(';');
                    for (const c of cookies) {
                        const [name, value] = c.trim().split('=');
                        if (name === 'fingerprint-id' || name === 'fp' || name === 'fingerprintId') {
                            return value;
                        }
                    }

                    // Buscar en window globals
                    if (window.__wu_fingerprint) return window.__wu_fingerprint;
                    if (window.fpId) return window.fpId;

                    return null;
                }
            """)

            if fp:
                self.fingerprint_id = fp
                logger.info(f"[WU] Fingerprint-id capturado: {fp[:12]}...")
                return
        except Exception as e:
            logger.debug(f"[WU] No se pudo extraer fingerprint del browser: {e}")

        # Generar un fingerprint realista como fallback
        # Basado en el formato del HAR: 32 chars hex (MD5-like)
        seed = f"{self.device_id}-{time.time()}"
        self.fingerprint_id = hashlib.md5(seed.encode()).hexdigest()
        logger.info(f"[WU] Fingerprint-id generado: {self.fingerprint_id[:12]}...")

    async def _capture_session_headers(self):
        """
        Intercepta requests al /router/ para capturar headers de sesión REALES.
        Estrategia: navegar a la página de envío, dejar que el JS de WU haga sus
        propias llamadas al /router/, y capturar los headers que usa.
        """
        logger.info("[WU] Capturando headers de sesión...")

        captured = {}
        all_header_keys = [
            "x-wu-sessionid", "x-wu-accesscode", "x-wu-apikey",
            "x-wu-correlationid", "x-wu-retailsessionid",
            "device-id", "fingerprint-id",
        ]

        async def intercept_request(request):
            if "/router/" in request.url:
                headers = request.headers
                for key in all_header_keys:
                    if key in headers and headers[key]:
                        captured[key] = headers[key]

        self.page.on("request", intercept_request)

        # Paso 1: Navegar a la home de WU Chile para establecer cookies de sesión
        try:
            logger.info("[WU] Paso 1: Navegando a WU Chile home...")
            await self.page.goto(
                f"{WU_BASE}/cl/es/home.html",
                wait_until="domcontentloaded", timeout=30000
            )
            await self._human_delay(3, 5)
            await self._simulate_human_activity()
        except Exception as e:
            logger.warning(f"[WU] Error en home: {e}")

        # Paso 2: Navegar a send-money/start (dispara GraphQL del frontend de WU)
        try:
            logger.info("[WU] Paso 2: Navegando a send-money/start...")
            await self.page.goto(
                f"{WU_BASE}/cl/es/web/send-money/start",
                wait_until="domcontentloaded", timeout=30000
            )
            # Esperar a que WU haga sus propios requests al /router/
            # El frontend de WU hace productos queries automáticas
            logger.info("[WU] Esperando que WU frontend haga sus propias llamadas...")
            await asyncio.sleep(8)
        except Exception as e:
            logger.warning(f"[WU] Error en send-money: {e}")

        # Paso 3: Si aún no capturamos, interactuar con la página
        if not captured.get("x-wu-accesscode"):
            try:
                logger.info("[WU] Paso 3: Interactuando con la página para provocar requests...")
                await self._simulate_human_activity()

                # Intentar click en un país para forzar un products query
                country_links = await self.page.query_selector_all(
                    '.country-item, [data-testid*="country"], a[href*="send-money"]'
                )
                if country_links and len(country_links) > 0:
                    await country_links[0].click()
                    await asyncio.sleep(5)
                else:
                    # Intentar buscar un input de país y escribir
                    search_input = await self.page.query_selector(
                        'input[placeholder*="país"], input[placeholder*="country"], '
                        'input[data-testid*="country"], input[aria-label*="country"]'
                    )
                    if search_input:
                        await search_input.click()
                        await self._human_delay(0.5, 1)
                        await search_input.type("Peru", delay=150)
                        await asyncio.sleep(3)
                        # Click primer resultado
                        first_result = await self.page.query_selector(
                            '[data-testid*="suggestion"], li[role="option"], .autocomplete-item'
                        )
                        if first_result:
                            await first_result.click()
                            await asyncio.sleep(5)
            except Exception as e:
                logger.warning(f"[WU] Error interactuando: {e}")

        self.page.remove_listener("request", intercept_request)

        # Capturar fingerprint del browser
        await self._capture_fingerprint_id()

        # Paso 4: También intentar extraer headers del JS runtime de WU
        if not captured.get("x-wu-accesscode"):
            try:
                js_headers = await self.page.evaluate("""
                    () => {
                        const result = {};
                        // WU guarda session info en window o localStorage
                        const checks = [
                            'sessionStorage', 'localStorage'
                        ];
                        for (const store of checks) {
                            try {
                                const s = window[store];
                                for (let i = 0; i < s.length; i++) {
                                    const key = s.key(i);
                                    const val = s.getItem(key);
                                    if (key.toLowerCase().includes('session')
                                        || key.toLowerCase().includes('access')
                                        || key.toLowerCase().includes('apikey')
                                        || key.toLowerCase().includes('token')) {
                                        result[key] = val;
                                    }
                                }
                            } catch(e) {}
                        }
                        // Check cookies
                        document.cookie.split(';').forEach(c => {
                            const [name, ...rest] = c.trim().split('=');
                            const val = rest.join('=');
                            if (name.includes('session') || name.includes('access')
                                || name.includes('Session') || name.includes('Access')) {
                                result[name.trim()] = val;
                            }
                        });
                        return result;
                    }
                """)
                if js_headers:
                    logger.info(f"[WU] Datos de sesión del JS runtime: {list(js_headers.keys())}")
                    # Mapear a nuestros headers
                    for key, val in js_headers.items():
                        if 'sessionid' in key.lower() or 'session_id' in key.lower():
                            captured.setdefault("x-wu-sessionid", val)
                        elif 'accesscode' in key.lower() or 'access_code' in key.lower():
                            captured.setdefault("x-wu-accesscode", val)
                        elif 'apikey' in key.lower() or 'api_key' in key.lower():
                            captured.setdefault("x-wu-apikey", val)
            except Exception as e:
                logger.debug(f"[WU] No se pudieron extraer headers del JS: {e}")

        if captured.get("x-wu-accesscode") or captured.get("x-wu-sessionid"):
            self.session_headers = captured
            logger.info(f"[WU] Headers capturados exitosamente: {list(captured.keys())}")
        else:
            logger.warning("[WU] No se pudieron capturar headers reales. Usando fallback de cookies.")
            cookies = await self.context.cookies()
            wu_cookies = {c["name"]: c["value"] for c in cookies if "westernunion" in c.get("domain", "")}
            logger.info(f"[WU] Cookies WU disponibles: {list(wu_cookies.keys())}")

            self.session_headers = {
                "x-wu-apikey": "1978",
                "x-wu-sessionid": wu_cookies.get("wuSessionId", f"web-{uuid.uuid4()}"),
                "x-wu-accesscode": wu_cookies.get("accessCode", ""),
            }

    def _build_full_headers(self, correlation_id: str, external_ref: str) -> dict:
        """Construye el set COMPLETO de headers que WU espera (basado en HAR)."""
        headers = {
            # ── Standard HTTP ──
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Origin": WU_BASE,
            "Referer": f"{WU_BASE}/cl/es/web/send-money/start",

            # ── WU Custom Headers (CRITICAL para anti-bot) ──
            "x-wu-operationname": "products",
            "x-wu-correlationid": correlation_id,
            "x-wu-externalrefid": external_ref,

            # ── Headers que faltaban (descubiertos en HAR) ──
            "device-id": self.device_id,
            "fingerprint-id": self.fingerprint_id or hashlib.md5(
                f"{self.device_id}-{time.time()}".encode()
            ).hexdigest(),
            "devicedetails": "Browser",
            "displaysystem": "Web",
            "platform": "nextgen",
            "source": "ExpPlatform",
            "calltrace": "Web",
            "canary": "false",
            "isrrenabled": "true",
            "wucountrycode": "CL",
            "wulanguagecode": "es",
            "user-identity": "registeredCustomer",

            # ── Client Hints (Chrome real) ──
            "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }

        # Merge session headers (x-wu-apikey, x-wu-sessionid, etc.)
        headers.update(self.session_headers)

        return headers

    async def _call_products(self, dest_country: str, dest_currency: str) -> dict:
        """Llama al GraphQL API de productos/pricing con headers completos."""
        # HAR usa formato "web-{uuid}" no "webapp-{uuid}"
        session_id = self.session_headers.get("x-wu-sessionid", f"web-{uuid.uuid4()}")
        correlation_id = session_id  # HAR muestra que usan el mismo sessionId
        external_ref = f"webapp-{uuid.uuid4()}"

        # Amount in WU is multiplied by 100 (centavos)
        amount_wu = SEND_AMOUNT_CLP * 100
        timestamp_ms = int(time.time() * 1000)

        variables = {
            "req_products": {
                "origination": {
                    "channel": "WWEB",
                    "client": "WUCOM",
                    "countryIsoCode": "CL",
                    "currencyIsoCode": "CLP",
                    "eflType": "STATE",
                    "amount": amount_wu,
                    "fundsIn": "*",
                    "airRequested": "Y"
                },
                "destination": {
                    "countryIsoCode": dest_country,
                    "currencyIsoCode": dest_currency
                },
                "headerRequest": {
                    "version": "0.5",
                    "requestType": "PRICECATALOG",
                    "correlationId": correlation_id,
                    "transactionId": f"{correlation_id}-{timestamp_ms}"
                },
                "visit": {
                    "localDatetime": {
                        "timeZone": 180,
                        "timestampMs": timestamp_ms
                    }
                },
                "visitor": {
                    "customerId": ""
                }
            }
        }

        headers = self._build_full_headers(correlation_id, external_ref)

        payload = {
            "variables": variables,
            "query": PRODUCTS_QUERY
        }

        # Ejecutar fetch DENTRO del contexto del browser (hereda cookies, TLS, etc.)
        result = await self.page.evaluate('''async ([url, payload, hdrs]) => {
            try {
                const resp = await fetch(url, {
                    method: "POST",
                    headers: hdrs,
                    body: JSON.stringify(payload),
                    credentials: "include"
                });
                return {
                    status: resp.status,
                    ok: resp.ok,
                    text: await resp.text()
                };
            } catch (err) {
                return { status: 0, ok: false, text: err.toString() };
            }
        }''', [WU_ROUTER_URL, payload, headers])

        status = result.get("status")
        text = result.get("text", "")

        if not result.get("ok"):
            logger.error(f"[WU] Response HTTP {status}: {text[:500]}")
            raise Exception(f"HTTP {status} en _call_products: {text[:300]}")

        parsed = json.loads(text)

        # Log para debug: ver estructura de respuesta
        if parsed.get("data", {}).get("products", {}).get("__typename") == "ErrorResponse":
            error_resp = parsed["data"]["products"]
            logger.error(f"[WU] ErrorResponse: {error_resp}")
        elif parsed.get("errors"):
            logger.error(f"[WU] GraphQL errors: {parsed['errors']}")

        return parsed

    async def scrape(self, destinations: list[dict]) -> list[QuoteResult]:
        """Ejecuta scraping de WU para todos los destinos."""
        results = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Init browser con stealth, capturar sesión
        await self._init_browser()
        await self._login()
        await self._capture_session_headers()

        # Simular actividad humana antes de las queries
        await self._simulate_human_activity()
        await self._human_delay(1, 3)

        # 2. Iterate destinations con delays humanos
        for i, dest in enumerate(destinations):
            code = dest["country_code"]
            country_name = normalize_country(dest["country_name"], code)
            local_currency = dest["local_currency"]

            currencies_to_try = [local_currency, "USD"]

            for currency in currencies_to_try:
                try:
                    logger.info(f"[WU] Cotizando {country_name} en {currency}...")

                    # Delay humano entre requests (más largo cada N requests)
                    if i > 0:
                        await self._human_delay(2.0, 5.0)

                    data = await self._call_products(code, currency)

                    # Verificar si hay error de bot en la respuesta
                    errors = data.get("errors", [])
                    if errors:
                        error_codes = [e.get("extensions", {}).get("code", "") for e in errors]
                        if any("C1131" in str(c) for c in error_codes):
                            logger.error(f"[WU] Bot detectado en response para {country_name}/{currency}")
                            continue

                    products_resp = data.get("data", {}).get("products", {})
                    products = products_resp.get("products", [])

                    if not products:
                        logger.info(f"[WU] {country_name}/{currency}: sin productos disponibles")
                        continue

                    for product in products:
                        try:
                            origination = product.get("origination", {}) or {}
                            destination = product.get("destination", {}) or {}
                            taxes_data = product.get("taxes", {}) or {}
                            fee_details = product.get("feeDetails", {}) or {}
                            promotion = product.get("promotion", {}) or {}

                            # Exchange rate (top-level en nuevo esquema)
                            exchange_rate = float(product.get("exchangeRate", 0) or 0)

                            # Todos los montos monetarios en WU vienen en centavos (x100).
                            # Normalizamos SIEMPRE a unidades dividiendo por 100 para evitar
                            # errores de escala (por ejemplo 37.692,00 en lugar de 376,92).
                            raw_receive = float(destination.get("expectedPayoutAmountLong", 0) or 0)
                            receive_amount = raw_receive / 100 if raw_receive else 0.0

                            raw_principal = float(origination.get("principalAmount", 0) or 0)
                            principal = raw_principal / 100 if raw_principal else 0.0

                            raw_gross = float(origination.get("grossAmount", 0) or 0)
                            gross = raw_gross / 100 if raw_gross else 0.0

                            # Fees
                            raw_fees = float(product.get("fees", 0) or 0)
                            fees_raw = raw_fees / 100 if raw_fees else 0.0

                            # Descuento promo
                            raw_promo = float(promotion.get("discountFee", 0) or 0)
                            promo_discount = raw_promo / 100 if raw_promo else 0.0

                            fee_base = fees_raw - promo_discount

                            # Tax
                            raw_tax = float(taxes_data.get("taxAmount", 0) or 0)
                            tax_amount = raw_tax / 100 if raw_tax else 0.0

                            total_charged = principal + fee_base + tax_amount

                            pay_in = product.get("payIn", "N/D")
                            pay_out = product.get("payOut", "N/D")
                            product_name = product.get("name", "N/D")

                            dest_currency_norm = normalize_currency(
                                destination.get("currencyIsoCode", currency)
                            )

                            dispersion_raw = f"{pay_out} ({product_name})"
                            results.append(QuoteResult(
                                timestamp=timestamp,
                                agente="Western Union",
                                pais_destino=country_name,
                                moneda_origen="CLP",
                                moneda_destino=dest_currency_norm,
                                monto_enviado=float(SEND_AMOUNT_CLP),
                                monto_recibido=receive_amount,
                                tasa_de_cambio=exchange_rate,
                                fee_base=fee_base,
                                fee_impuesto=tax_amount,
                                total_cobrado=total_charged,
                                metodo_recaudacion=pay_in,
                                metodo_dispersion=dispersion_raw,
                                categoria_recaudacion=normalize_metodo_recaudacion(pay_in),
                                categoria_dispersion=normalize_metodo_dispersion(dispersion_raw),
                            ))
                        except Exception as e:
                            logger.error(f"[WU] Error parseando producto: {e}")

                    logger.info(f"[WU] {country_name}/{currency}: {len(products)} productos")

                except Exception as e:
                    logger.error(f"[WU] Error {country_name}/{currency}: {e}")
                    continue

        logger.info(f"[WU] Total resultados: {len(results)}")
        return results

    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
