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
    normalize_country, normalize_currency, REQUEST_TIMEOUT
)

logger = logging.getLogger(__name__)

# --- AFEX Connect endpoints (descubiertos del HAR) ---
PUBLIC_URL = "https://hasacv5rf9.execute-api.us-east-1.amazonaws.com/prod/v1/public"
PUBLIC_API_KEY = "lVyB8gmrhKIw7BZUkqJYAqCHAp6Pnl3zEWnM4Pi0"
SIGNIN_URL = "https://0hgu1h4p88.execute-api.us-east-2.amazonaws.com/prod/afex-client-api-key"
GRAPHQL_URL = "https://jmpw2xetb3.execute-api.us-east-2.amazonaws.com/prod/"

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

    async def _get_feelookup(self, country_code: str, method_id: int = 1,
                              amount: int = SEND_AMOUNT_CLP) -> dict:
        """Ejecuta una cotización para un país con un método de dispersión."""
        payload = {
            "operationName": "getFeelookup",
            "variables": {
                "variables": {
                    "amount": str(amount),
                    "originCurrency": "CLP",
                    "receiverCountry": country_code,
                    "receiverCity": "*",
                    "includeFee": False,
                    "methodPaymentId": method_id,
                }
            },
            "query": FEELOOKUP_QUERY
        }

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

    async def scrape(self, destinations: list[dict]) -> list[QuoteResult]:
        """Ejecuta scraping de AFEX para todos los destinos."""
        results = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Delivery method IDs to try (discovered from HAR)
        # 1 = Banco/Depósito, 2 = Cash Pickup, 4 = Wallet
        METHOD_IDS = [1, 4, 2]

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

            for method_id in METHOD_IDS:
                try:
                    logger.info(f"[AFEX] Cotizando {country_name} (método {method_id})...")
                    data = await self._get_feelookup(code, method_id=method_id)

                    feelookup = data.get("data", {}).get("getFeelookup", {})
                    if feelookup.get("status") != "success":
                        continue

                    feelookup_data = feelookup.get("data", {})
                    feelookup_id = feelookup_data.get("id", "")
                    quotes = feelookup_data.get("quotes", [])

                    if not quotes:
                        continue

                    # Get collect (payment) methods for the first quote
                    collect_methods = []
                    try:
                        collect_methods = await self._get_collect_methods(feelookup_id)
                    except Exception as e:
                        logger.warning(f"[AFEX] No se pudo obtener métodos de pago: {e}")

                    payment_method_names = (
                        [m["name"] for m in collect_methods] if collect_methods else ["N/D"]
                    )

                    # Map each quote to QuoteResult
                    for quote in quotes:
                        receive = quote.get("receive", {})
                        transfer = quote.get("transfer", {})
                        fees = quote.get("fees", {})
                        payment = quote.get("payment", {})

                        dest_currency = normalize_currency(receive.get("currency", ""))
                        delivery_method = receive.get("methodPayment", "N/D")
                        agency = receive.get("agency", "N/D")
                        agent_id = quote.get("agent", {}).get("id", "")

                        # Dedup key: agent + currency + delivery method
                        dedup_key = f"{agent_id}_{dest_currency}_{delivery_method}"
                        if dedup_key in seen_agents:
                            continue
                        seen_agents.add(dedup_key)

                        fee_total = fees.get("total", 0)
                        fee_suggested = fees.get("suggested", 0)
                        fee_base = fee_total
                        fee_tax = max(0, fee_suggested - fee_total)
                        total_charged = payment.get("amount", SEND_AMOUNT_CLP + fee_total)

                        # Exchange rate: use conversionInfo (1 dest = X CLP)
                        # or compute from amounts if unavailable
                        conversion = quote.get("conversionInfo", {})
                        received = float(receive.get("amount", 0))
                        if (conversion.get("targetCurrency") == "CLP"
                                and conversion.get("targetAmount")):
                            # conversionInfo gives "1 PEN = 268.11 CLP" directly
                            exchange_rate = float(conversion["targetAmount"])
                        elif received > 0:
                            # Fallback: compute CLP per 1 dest unit
                            exchange_rate = float(SEND_AMOUNT_CLP) / received
                        else:
                            exchange_rate = 0.0

                        for pm_name in payment_method_names:
                            country_quotes.append(QuoteResult(
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
                                metodo_dispersion=f"{delivery_method} ({agency})",
                            ))

                except Exception as e:
                    logger.error(f"[AFEX] Error {country_name} método {method_id}: {e}")
                    continue

            results.extend(country_quotes)
            if country_quotes:
                logger.info(f"[AFEX] {country_name}: {len(country_quotes)} resultados")
            else:
                logger.warning(f"[AFEX] {country_name}: sin cotizaciones en ningún método")

        logger.info(f"[AFEX] Total resultados: {len(results)}")
        return results

    async def close(self):
        self.session.close()

