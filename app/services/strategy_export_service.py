from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List
import csv

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.strategy import StrategyRun


class StrategyExportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.base_dir = Path(settings.EXPORT_ROOT).expanduser().resolve()
        self.dir = self.base_dir / "strategy_runs"
        self.dir.mkdir(parents=True, exist_ok=True)

    async def export_run_to_csv(self, run_id: str) -> dict[str, str]:
        stmt = (
            select(StrategyRun)
            .options(selectinload(StrategyRun.assets))
            .where(StrategyRun.id == run_id)
        )
        res = await self.session.execute(stmt)
        run = res.scalars().first()
        if not run:
            raise ValueError("Strategy run not found")

        assets = run.assets or []
        if not assets and run.history and run.history.assets:
            assets = run.history.assets

        if not assets:
            raise ValueError("No assets found for export")

        file_path = self.dir / f"strategy_run_{run.id}.csv"
        self._write_assets_to_csv(assets, file_path)
        return {
            "file_path": str(file_path),
            "download_url": f"/exports/strategy_runs/{file_path.name}",
        }

    @staticmethod
    def _asset_to_row(asset: Any) -> List[str]:
        if hasattr(asset, "symbol"):
            symbol = asset.symbol
            strength = getattr(asset, "signal_strength", None)
            weight = getattr(asset, "weight", None)
            risk_flags = getattr(asset, "risk_flags", []) or []
            notes = getattr(asset, "notes", "") or ""
            signal_dimensions = getattr(asset, "signal_dimensions", {}) or {}
        else:
            symbol = asset.get("symbol")
            strength = asset.get("signal_strength")
            weight = asset.get("weight")
            risk_flags = asset.get("risk_flags") or []
            notes = asset.get("notes") or ""
            signal_dimensions = asset.get("signal_dimensions") or {}
        return [
            symbol,
            f"{strength:.2f}" if isinstance(strength, float) else str(strength or ""),
            f"{weight:.3f}" if isinstance(weight, float) else str(weight or ""),
            ";".join(risk_flags) if isinstance(risk_flags, Iterable) else str(risk_flags),
            notes,
            signal_dimensions.get("momentum", ""),
            signal_dimensions.get("volume", ""),
            signal_dimensions.get("sentiment", ""),
        ]

    def _write_assets_to_csv(self, assets: Iterable[Any], path: Path) -> None:
        headers = ["symbol", "strength", "weight", "risk_flags", "notes", "momentum", "volume", "sentiment"]
        with path.open("w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(headers)
            for asset in assets:
                writer.writerow(self._asset_to_row(asset))
