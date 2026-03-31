"""
Scraper de AFEX Connect (afexconnect.com).
Usa Cognito auth + GraphQL via AWS Lambda. Sin browser.
"""
import logging
import requests
from datetime import datetime
from src.scrapers.base import BaseScraper
from src.models import QuoteResult
from src.config import (
    AFEX_USERNAME, AFEX_PASSWORD, SEND_AMOUNT_CLP,
    normalize_country, normalize_currency, REQUEST_TIMEOUT,
    normalize_metodo_recaudacion, normalize_metodo_dispersion
)

logger = logging.getLogger(__name__)

# --- AFEX Connect endpoints (descubiertos del HAR) ---
PUBLIC_URL = "https://hasacv5rf9.execute-api.us-east-1.amazonaws.com/prod/v1/public"
PUBLIC_API_KEY = "lVyB8gmrhKIw7BZUkqJYAqCHAp6Pnl3zEWnM4Pi0"
SIGNIN_URL = "https://0hgu1h4p88.execute-api.us-east-2.amazonaws.com/prod/afex-client-api-key"
GRAPHQL_URL = "https://jmpw2xetb3.execute-api.us-east-2.amazonaws.com/prod/"

# Para cash pickup y depósitos, cotizamos solo en un subconjunto pequeño
# de combinaciones para evitar explosión de tiempo de ejecución.
MAX_CITIES_CASH_PICKUP = 3
MAX_BANKS_DEPOSITO = 3

# GraphQL query para getFeelookup
FEELOOKUP_QUERY = """
query getFeelookup($variables: GetFeelookupRequestInput) {
  getFeelookup(variables: $variables) {
    data {
      id
      quotes {
        id
        expiresAt
        agent { id name __typename }
        fees {
          afex collector parentCompany payer intermediary
          suggested total __typename
        }
        payment { amount __typename }
        receive {
          agency amount city country currency
          methodPayment methodPaymentId __typename
        }
        transfer {
          amount amountDifferenceCLP amountUSD currency
          exchangeRate parity __typename
        }
        promocode { campaign discount __typename }
        conditions { estimatedTime __typename }
        highlights { isFastest suggested isMostConvenient __typename }
        amountRange { minimumAmount maximumAmount __typename }
        conversionInfo {
          sourceAmount sourceCurrency targetAmount targetCurrency __typename
        }
        __typename
      }
      __typename
    }
    status
    error {
      error { step severity uiMessage __typename }
      errorUIMessage {
        uiTitle uiBodyText uiButtonText uiRedirectPath
        errorSnippet showAdditionalInfo __typename
      }
      __typename
    }
    __typename
  }
}
"""

PAYMENT_METHODS_QUERY = """
query getPaymentMethods($alpha2CountryCode: String) {
  getPaymentMethods(alpha2CountryCode: $alpha2CountryCode) {
    data {
      methodPayment
      methodPaymentId
      bank {
        id
        name
        agents {
          methodPayment
          bankCode
          agentId
          suggested
          receiveAgentId
          conditions {
            estimatedTime
            __typename
          }
          __typename
        }
        __typename
      }
      __typename
    }
    status
    error {
      error {
        step
        severity
        uiMessage
        __typename
      }
      errorUIMessage {
        uiTitle
        uiBodyText
        uiButtonText
        uiRedirectPath
        errorSnippet
        showAdditionalInfo
        __typename
      }
      __typename
    }
    __typename
  }
}
"""

BANKS_QUERY = """
query getBanks($alpha2CountryCode: String, $methodPaymentId: Int) {
  getBanks(
    alpha2CountryCode: $alpha2CountryCode
    methodPaymentId: $methodPaymentId
  ) {
    data {
      id
      name
      agents {
        methodPayment
        bankCode
        agentId
        suggested
        receiveAgentId
        conditions {
          estimatedTime
          __typename
        }
        __typename
      }
      __typename
    }
    status
    error {
      error {
        step
        severity
        uiMessage
        __typename
      }
      errorUIMessage {
        uiTitle
        uiBodyText
        uiButtonText
        uiRedirectPath
        errorSnippet
        showAdditionalInfo
        __typename
      }
      __typename
    }
    __typename
  }
}
"""

