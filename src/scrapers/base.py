"""
Clase base abstracta para scrapers de remesas.
"""
import logging
import time
from abc import ABC, abstractmethod
from src.models import QuoteResult

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Clase base para todos los scrapers de remesas."""

    name: str = "Base"

    @abstractmethod
    async def scrape(self, destinations: list[dict]) -> list[QuoteResult]:
        """
        Ejecuta el scraping para todos los destinos dados.
        
        Args:
            destinations: Lista de dicts con country_code, country_name, local_currency
            
        Returns:
            Lista de QuoteResult con todas las cotizaciones encontradas
        """
        pass

    @abstractmethod
    async def close(self):
        """Limpia recursos (browser, sesiones, etc.)."""
        pass

    def _retry(self, func, *args, max_retries=3, delay=5, **kwargs):
        """Ejecuta func con reintentos."""
        last_error = None
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                logger.warning(
                    f"[{self.name}] Intento {attempt+1}/{max_retries} falló: {e}"
                )
                if attempt < max_retries - 1:
                    time.sleep(delay)
        raise last_error
