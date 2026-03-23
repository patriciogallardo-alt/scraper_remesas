"""
Modelos de datos para el scraper de remesas.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
import json


@dataclass
class QuoteResult:
    """Resultado de una cotización de remesa."""
    timestamp: str
    agente: str              # Proveedor: "RIA", "Western Union", "AFEX"
    pais_destino: str        # Nombre del país: "Perú", "Colombia", etc.
    moneda_origen: str       # Siempre "CLP"
    moneda_destino: str      # "PEN", "USD", "COP", etc.
    monto_enviado: float     # Monto base en CLP (100,000)
    monto_recibido: float    # Lo que recibe el destinatario
    tasa_de_cambio: float    # Exchange rate proporcionado por el proveedor (puede venir en distintos formatos)
    fee_base: float          # Fee del proveedor en CLP (sin impuesto)
    fee_impuesto: float      # Impuesto sobre el fee en CLP
    total_cobrado: float     # Total cobrado al emisor en CLP
    metodo_recaudacion: str  # Valor original del proveedor
    metodo_dispersion: str   # Valor original del proveedor
    categoria_recaudacion: str = ""  # Categoría normalizada: Transferencia Bancaria, Tarjeta, etc.
    categoria_dispersion: str = ""   # Categoría normalizada: Depósito Bancario, Retiro en Efectivo, etc.
    tasa_cambio_normalizada: float = 0.0  # CLP / 1 unidad de moneda destino, calculado como monto_enviado / monto_recibido
    tasa_cambio_final: float = 0.0  # CLP total cobrado / 1 unidad de moneda destino, calculado como total_cobrado / monto_recibido
    tasa_mercado_clp: float = 0.0    # Tasa real (mid-market) desde una API pública (ej. CLP/PEN)
    markup_porcentaje: float = 0.0   # Porcentaje de sobreprecio vs el mercado: ((tasa_final / tasa_mercado) - 1) * 100

    def __post_init__(self):
        """
        Calcula una tasa de cambio normalizada siempre como:
        CLP enviados / monto recibido en moneda extranjera.
        Esto permite comparar directamente entre proveedores sin importar
        cómo venga expresada la tasa original.
        """
        try:
            if (self.tasa_cambio_normalizada in (0, None)) and self.monto_recibido:
                self.tasa_cambio_normalizada = float(self.monto_enviado) / float(self.monto_recibido)
        except Exception:
            # Si por alguna razón el cálculo falla, dejamos 0.0 como valor neutro
            self.tasa_cambio_normalizada = 0.0

        try:
            if (self.tasa_cambio_final in (0, None)) and self.monto_recibido:
                self.tasa_cambio_final = float(self.total_cobrado) / float(self.monto_recibido)
        except Exception:
            self.tasa_cambio_final = 0.0

        try:
            if self.tasa_mercado_clp > 0 and self.tasa_cambio_final > 0:
                self.markup_porcentaje = ((self.tasa_cambio_final / self.tasa_mercado_clp) - 1.0) * 100.0
        except Exception:
            self.markup_porcentaje = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def csv_headers() -> list[str]:
        return [
            "Timestamp", "Agente", "Método Dispersión",
            "Categoría Recaudación", "Categoría Dispersión",
            "País Destino", "Moneda Origen", "Moneda Destino",
            "Monto Enviado (CLP)", "Monto Dispersado (ME)",
            "Tasa de Cambio (Proveedor)", "TC Normalizado (CLP/ME)", "TC final",
            "TC Mercado Libre", "Markup (%)",
            "Fee Base (CLP)", "Fee Impuesto (CLP)", "Total Cobrado (CLP)",
            "Método Recaudación"
        ]

    def to_row(self) -> list:
        return [
            self.timestamp, self.agente, self.metodo_dispersion,
            self.categoria_recaudacion, self.categoria_dispersion,
            self.pais_destino, self.moneda_origen, self.moneda_destino,
            self.monto_enviado, self.monto_recibido,
            self.tasa_de_cambio, self.tasa_cambio_normalizada, self.tasa_cambio_final,
            self.tasa_mercado_clp, self.markup_porcentaje,
            self.fee_base, self.fee_impuesto, self.total_cobrado,
            self.metodo_recaudacion
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
