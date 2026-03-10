"""
Modelos de datos para el scraper de remesas.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
import json


@dataclass
class QuoteResult:
    """Resultado de una cotización de remesa — 13 campos requeridos."""
    timestamp: str
    agente: str              # Proveedor: "RIA", "Western Union", "AFEX"
    pais_destino: str        # Nombre del país: "Perú", "Colombia", etc.
    moneda_origen: str       # Siempre "CLP"
    moneda_destino: str      # "PEN", "USD", "COP", etc.
    monto_enviado: float     # Monto base en CLP (100,000)
    monto_recibido: float    # Lo que recibe el destinatario
    tasa_de_cambio: float    # Exchange rate aplicado
    fee_base: float          # Fee del proveedor en CLP (sin impuesto)
    fee_impuesto: float      # Impuesto sobre el fee en CLP
    total_cobrado: float     # Total cobrado al emisor en CLP
    metodo_recaudacion: str  # Cómo paga el emisor: "Banco directo", "Webpay", etc.
    metodo_dispersion: str   # Cómo recibe el destinatario: "BankDeposit", "Cash", etc.

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def csv_headers() -> list[str]:
        return [
            "Timestamp", "Agente", "País Destino", "Moneda Origen",
            "Moneda Destino", "Monto Enviado (CLP)", "Monto Recibido",
            "Tasa de Cambio", "Fee Base (CLP)", "Fee Impuesto (CLP)",
            "Total Cobrado (CLP)", "Método Recaudación", "Método Dispersión"
        ]

    def to_row(self) -> list:
        return [
            self.timestamp, self.agente, self.pais_destino, self.moneda_origen,
            self.moneda_destino, self.monto_enviado, self.monto_recibido,
            self.tasa_de_cambio, self.fee_base, self.fee_impuesto,
            self.total_cobrado, self.metodo_recaudacion, self.metodo_dispersion
        ]


@dataclass
class ScrapeRun:
    """Metadata de una ejecución completa de scraping."""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    duration_seconds: float = 0.0
    total_quotes: int = 0
    errors: list[str] = field(default_factory=list)
    results: list[QuoteResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "total_quotes": self.total_quotes,
            "errors": self.errors,
            "results": [r.to_dict() for r in self.results]
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