GET_CITIES_QUERY = """
query getCities($alpha2CountryCode: String) {
  getCities(alpha2CountryCode: $alpha2CountryCode) {
    data {
      id
      code
      callingCode
      name
      countryId
      alpha2CountryCode
      alpha3CountryCode
      __typename
    }
    status
    error {
      error {
        step
        severity
        uiMessage
        __typename
      }
      errorUIMessage {
        uiTitle
        uiBodyText
        uiButtonText
        uiRedirectPath
        errorSnippet
        showAdditionalInfo
        __typename
      }
      __typename
    }
    __typename
  }
}
"""

COUNTRIES_QUERY = """
query getCountries {
  getCountries {
    code
    name
    feeLookup {
      currency
      minimumAmount
    }
  }
}
"""

COLLECT_METHODS_QUERY = """
query getCollectMethods($feelookupId: String, $quoteId: Int) {
  getCollectMethods(feelookupId: $feelookupId, quoteId: $quoteId) {
    data {
      name
      description
      fees {
        afex collector parentCompany payer intermediary
        suggested connectCollectMethod total __typename
      }
      isEnabled
      nameClient
      __typename
    }
    status
    error {
      error { step severity uiMessage __typename }
      __typename
    }
    __typename
  }
}
"""

SIGNIN_QUERY = """
query signIn($email: String!, $password: String!) {
  signIn(email: $email, password: $password) {
    error
    data
    user {
      id
      username
      attributes {
        sub
        email
        name
        family_name
        phone_number
        custom_codigoClienteGiro
        custom_codigoCorporativa
        __typename
      }
      __typename
    }
    __typename
  }
}
"""


