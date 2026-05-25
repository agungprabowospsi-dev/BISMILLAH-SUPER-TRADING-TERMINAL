from app.core.money_maker import analyze_money_maker_context
from app.core.money_maker_store import get_latest_flow_snapshot_cloud, save_money_maker_cloud
from app.engines.base_engine import BaseEngine, EngineResult


class MoneyMakerCoreEngine(BaseEngine):
    def __init__(self):
        super().__init__("MoneyMakerCoreEngine")

    async def analyze(self, ticker: str, ohlcv: list, mode: str, **kwargs) -> EngineResult:
        try:
            previous_snapshot = await get_latest_flow_snapshot_cloud(ticker, mode)
            context = analyze_money_maker_context(
                ticker=ticker,
                mode=mode,
                ohlcv=ohlcv,
                engine_result={"composite_score": kwargs.get("composite_score", 50)},
                broker_summary=kwargs.get("broker_summary_raw") or kwargs.get("broker_data_raw") or [],
                orderbook=kwargs.get("orderbook") or {},
                official_enrichment=kwargs.get("official_enrichment") or {},
                bandarmology=kwargs.get("bandarmology") or {},
                foreign_flow=kwargs.get("foreign_data") or {},
                previous_snapshot=previous_snapshot,
            )
            persist = await save_money_maker_cloud(context)
            context.setdefault("flow_memory", {})["cloud_saved"] = bool(persist.get("saved"))
            context["flow_memory"]["persistent_backend"] = persist.get("persistent_backend", "sqlite")
            score = context.get("score", 50.0)
            verdict = context.get("verdict", "NO_CLEAR_FLOW")
            phase = context.get("phase", "no_clear_flow")
            bfd = context.get("bfd_score", 0)
            patterns = ", ".join([p.get("name", "") for p in context.get("patterns", [])[:3] if isinstance(p, dict) and p.get("name")])
            rationale = (
                f"Money Maker Core {verdict}: phase {phase}, BFD {bfd}/5, "
                f"score {score:.0f}. Patterns: {patterns or 'none'}. "
                f"Evidence: {', '.join(context.get('evidence', [])[:4]) or 'limited'}."
            )
            return EngineResult(
                engine_name=self.name,
                score=score,
                signal=self._signal_from_score(score),
                confidence=85.0 if context.get("broker", {}).get("available") or context.get("orderbook", {}).get("available") else 55.0,
                rationale=rationale,
                data=context,
            )
        except Exception as exc:
            return self._safe_result(str(exc))
