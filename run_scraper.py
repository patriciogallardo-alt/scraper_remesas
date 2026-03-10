"""
Script principal para ejecutar el scraping de remesas.
Uso: python run_scraper.py [--afex] [--ria] [--wu] [--all]
"""
import asyncio
import argparse
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Scraper de Remesas - RIA, WU, AFEX")
    parser.add_argument("--afex", action="store_true", help="Solo ejecutar AFEX")
    parser.add_argument("--ria", action="store_true", help="Solo ejecutar RIA")
    parser.add_argument("--wu", action="store_true", help="Solo ejecutar Western Union")
    parser.add_argument("--all", action="store_true", help="Ejecutar todos (default)")
    args = parser.parse_args()

    # If no specific scraper is selected, run all
    run_all = args.all or not (args.afex or args.ria or args.wu)

    from src.orchestrator import run_all_scrapers
    from src.exporter import export_to_excel, save_json

    logger.info("=" * 60)
    logger.info("  SCRAPER DE REMESAS - Iniciando")
    logger.info("=" * 60)

    scrape_run = await run_all_scrapers(
        run_afex=run_all or args.afex,
        run_ria=run_all or args.ria,
        run_wu=run_all or args.wu,
    )

    # Save results
    if scrape_run.results:
        json_path = save_json(scrape_run)
        xlsx_path = export_to_excel(scrape_run)
        logger.info(f"Resultados guardados:")
        logger.info(f"  JSON: {json_path}")
        logger.info(f"  Excel: {xlsx_path}")
    else:
        logger.warning("No se obtuvieron resultados.")

    # Print summary
    logger.info(f"\n{'=' * 60}")
    logger.info(f"  RESUMEN")
    logger.info(f"  Total cotizaciones: {scrape_run.total_quotes}")
    logger.info(f"  Duración: {scrape_run.duration_seconds}s")
    logger.info(f"  Errores: {len(scrape_run.errors)}")
    if scrape_run.errors:
        for err in scrape_run.errors:
            logger.info(f"    - {err}")
    logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
