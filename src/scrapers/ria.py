"""
Scraper de RIA Money Transfer (secure.riamoneytransfer.com).
Usa Playwright para login + perfil persistente, luego REST API para cotizaciones.
"""
import asyncio
import json
import logging
from datetime import datetime
from playwright.async_api import async_playwright
from src.scrapers.base import BaseScraper
from src.models import QuoteResult
from src.config import (
    RIA_EMAIL, RIA_PASSWORD, SEND_AMOUNT_CLP,
    BROWSER_PROFILES_DIR, normalize_country, normalize_currency,
    REQUEST_TIMEOUT, normalize_metodo_recaudacion, normalize_metodo_dispersion
)

logger = logging.getLogger(__name__)

CALCULATE_URL = "https://secure.riamoneytransfer.com/api/moneytransfercalculator/calculate"
LOGIN_URL = "https://secure.riamoneytransfer.com"


class RiaScraper(BaseScraper):
    name = "RIA"

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def _init_browser(self):
        """Inicia Playwright con Chrome real del sistema (no test Chromium)."""
        import os
        profile_dir = os.path.join(BROWSER_PROFILES_DIR, "ria")
        os.makedirs(profile_dir, exist_ok=True)

        self.playwright = await async_playwright().start()
        is_cloud = os.getenv("RENDER") == "true"
        self.context = await self.playwright.chromium.launch_persistent_context(
            profile_dir,
            headless=is_cloud,
            viewport={"width": 1280, "height": 800},
            locale="es-CL",
            timezone_id="America/Santiago",
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

    async def _login(self):
        """Login en RIA. Si requiere 2FA, espera intervención manual."""
        logger.info("[RIA] Navegando al login...")
        await self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)

        # Check if already logged in (look for calculator or dashboard elements)
        current_url = self.page.url
        if "/send" in current_url or "/dashboard" in current_url:
            logger.info("[RIA] Ya hay sesión activa.")
            return

        # Check if we're on a login page
        try:
            email_field = await self.page.query_selector('input[type="email"], input[name="email"], #email')
            if email_field:
                logger.info("[RIA] Ingresando credenciales...")
                await email_field.fill(RIA_EMAIL)

                password_field = await self.page.query_selector(
                    'input[type="password"], input[name="password"], #password'
                )
                if password_field:
                    await password_field.fill(RIA_PASSWORD)

                # Click login button
                login_btn = await self.page.query_selector(
                    'button[type="submit"], .login-button, #loginButton'
                )
                if login_btn:
                    await login_btn.click()
                    await asyncio.sleep(3)

                # Check for 2FA
                await self._handle_2fa()
            else:
                logger.info("[RIA] No se encontró campo de email, posible sesión activa.")
        except Exception as e:
            logger.warning(f"[RIA] Error en login flow: {e}")

    async def _handle_2fa(self):
        """Si aparece 2FA, espera que el usuario lo resuelva manualmente."""
        await asyncio.sleep(2)
        # Look for 2FA/OTP indicators
        page_content = await self.page.content()
        otp_indicators = ["verification", "verify", "code", "OTP", "sms", "2fa", "confirmar"]

        if any(indicator.lower() in page_content.lower() for indicator in otp_indicators):
            logger.info("[RIA] *** 2FA detectado. Por favor ingrese el código SMS en el browser. ***")
            logger.info("[RIA] Esperando hasta 120 segundos...")

            # Wait up to 120 seconds for user to complete 2FA
            for i in range(60):
                await asyncio.sleep(2)
                current_url = self.page.url
                if "/send" in current_url or "/dashboard" in current_url or "calculator" in current_url:
                    logger.info("[RIA] 2FA completado exitosamente.")
                    return

            logger.warning("[RIA] Timeout esperando 2FA. Continuando de todos modos...")

    async def _get_cookies_dict(self) -> dict:
        """Extrae cookies del browser context."""
        cookies = await self.context.cookies()
        return {c["name"]: c["value"] for c in cookies if "riamoneytransfer" in c.get("domain", "")}

    async def _calculate(self, country_code: str, currency_to: str = None,
                         delivery_method: str = None, payment_method: str = None) -> dict:
        """Llama a la API de cálculo de RIA usando el request context nativo de Playwright."""
        payload = {
            "selections": {
                "countryTo": country_code,
                "amountFrom": self.amount,
                "amountTo": None,
                "currencyFrom": "CLP",
                "shouldCalcAmountFrom": False,
                "shouldCalcVariableRates": True,
                "shouldCalcFeesForPaymentMethods": []
            }
        }

        if currency_to:
            payload["selections"]["currencyTo"] = currency_to
        if delivery_method:
            payload["selections"]["deliveryMethod"] = delivery_method
        if payment_method:
            payload["selections"]["paymentMethod"] = payment_method
            # Importante: esta lista controla para qué métodos devuelve fee/tax detallado.
            payload["selections"]["shouldCalcFeesForPaymentMethods"] = [payment_method]

        # Ejecutamos fetch en el contexto del navegador para heredar XSRF, headers reales y contexto origin()
        # Esto previene errores 500 causados por protecciones anti-bot de la API.
        result = await self.page.evaluate('''async ([url, payload]) => {
            try {
                const resp = await fetch(url, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/plain, */*",
                        "apptype": "2",
                        "appversion": "4.84.0",
                        "brand": "0",
                        "client-type": "RMT4",
                        "countryid": "3105",
                        "culturecode": "es-ES",
                        "isocode": "CL",
                        "locale": "es-ES",
                        "platform": "RMT4"
                    },
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
        }''', [CALCULATE_URL, payload])

        if not result.get("ok"):
            raise Exception(f"Error HTTP {result.get('status')} en _calculate: {result.get('text', '')[:200]}")
            
        return json.loads(result["text"])

    async def scrape(self, destinations: list[dict], amount: int = None) -> list[QuoteResult]:
        """Ejecuta scraping de RIA para todos los destinos."""
        self.amount = amount or SEND_AMOUNT_CLP
        results = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Init browser and login
        await self._init_browser()
        await self._login()
        await asyncio.sleep(2)

        # Navigate to the send money page to ensure session is valid for API calls
        try:
            await self.page.goto(
                "https://secure.riamoneytransfer.com/send/moneytransfer",
                wait_until="domcontentloaded", timeout=30000
            )
            await asyncio.sleep(2)
        except Exception:
            pass

        # 2. Iterate destinations
        for dest in destinations:
            code = dest["country_code"]
            country_name = normalize_country(dest["country_name"], code)

            try:
                # First call without currency to discover available currencies
                logger.info(f"[RIA] Descubriendo monedas para {country_name}...")
                discovery_data = await self._calculate(code)

                model = discovery_data.get("model", {})
                transfer = model.get("transferDetails", {})
                options = transfer.get("transferOptions", {})

                # Get available currencies for this country
                available_currencies = []
                for curr in options.get("currencies", []):
                    currency_code = curr.get("currencyCode", "")
                    if currency_code:
                        available_currencies.append(currency_code)

                if not available_currencies:
                    # Fallback: use the currency from the calculation
                    selections = transfer.get("selections", {})
                    fallback_curr = selections.get("currencyTo", "")
                    if fallback_curr:
                        available_currencies = [fallback_curr]

                logger.info(f"[RIA] {country_name}: monedas disponibles: {available_currencies}")

                # Get available delivery methods
                available_delivery = [
                    dm.get("value", "") for dm in options.get("deliveryMethods", [])
                ]
                available_payment = [
                    pm.get("value", "") for pm in options.get("paymentMethods", [])
                ]

                # For each currency, get full calculation
                for currency in available_currencies:
                    for delivery in (available_delivery or [None]):
                        try:
                            # Iterar por todos los métodos de pago disponibles para capturar
                            # combinaciones (incluyendo "Depósito con tarjeta de débito").
                            for payment in (available_payment or [None]):
                                data = await self._calculate(
                                    code,
                                    currency_to=currency,
                                    delivery_method=delivery,
                                    payment_method=payment,
                                )

                                model = data.get("model", {})
                                td = model.get("transferDetails", {})
                                calc = td.get("calculations", {})
                                sel = td.get("selections", {})

                                # Extract fee details
                                transfer_fee = float(calc.get("transferFee", 0) or 0)
                                tax_amount = float(calc.get("taxAmount", 0) or 0)
                                total_amount = float(calc.get("totalAmount", 0) or 0)
                                amount_to = float(calc.get("amountTo", 0) or 0)
                                exchange_rate = float(calc.get("exchangeRate", 0) or 0)

                                # Get delivery/payment method labels
                                delivery_label = delivery or sel.get("deliveryMethod", "N/D")
                                delivery_methods_map = {
                                    dm["value"]: dm.get("text", dm["value"])
                                    for dm in options.get("deliveryMethods", [])
                                }
                                delivery_label = delivery_methods_map.get(delivery_label, delivery_label)

                                payment_label = payment or sel.get("paymentMethod", "N/D")
                                payment_methods_map = {
                                    pm["value"]: pm.get("text", pm["value"])
                                    for pm in options.get("paymentMethods", [])
                                }
                                payment_label = payment_methods_map.get(payment_label, payment_label)

                                dest_currency = normalize_currency(
                                    currency or sel.get("currencyTo", "")
                                )

                                results.append(QuoteResult(
                                    timestamp=timestamp,
                                    agente="RIA",
                                    pais_destino=country_name,
                                    moneda_origen="CLP",
                                    moneda_destino=dest_currency,
                                    monto_enviado=float(SEND_AMOUNT_CLP),
                                    monto_recibido=amount_to,
                                    tasa_de_cambio=exchange_rate,
                                    fee_base=transfer_fee,
                                    fee_impuesto=tax_amount,
                                    total_cobrado=total_amount,
                                    metodo_recaudacion=payment_label,
                                    metodo_dispersion=delivery_label,
                                    categoria_recaudacion=normalize_metodo_recaudacion(payment_label),
                                    categoria_dispersion=normalize_metodo_dispersion(delivery_label),
                                ))

                        except Exception as e:
                            logger.error(
                                f"[RIA] Error {country_name}/{currency}/{delivery}: {e}"
                            )

                logger.info(f"[RIA] {country_name}: procesado OK")

            except Exception as e:
                logger.error(f"[RIA] Error procesando {country_name}: {e}")
                continue

        logger.info(f"[RIA] Total resultados: {len(results)}")
        return results

    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
