"""
Orquestador principal — ejecuta todos los scrapers y consolida resultados.
"""
import asyncio
import logging
import time
import requests
from datetime import datetime
from src.models import ScrapeRun
from src.config import DESTINATIONS
from src.scrapers.afex import AfexScraper
from src.scrapers.ria import RiaScraper
from src.scrapers.western_union import WesternUnionScraper

logger = logging.getLogger(__name__)


async def run_all_scrapers(
    run_afex: bool = True,
    run_ria: bool = True,
    run_wu: bool = True
) -> ScrapeRun:
    """
    Ejecuta los scrapers seleccionados y consolida resultados.
    AFEX primero (más rápido, sin browser), luego RIA, luego WU.
    """
    scrape_run = ScrapeRun(timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    start_time = time.time()

    # 1. Obtener tasas de mercado en vivo
    market_rates = {}
    try:
        logger.info("=== Obteniendo tasas de mercado base (CLP) ===")
        resp = requests.get("https://open.er-api.com/v6/latest/CLP", timeout=10)
        if resp.status_code == 200:
            market_rates = resp.json().get("rates", {})
    except Exception as e:
        logger.error(f"Error obteniendo tasas de mercado: {e}")

    scrapers = []
    if run_afex:
        scrapers.append(("AFEX", AfexScraper()))
    if run_ria:
        scrapers.append(("RIA", RiaScraper()))
    if run_wu:
        scrapers.append(("WU", WesternUnionScraper()))

    for name, scraper in scrapers:
        try:
            logger.info(f"=== Ejecutando scraper {name} ===")
            results = await scraper.scrape(DESTINATIONS)
            
            # Inject market rates and calculate markup
            for r in results:
                if r.moneda_destino in market_rates:
                    # La API da: 1 CLP = X Moneda Destino. 
                    # Nuestra tasa es: CLP / 1 Moneda Destino, así que invertimos
                    r.tasa_mercado_clp = 1.0 / market_rates[r.moneda_destino]
                    # Volver a llamar _post_init manualmente para setear el markup_porcentaje
                    r.__post_init__()
                    
            scrape_run.results.extend(results)
            logger.info(f"=== {name}: {len(results)} resultados ===")
        except Exception as e:
            error_msg = f"Error en scraper {name}: {str(e)}"
            logger.error(error_msg)
            scrape_run.errors.append(error_msg)
        finally:
            try:
                await scraper.close()
            except Exception:
                pass

    scrape_run.duration_seconds = round(time.time() - start_time, 2)
    scrape_run.total_quotes = len(scrape_run.results)

    logger.info(
        f"=== Scraping completado: {scrape_run.total_quotes} cotizaciones "
        f"en {scrape_run.duration_seconds}s ({len(scrape_run.errors)} errores) ==="
    )

    return scrape_run