class AfexScraper(BaseScraper):
    name = "AFEX"

    def __init__(self):
        self.session = requests.Session()
        self.access_token = None
        self.id_token = None

    async def _authenticate(self):
        """Login via GraphQL signIn on afex-client-api-key endpoint."""
        logger.info("[AFEX] Autenticando...")

        payload = {
            "operationName": "signIn",
            "variables": {
                "email": AFEX_USERNAME,
                "password": AFEX_PASSWORD
            },
            "query": SIGNIN_QUERY
        }

        resp = self.session.post(
            SIGNIN_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Origin": "https://afexconnect.com",
                "Referer": "https://afexconnect.com/",
            },
            timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()

        sign_in = data.get("data", {}).get("signIn", {})
        if sign_in.get("error"):
            raise Exception(f"AFEX login failed: {sign_in['error']}")

        # signIn returns a JWT session token directly in the 'data' field
        session_token = sign_in.get("data", "")
        if not session_token:
            raise Exception("AFEX login: no session token returned")

        self.id_token = session_token

        # Set auth header for GraphQL requests
        self.session.headers.update({
            "Authorization": f"Bearer {self.id_token}",
            "Content-Type": "application/json",
            "Origin": "https://afexconnect.com",
            "Referer": "https://afexconnect.com/",
        })

        logger.info("[AFEX] Autenticación exitosa.")

    async def _get_available_countries(self) -> list[dict]:
        """Obtiene los países disponibles en AFEX (endpoint público)."""
        payload = {
            "operationName": "getCountries",
            "query": COUNTRIES_QUERY
        }
        resp = self.session.post(
            PUBLIC_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": PUBLIC_API_KEY,
                "Origin": "https://www.afex.cl",
                "Referer": "https://www.afex.cl/",
            },
            timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
        countries = data.get("data", {}).get("getCountries", [])
        return countries

    async def _get_payment_methods(self, country_code: str) -> list[dict]:
        """Obtiene los métodos de pago disponibles para un país."""
        payload = {
            "operationName": "getPaymentMethods",
            "variables": {
                "alpha2CountryCode": country_code,
            },
            "query": PAYMENT_METHODS_QUERY,
        }
        resp = self.session.post(GRAPHQL_URL, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        methods = data.get("data", {}).get("getPaymentMethods", {}).get("data", [])
        # Solo retornamos métodos válidos (con methodPaymentId definido)
        return [m for m in methods if m.get("methodPaymentId") is not None]

    async def _get_banks(self, country_code: str, method_payment_id: int) -> list[dict]:
        """Obtiene los bancos disponibles para un método de pago concreto."""
        payload = {
            "operationName": "getBanks",
            "variables": {
                "alpha2CountryCode": country_code,
                "methodPaymentId": method_payment_id,
            },
            "query": BANKS_QUERY,
        }
        resp = self.session.post(GRAPHQL_URL, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        banks = data.get("data", {}).get("getBanks", {}).get("data", [])
        return banks

    async def _get_cities(self, country_code: str) -> list[dict]:
        """Obtiene ciudades disponibles para retiro presencial (cash pickup)."""
        payload = {
            "operationName": "getCities",
            "variables": {
                "alpha2CountryCode": country_code,
            },
            "query": GET_CITIES_QUERY,
        }
        resp = self.session.post(GRAPHQL_URL, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        cities = data.get("data", {}).get("getCities", {}).get("data", [])
        return cities

    async def _get_feelookup(
        self,
        country_code: str,
        method_id: int = 1,
        amount: int = SEND_AMOUNT_CLP,
        payment_agent: str | None = None,
        receiver_city: str = "*",
    ) -> dict:
        """
        Ejecuta una cotización para un país con un método de dispersión.

        payment_agent replica el parámetro paymentAgent que envía la web
        (banco o wallet provider). receiver_city permite cotizar cash pickup
        por ciudad específica.
        """
        payload = {
            "operationName": "getFeelookup",
            "variables": {
                "variables": {
                    "amount": str(amount),
                    "originCurrency": "CLP",
                    "receiverCountry": country_code,
                    "receiverCity": receiver_city,
                    "includeFee": False,
                    "methodPaymentId": method_id,
                }
            },
            "query": FEELOOKUP_QUERY
        }

        # Agregar paymentAgent solo cuando aplique (depósitos / wallets)
        if payment_agent:
            payload["variables"]["variables"]["paymentAgent"] = payment_agent

        resp = self.session.post(GRAPHQL_URL, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    async def _get_collect_methods(self, feelookup_id: str, quote_id: int = 0) -> list[dict]:
        """Obtiene los métodos de pago disponibles."""
        payload = {
            "operationName": "getCollectMethods",
            "variables": {
                "feelookupId": feelookup_id,
                "quoteId": quote_id
            },
            "query": COLLECT_METHODS_QUERY
        }

        resp = self.session.post(GRAPHQL_URL, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        methods = data.get("data", {}).get("getCollectMethods", {}).get("data", [])
        return [m for m in methods if m.get("isEnabled")]

    async def scrape(self, destinations: list[dict], amount: int = None) -> list[QuoteResult]:
        """Ejecuta scraping de AFEX para todos los destinos."""
        self.amount = amount or SEND_AMOUNT_CLP
        results = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Authenticate
        await self._authenticate()

        # 2. Get available countries from AFEX
        available = await self._get_available_countries()
        available_codes = {c["code"] for c in available}
        logger.info(f"[AFEX] Países disponibles: {len(available_codes)}")

        # 3. Iterate destinations
        for dest in destinations:
            code = dest["country_code"]
            country_name = normalize_country(dest["country_name"], code)

            if code not in available_codes:
                logger.warning(f"[AFEX] País {country_name} ({code}) no disponible.")
                continue

            seen_agents = set()  # Avoid duplicate quotes for same agent+currency
            country_quotes = []

            # Descubrimos dinámicamente los métodos de pago disponibles
            try:
                payment_methods = await self._get_payment_methods(code)
            except Exception as e:
                logger.warning(f"[AFEX] No se pudieron obtener métodos de pago para {country_name}: {e}")
                payment_methods = []

            # Flags por tipo de método
            has_deposito = any(m.get("methodPaymentId") == 1 for m in payment_methods)
            has_wallet = any(m.get("methodPaymentId") == 4 for m in payment_methods)
            has_cash_pickup = any(m.get("methodPaymentId") == 0 for m in payment_methods)

            # Cache de métodos de pago por quoteId para evitar llamadas duplicadas
            collect_methods_cache: dict[int, list[dict]] = {}

            # --- 1) Depósito bancario (methodPaymentId=1) por banco/paymentAgent ---
            if has_deposito:
                try:
                    banks = await self._get_banks(code, method_payment_id=1)
                except Exception as e:
                    logger.warning(f"[AFEX] No se pudieron obtener bancos para {country_name}: {e}")
                    banks = []

                # Priorizamos bancos cuyo/algún agente viene marcado como suggested=1,
                # que son los mismos que usa la web por defecto. Si no hay ninguno,
                # usamos el listado completo como fallback.
                preferred_banks = [
                    b for b in banks
                    if any(a.get("suggested") for a in (b.get("agents") or []))
                ]
                banks_to_use = preferred_banks or banks

                # Limitamos el número de bancos a cotizar para evitar tiempos excesivos.
                # Debido a que deduplicamos por agente+moneda+método de dispersión, con
                # unos pocos bancos sugeridos ya descubrimos los agentes relevantes.
                for bank in banks_to_use[:MAX_BANKS_DEPOSITO]:
                    payment_agent = bank.get("id")
                    if not payment_agent:
                        continue

                    try:
                        logger.info(f"[AFEX] Cotizando {country_name} Depósito (banco {payment_agent})...")
                        data = await self._get_feelookup(
                            country_code=code,
                            method_id=1,
                            payment_agent=payment_agent,
                            receiver_city="*",
                        )
                    except Exception as e:
                        logger.error(f"[AFEX] Error {country_name} depósito banco {payment_agent}: {e}")
                        continue

                    feelookup = data.get("data", {}).get("getFeelookup", {})
                    if feelookup.get("status") != "success":
                        continue

                    feelookup_data = feelookup.get("data", {})
                    feelookup_id = feelookup_data.get("id", "")
                    quotes = feelookup_data.get("quotes", [])

                    if not quotes:
                        continue

                    for quote in quotes:
                        receive = quote.get("receive", {})
                        transfer = quote.get("transfer", {})
                        fees = quote.get("fees", {})
                        payment = quote.get("payment", {})

                        dest_currency = normalize_currency(receive.get("currency", ""))
                        delivery_method = receive.get("methodPayment", "N/D")
                        agency = receive.get("agency", "N/D")
                        agent_id = quote.get("agent", {}).get("id", "")

                        dedup_key = f"{agent_id}_{dest_currency}_{delivery_method}"
                        if dedup_key in seen_agents:
                            continue
                        seen_agents.add(dedup_key)

                        fee_total = fees.get("total", 0)
                        fee_suggested = fees.get("suggested", 0)
                        fee_base = fee_total
                        fee_tax = max(0, fee_suggested - fee_total)
                        total_charged = payment.get("amount", SEND_AMOUNT_CLP + fee_total)

                        conversion = quote.get("conversionInfo", {})
                        received = float(receive.get("amount", 0))
                        if (
                            conversion.get("targetCurrency") == "CLP"
                            and conversion.get("targetAmount")
                        ):
                            exchange_rate = float(conversion["targetAmount"])
                        elif received > 0:
                            exchange_rate = float(SEND_AMOUNT_CLP) / received
                        else:
                            exchange_rate = 0.0

                        quote_id = quote.get("id", 0) or 0
                        payment_method_names: list[str] = ["N/D"]

                        try:
                            if quote_id in collect_methods_cache:
                                methods = collect_methods_cache[quote_id]
                            else:
                                methods = await self._get_collect_methods(feelookup_id, quote_id=quote_id)
                                collect_methods_cache[quote_id] = methods

                            if methods:
                                payment_method_names = [m.get("name", "N/D") for m in methods]
                        except Exception as e:
                            logger.warning(
                                f"[AFEX] No se pudo obtener métodos de pago para quote {quote_id}: {e}"
                            )

                        for pm_name in payment_method_names:
                            dispersion_raw = f"{delivery_method} ({agency})"
                            country_quotes.append(
                                QuoteResult(
                                    timestamp=timestamp,
                                    agente="AFEX",
                                    pais_destino=country_name,
                                    moneda_origen="CLP",
                                    moneda_destino=dest_currency,
                                    monto_enviado=float(SEND_AMOUNT_CLP),
                                    monto_recibido=received,
                                    tasa_de_cambio=exchange_rate,
                                    fee_base=float(fee_base),
                                    fee_impuesto=float(fee_tax),
                                    total_cobrado=float(total_charged),
                                    metodo_recaudacion=pm_name,
                                    metodo_dispersion=dispersion_raw,
                                    categoria_recaudacion=normalize_metodo_recaudacion(pm_name),
                                    categoria_dispersion=normalize_metodo_dispersion(dispersion_raw),
                                )
                            )

            # --- 2) Wallets (methodPaymentId=4) por proveedor/banco ---
            if has_wallet:
                # En getPaymentMethods, las wallets específicas vienen con bank != null
                wallet_methods = [
                    m for m in payment_methods if m.get("methodPaymentId") == 4 and m.get("bank")
                ]

                for wm in wallet_methods:
                    bank = wm.get("bank") or {}
                    payment_agent = bank.get("id")
                    wallet_name = bank.get("name") or wm.get("methodPayment", "Wallet")
                    if not payment_agent:
                        continue

                    try:
                        logger.info(
                            f"[AFEX] Cotizando {country_name} Wallet ({wallet_name} / {payment_agent})..."
                        )
                        data = await self._get_feelookup(
                            country_code=code,
                            method_id=4,
                            payment_agent=payment_agent,
                            receiver_city="*",
                        )
                    except Exception as e:
                        logger.error(
                            f"[AFEX] Error {country_name} wallet {wallet_name} ({payment_agent}): {e}"
                        )
                        continue

                    feelookup = data.get("data", {}).get("getFeelookup", {})
                    if feelookup.get("status") != "success":
                        continue

                    feelookup_data = feelookup.get("data", {})
                    feelookup_id = feelookup_data.get("id", "")
                    quotes = feelookup_data.get("quotes", [])

                    if not quotes:
                        continue

                    for quote in quotes:
                        receive = quote.get("receive", {})
                        transfer = quote.get("transfer", {})
                        fees = quote.get("fees", {})
                        payment = quote.get("payment", {})

                        dest_currency = normalize_currency(receive.get("currency", ""))
                        delivery_method = receive.get("methodPayment", wallet_name)
                        agency = receive.get("agency", wallet_name)
                        agent_id = quote.get("agent", {}).get("id", "")

                        dedup_key = f"{agent_id}_{dest_currency}_{delivery_method}"
                        if dedup_key in seen_agents:
                            continue
                        seen_agents.add(dedup_key)

                        fee_total = fees.get("total", 0)
                        fee_suggested = fees.get("suggested", 0)
                        fee_base = fee_total
                        fee_tax = max(0, fee_suggested - fee_total)
                        total_charged = payment.get("amount", SEND_AMOUNT_CLP + fee_total)

                        conversion = quote.get("conversionInfo", {})
                        received = float(receive.get("amount", 0))
                        if (
                            conversion.get("targetCurrency") == "CLP"
                            and conversion.get("targetAmount")
                        ):
                            exchange_rate = float(conversion["targetAmount"])
                        elif received > 0:
                            exchange_rate = float(SEND_AMOUNT_CLP) / received
                        else:
                            exchange_rate = 0.0

                        quote_id = quote.get("id", 0) or 0
                        payment_method_names: list[str] = ["N/D"]

                        try:
                            if quote_id in collect_methods_cache:
                                methods = collect_methods_cache[quote_id]
                            else:
                                methods = await self._get_collect_methods(feelookup_id, quote_id=quote_id)
                                collect_methods_cache[quote_id] = methods

                            if methods:
                                payment_method_names = [m.get("name", "N/D") for m in methods]
                        except Exception as e:
                            logger.warning(
                                f"[AFEX] No se pudo obtener métodos de pago para quote {quote_id}: {e}"
                            )

                        for pm_name in payment_method_names:
                            dispersion_raw = f"{delivery_method} ({agency})"
                            country_quotes.append(
                                QuoteResult(
                                    timestamp=timestamp,
                                    agente="AFEX",
                                    pais_destino=country_name,
                                    moneda_origen="CLP",
                                    moneda_destino=dest_currency,
                                    monto_enviado=float(SEND_AMOUNT_CLP),
                                    monto_recibido=received,
                                    tasa_de_cambio=exchange_rate,
                                    fee_base=float(fee_base),
                                    fee_impuesto=float(fee_tax),
                                    total_cobrado=float(total_charged),
                                    metodo_recaudacion=pm_name,
                                    metodo_dispersion=dispersion_raw,
                                    categoria_recaudacion=normalize_metodo_recaudacion(pm_name),
                                    categoria_dispersion=normalize_metodo_dispersion(dispersion_raw),
                                )
                            )

            # --- 3) Cash pickup (methodPaymentId=0) explorando ciudades pero sin exponer ciudad ---
            if has_cash_pickup:
                try:
                    cities = await self._get_cities(code)
                except Exception as e:
                    logger.warning(f"[AFEX] No se pudieron obtener ciudades para {country_name}: {e}")
                    cities = []

                # Recorremos solo un subconjunto pequeño de ciudades para descubrir
                # agentes posibles sin volver el scraper demasiado lento. La ciudad
                # no entra en la clave de deduplicación.
                for city in cities[:MAX_CITIES_CASH_PICKUP]:
                    city_code = city.get("code") or "*"

                    try:
                        logger.info(
                            f"[AFEX] Cotizando {country_name} Cash Pickup ciudad {city_code}..."
                        )
                        data = await self._get_feelookup(
                            country_code=code,
                            method_id=0,
                            payment_agent=None,
                            receiver_city=city_code,
                        )
                    except Exception as e:
                        logger.error(
                            f"[AFEX] Error {country_name} cash pickup ciudad {city_code}: {e}"
                        )
                        continue

                    feelookup = data.get("data", {}).get("getFeelookup", {})
                    if feelookup.get("status") != "success":
                        continue

                    feelookup_data = feelookup.get("data", {})
                    feelookup_id = feelookup_data.get("id", "")
                    quotes = feelookup_data.get("quotes", []) or []

                    for quote in quotes:
                        receive = quote.get("receive", {})
                        transfer = quote.get("transfer", {})
                        fees = quote.get("fees", {})
                        payment = quote.get("payment", {})

                        dest_currency = normalize_currency(receive.get("currency", ""))
                        delivery_method = receive.get("methodPayment", "Retiro presencial")
                        agency = receive.get("agency", "N/D")
                        agent_id = quote.get("agent", {}).get("id", "")

                        # La ciudad NO entra en la clave, así consolidamos por agente+moneda+método.
                        dedup_key = f"{agent_id}_{dest_currency}_{delivery_method}"
                        if dedup_key in seen_agents:
                            continue
                        seen_agents.add(dedup_key)

                        fee_total = fees.get("total", 0)
                        fee_suggested = fees.get("suggested", 0)
                        fee_base = fee_total
                        fee_tax = max(0, fee_suggested - fee_total)
                        total_charged = payment.get("amount", SEND_AMOUNT_CLP + fee_total)

                        conversion = quote.get("conversionInfo", {})
                        received = float(receive.get("amount", 0))
                        if (
                            conversion.get("targetCurrency") == "CLP"
                            and conversion.get("targetAmount")
                        ):
                            exchange_rate = float(conversion["targetAmount"])
                        elif received > 0:
                            exchange_rate = float(SEND_AMOUNT_CLP) / received
                        else:
                            exchange_rate = 0.0

                        quote_id = quote.get("id", 0) or 0
                        payment_method_names: list[str] = ["N/D"]

                        try:
                            if quote_id in collect_methods_cache:
                                methods = collect_methods_cache[quote_id]
                            else:
                                methods = await self._get_collect_methods(
                                    feelookup_id, quote_id=quote_id
                                )
                                collect_methods_cache[quote_id] = methods

                            if methods:
                                payment_method_names = [m.get("name", "N/D") for m in methods]
                        except Exception as e:
                            logger.warning(
                                f"[AFEX] No se pudo obtener métodos de pago para quote {quote_id}: {e}"
                            )

                        for pm_name in payment_method_names:
                            dispersion_raw = f"{delivery_method} ({agency})"
                            country_quotes.append(
                                QuoteResult(
                                    timestamp=timestamp,
                                    agente="AFEX",
                                    pais_destino=country_name,
                                    moneda_origen="CLP",
                                    moneda_destino=dest_currency,
                                    monto_enviado=float(SEND_AMOUNT_CLP),
                                    monto_recibido=received,
                                    tasa_de_cambio=exchange_rate,
                                    fee_base=float(fee_base),
                                    fee_impuesto=float(fee_tax),
                                    total_cobrado=float(total_charged),
                                    metodo_recaudacion=pm_name,
                                    metodo_dispersion=dispersion_raw,
                                    categoria_recaudacion=normalize_metodo_recaudacion(pm_name),
                                    categoria_dispersion=normalize_metodo_dispersion(dispersion_raw),
                                )
                            )

            results.extend(country_quotes)
            if country_quotes:
                logger.info(f"[AFEX] {country_name}: {len(country_quotes)} resultados")
            else:
                logger.warning(f"[AFEX] {country_name}: sin cotizaciones en ningún método")

        logger.info(f"[AFEX] Total resultados: {len(results)}")
        return results

    async def close(self):
        self.session.close()

