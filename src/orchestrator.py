"""
Orquestador principal — ejecuta todos los scrapers y consolida resultados.
"""
import asyncio
import logging
import time
import requests
from datetime import datetime
from src.models import ScrapeRun
import os
from playwright.async_api import async_playwright
from src.scrapers.afex import AfexScraper
from src.scrapers.ria import RiaScraper
from src.scrapers.western_union import WesternUnionScraper
from src.config import DESTINATIONS, BROWSER_PROFILES_DIR

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

    shared_playwright = None
    shared_context = None
    
    if run_ria or run_wu:
        logger.info("=== Iniciando Contexto Compartido Único de Navegador ===")
        shared_playwright = await async_playwright().start()
        # Usamos la carpeta 'wu' porque contiene los cookies autorizados crudos que la nube lee
        profile_dir = os.path.join(BROWSER_PROFILES_DIR, "wu")
        os.makedirs(profile_dir, exist_ok=True)
        is_cloud = os.getenv("RENDER") == "true"
        
        ignored_default_args = [
            "--enable-automation",
            "--enable-blink-features=IdleDetection",
        ]
        if not is_cloud:
            ignored_default_args.append("--no-sandbox")

        shared_context = await shared_playwright.chromium.launch_persistent_context(
            profile_dir,
            headless=is_cloud,
            viewport={"width": 1280, "height": 800},
            locale="es-CL",
            timezone_id="America/Santiago",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            ignore_default_args=ignored_default_args,
            args=[
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1280,800",
            ]
        )

    scrapers = []
    if run_afex:
        scrapers.append(("AFEX", AfexScraper()))
    if run_ria:
        scrapers.append(("RIA", RiaScraper(shared_context=shared_context)))
    if run_wu:
        scrapers.append(("WU", WesternUnionScraper(shared_context=shared_context)))

    for name, scraper in scrapers:
        try:
            logger.info(f"=== Ejecutando scraper {name} ===")
            results = await scraper.scrape(DESTINATIONS)
            
            # Inject market rates, uniform timestamp and calculate markup
            for r in results:
                # Unificar timestamp para agrupar todas las remesadoras bajo una sola consulta
                r.timestamp = scrape_run.timestamp
                
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

    if shared_context:
        try:
            await shared_context.close()
        except Exception:
            pass
    if shared_playwright:
        try:
            await shared_playwright.stop()
        except Exception:
            pass

    scrape_run.duration_seconds = round(time.time() - start_time, 2)
    scrape_run.total_quotes = len(scrape_run.results)

    logger.info(
        f"=== Scraping completado: {scrape_run.total_quotes} cotizaciones "
        f"en {scrape_run.duration_seconds}s ({len(scrape_run.errors)} errores) ==="
    )

    return scrape_run
