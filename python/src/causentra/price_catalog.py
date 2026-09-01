"""Explicit, versioned local model-price catalogs with deterministic lookup."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .model import normalize_provider_name
from .types import EventAttributes


@dataclass(frozen=True, slots=True)
class ModelPriceRate:
    """One provider/model rate in integer microdollars per million tokens."""

    provider_name: str
    model: str
    effective_from: date
    input_microusd_per_million: int
    output_microusd_per_million: int
    cache_read_input_microusd_per_million: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_name", normalize_provider_name(self.provider_name))
        if not self.model.strip() or len(self.model) > 256:
            raise ValueError("model must be non-empty and at most 256 characters")
        if not isinstance(self.effective_from, date):
            raise ValueError("effective_from must be a date")
        for name in (
            "input_microusd_per_million",
            "output_microusd_per_million",
            "cache_read_input_microusd_per_million",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class CatalogCostEstimate:
    catalog_version: str
    provider_name: str
    model: str
    effective_from: date
    cost_microusd: int

    @property
    def cost_usd(self) -> float:
        return self.cost_microusd / 1_000_000

    def attributes(self) -> EventAttributes:
        return {
            "causentra.cost.usd": self.cost_usd,
            "causentra.cost.basis": "catalog_estimate",
            "causentra.cost.catalog.version": self.catalog_version,
            "causentra.cost.catalog.effective_from": self.effective_from.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class PriceCatalog:
    """A caller-supplied immutable catalog; it never performs remote lookups."""

    version: str
    rates: tuple[ModelPriceRate, ...]

    def __post_init__(self) -> None:
        if not self.version or len(self.version) > 128:
            raise ValueError("catalog version must be non-empty and at most 128 characters")
        seen = {(rate.provider_name, rate.model, rate.effective_from) for rate in self.rates}
        if len(seen) != len(self.rates):
            raise ValueError("catalog rate provider/model/effective_from values must be unique")

    def estimate(
        self,
        *,
        provider_name: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        on: date | None = None,
    ) -> CatalogCostEstimate | None:
        """Return ``None`` for unknown models or rates, never a guessed price."""

        for name, value in (
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
            ("cache_read_input_tokens", cache_read_input_tokens),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not model.strip() or len(model) > 256:
            raise ValueError("model must be non-empty and at most 256 characters")
        effective_on = on or date.today()
        if not isinstance(effective_on, date):
            raise ValueError("on must be a date")
        provider = normalize_provider_name(provider_name)
        applicable = [
            rate
            for rate in self.rates
            if rate.provider_name == provider
            and rate.model == model
            and rate.effective_from <= effective_on
        ]
        if not applicable:
            return None
        rate = max(applicable, key=lambda candidate: candidate.effective_from)
        if cache_read_input_tokens and rate.cache_read_input_microusd_per_million is None:
            return None
        total = (
            input_tokens * rate.input_microusd_per_million
            + output_tokens * rate.output_microusd_per_million
            + cache_read_input_tokens * (rate.cache_read_input_microusd_per_million or 0)
        )
        # Preserve exact integer microdollars; truncation is deterministic and visible.
        return CatalogCostEstimate(
            self.version,
            provider,
            model,
            rate.effective_from,
            total // 1_000_000,
        )
