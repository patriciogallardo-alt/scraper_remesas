"""
Scraper de Western Union (westernunion.com/cl).
Usa Playwright para login + perfil persistente, luego GraphQL API /router/.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime
import requests as req
from playwright.async_api import async_playwright
from src.scrapers.base import BaseScraper
from src.models import QuoteResult
from src.config import (
    WU_EMAIL, WU_PASSWORD, SEND_AMOUNT_CLP,
    BROWSER_PROFILES_DIR, normalize_country, normalize_currency,
    REQUEST_TIMEOUT
)

logger = logging.getLogger(__name__)

WU_BASE = "https://www.westernunion.com"
WU_LOGIN_URL = f"{WU_BASE}/cl/es/web/user/login"
WU_ROUTER_URL = f"{WU_BASE}/router/"

# GraphQL query for products (discovered from HAR)
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
        payIn
        payOut
        fees {
          charges
          promotionDiscount
          currencyCode
        }
        fx {
          originCurrencyCode
          destinationCurrencyCode
          exchangeRate
        }
        grossAmount
        receiveAmount
        receiveCurrencyCode
        sendAmount
        sendCurrencyCode
        tolls
        estimatedDeliveryDate
      }
    }
  }
}
"""


class WesternUnionScraper(BaseScraper):
    name = "Western Union"

    def __init__(self):
        self.playwright = None
        self.context = None
        self.page = None
        self.session_headers = {}

    async def _init_browser(self):
        """Inicia Playwright con Chrome real del sistema (no test Chromium)."""
        import os
        profile_dir = os.path.join(BROWSER_PROFILES_DIR, "wu")
        os.makedirs(profile_dir, exist_ok=True)

        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            profile_dir,
            channel="chrome",  # Usa Chrome real, no test Chromium
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale="es-CL",
            timezone_id="America/Santiago",
            ignore_default_args=["--enable-automation"],
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

    async def _login(self):
        """Login en WU. Si requiere 2FA, espera intervención manual."""
        logger.info("[WU] Navegando al login...")
        await self.page.goto(WU_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

        # Check if already logged in
        current_url = self.page.url
        if "send-money" in current_url or "estimate" in current_url:
            logger.info("[WU] Ya hay sesión activa.")
            return

        # Try to find and fill login form
        try:
            email_input = await self.page.query_selector(
                'input[type="email"], input[name="email"], #email, input[data-testid="email"]'
            )
            if email_input:
                logger.info("[WU] Ingresando credenciales humano-like...")
                await email_input.focus()
                await email_input.type(WU_EMAIL, delay=150)

                password_input = await self.page.query_selector(
                    'input[type="password"], input[name="password"], #password'
                )
                if password_input:
                    await password_input.focus()
                    await password_input.type(WU_PASSWORD, delay=150)

                # Accept cookies if banner is blocking the view
                try:
                    cookie_btn = await self.page.query_selector(
                        "button#onetrust-accept-btn-handler, [aria-label='Accept Cookies']"
                    )
                    if cookie_btn:
                        await cookie_btn.click()
                        await asyncio.sleep(1)
                except Exception:
                    pass

                # Try submitting via Enter key first
                await password_input.press("Enter")
                await asyncio.sleep(2)

                # Click submit as fallback
                submit_btn = await self.page.query_selector(
                    'button[type="submit"], .btn-login, [data-testid="login-button"], button#button-continue'
                )
                if submit_btn:
                    await submit_btn.click()
                
                await asyncio.sleep(6)

                # Check for bot block or C1131 error
                content = await self.page.content()
                if "Algo está mal" in content or "C1131" in content:
                    logger.error("=" * 60)
                    logger.error("[WU] BLOQUEO DETECTADO (Error C1131 / Bot).")
                    logger.error("[WU] INSTRUCCIÓN MANUAL: La ventana de Chrome está abierta.")
                    logger.error("[WU] Ingresa MALA CONTRASEÑA, resuelve el CAPTCHA/2FA y luego ingresa la correcta.")
                    logger.error("[WU] INICIA SESIÓN TÚ MISMO AHORA. El bot te esperará 3 minutos.")
                    logger.error("=" * 60)
                    
                    for _ in range(90):
                        await asyncio.sleep(2)
                        current_url = self.page.url
                        if "send-money" in current_url or "estimate" in current_url or "start" in current_url:
                            logger.info("[WU] Login manual exitoso detectado. Continuando automated run...")
                            return
                else:
                    # Handle 2FA
                    await self._handle_2fa()
        except Exception as e:
            logger.warning(f"[WU] Error en login: {e}")

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

    async def _capture_session_headers(self):
        """Intercepta requests al /router/ para capturar headers de sesión."""
        logger.info("[WU] Capturando headers de sesión...")

        captured = {}

        async def intercept_request(request):
            if "/router/" in request.url:
                headers = request.headers
                for key in ["x-wu-sessionid", "x-wu-accesscode", "x-wu-apikey",
                            "x-wu-correlationid"]:
                    if key in headers:
                        captured[key] = headers[key]

        self.page.on("request", intercept_request)

        # Navigate to the send money flow to trigger a /router/ request
        try:
            await self.page.goto(
                f"{WU_BASE}/cl/es/web/send-money/start",
                wait_until="networkidle", timeout=30000
            )
            await asyncio.sleep(3)

            # Try to select a country to trigger products request
            # Click on Peru or first available country
            country_links = await self.page.query_selector_all('.country-item, [data-testid*="country"]')
            if country_links and len(country_links) > 0:
                await country_links[0].click()
                await asyncio.sleep(3)

        except Exception as e:
            logger.warning(f"[WU] Error capturando headers: {e}")

        self.page.remove_listener("request", intercept_request)

        if captured:
            self.session_headers = captured
            logger.info(f"[WU] Headers capturados: {list(captured.keys())}")
        else:
            logger.warning("[WU] No se pudieron capturar headers automáticamente.")
            # Try to extract from cookies/page
            cookies = await self.context.cookies()
            wu_cookies = {c["name"]: c["value"] for c in cookies if "westernunion" in c.get("domain", "")}

            # Fallback: use known defaults
            self.session_headers = {
                "x-wu-apikey": "1978",
                "x-wu-sessionid": wu_cookies.get("wuSessionId", f"web-{uuid.uuid4()}"),
                "x-wu-accesscode": wu_cookies.get("accessCode", ""),
            }

    async def _call_products(self, dest_country: str, dest_currency: str) -> dict:
        """Llama al GraphQL API de productos/pricing."""
        correlation_id = f"webapp-{uuid.uuid4()}"
        external_ref = f"webapp-{uuid.uuid4()}"

        # Amount in WU is multiplied by 100
        amount_wu = SEND_AMOUNT_CLP * 100

        import time
        timestamp_ms = int(time.time() * 1000)

        # Build the variables structure (matches HAR)
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

        headers = {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Origin": WU_BASE,
            "Referer": f"{WU_BASE}/cl/es/web/send-money/start",
            "x-wu-operationname": "products",
            "x-wu-correlationid": correlation_id,
            "x-wu-externalrefid": external_ref,
        }
        headers.update(self.session_headers)

        # Build the GraphQL payload
        payload = {
            "operationName": "products",
            "variables": variables,
            "query": PRODUCTS_QUERY
        }

        # Use fetch within the page context to prevent anti-bot blocking
        result = await self.page.evaluate('''async ([url, payload, hdrs]) => {
            try {
                const resp = await fetch(url, {
                    method: "POST",
                    headers: hdrs,
                    body: JSON.stringify(payload)
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

        if not result.get("ok"):
            text = result.get("text", "")
            raise Exception(f"HTTP {result.get('status')} en _call_products: {text[:200]}")

        return json.loads(result["text"])

    async def _get_cookies_dict(self) -> dict:
        cookies = await self.context.cookies()
        return {c["name"]: c["value"] for c in cookies if "westernunion" in c.get("domain", "")}

    async def scrape(self, destinations: list[dict]) -> list[QuoteResult]:
        """Ejecuta scraping de WU para todos los destinos."""
        results = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Init browser, login, capture session
        await self._init_browser()
        # await self._login()  # Guest flow bypasses C1131 bot block
        await self._capture_session_headers()

        # 2. Iterate destinations
        for dest in destinations:
            code = dest["country_code"]
            country_name = normalize_country(dest["country_name"], code)
            local_currency = dest["local_currency"]

            # Try local currency first, then USD
            currencies_to_try = [local_currency, "USD"]

            for currency in currencies_to_try:
                try:
                    logger.info(f"[WU] Cotizando {country_name} en {currency}...")
                    data = await self._call_products(code, currency)

                    products_resp = data.get("data", {}).get("products", {})
                    products = products_resp.get("products", [])

                    if not products:
                        logger.info(f"[WU] {country_name}/{currency}: sin productos disponibles")
                        continue

                    for product in products:
                        try:
                            fx = product.get("fx", {}) or {}
                            fees_data = product.get("fees", {}) or {}

                            exchange_rate = float(fx.get("exchangeRate", 0) or 0)
                            receive_amount = float(product.get("receiveAmount", 0) or 0)
                            send_amount = float(product.get("sendAmount", 0) or 0)
                            gross_amount = float(product.get("grossAmount", 0) or 0)

                            # WU amounts come in cents, divide by 100
                            receive_amount = receive_amount / 100 if receive_amount > 100000 else receive_amount
                            send_amount_real = send_amount / 100 if send_amount > 1000000 else send_amount

                            charges = float(fees_data.get("charges", 0) or 0)
                            charges = charges / 100 if charges > 100000 else charges

                            promo_discount = float(fees_data.get("promotionDiscount", 0) or 0)
                            promo_discount = promo_discount / 100 if promo_discount > 100000 else promo_discount

                            fee_base = charges - promo_discount
                            total_charged = send_amount_real + fee_base

                            pay_in = product.get("payIn", "N/D")
                            pay_out = product.get("payOut", "N/D")
                            product_name = product.get("name", "N/D")

                            dest_currency = normalize_currency(
                                product.get("receiveCurrencyCode", currency)
                            )

                            results.append(QuoteResult(
                                timestamp=timestamp,
                                agente="Western Union",
                                pais_destino=country_name,
                                moneda_origen="CLP",
                                moneda_destino=dest_currency,
                                monto_enviado=float(SEND_AMOUNT_CLP),
                                monto_recibido=receive_amount,
                                tasa_de_cambio=exchange_rate,
                                fee_base=fee_base,
                                fee_impuesto=0.0,  # WU doesn't separate tax in API
                                total_cobrado=total_charged,
                                metodo_recaudacion=pay_in,
                                metodo_dispersion=f"{pay_out} ({product_name})",
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
