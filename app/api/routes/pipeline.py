"""Pipeline routes — trigger a data refresh (money-mutating guard)."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app.api.dependencies import (
    get_alerts_repository,
    get_integration_config_service,
    get_pipeline_service,
    get_portfolio_service,
    get_trader_service,
)
from app.api.templating import templates
from app.api.watchlist_context import build_watchlist_context
from app.core.security import require_local_or_token
from app.repositories.alerts_repo import AlertsRepository
from app.services.capability_checks import (
    missing_capability_warnings,
    warnings_fingerprint,
)
from app.services.integration_config_service import IntegrationConfigService
from app.services.pipeline_service import PipelineService
from app.services.portfolio_service import PortfolioService
from app.services.trader_service import TraderService

router = APIRouter()

TraderDep = Annotated[TraderService, Depends(get_trader_service)]
PortfolioDep = Annotated[PortfolioService, Depends(get_portfolio_service)]
PipelineDep = Annotated[PipelineService, Depends(get_pipeline_service)]
AlertsDep = Annotated[AlertsRepository, Depends(get_alerts_repository)]
ConfigDep = Annotated[IntegrationConfigService, Depends(get_integration_config_service)]


@router.get("/pipeline-status", response_class=HTMLResponse)
async def pipeline_status(request: Request) -> HTMLResponse:
    """Render the bottom status bar without blocking a running refresh."""
    return templates.TemplateResponse(
        request, "_pipeline_status.html", {"status": PipelineService.status()}
    )


@router.post(
    "/refresh-data",
    response_class=HTMLResponse,
    dependencies=[Depends(require_local_or_token)],
)
async def refresh_data(
    request: Request,
    trader: TraderDep,
    portfolio: PortfolioDep,
    pipeline: PipelineDep,
    alerts: AlertsDep,
    config: ConfigDep,
    confirm_missing: bool = Form(False),
    confirmed_fingerprint: str = Form(""),
) -> HTMLResponse:
    """Refresh the analysis dataset by running the pipeline once.

    Preflight is re-evaluated from live configuration on every call rather
    than trusted from the browser (#45): a confirmation is only honored if
    ``confirmed_fingerprint`` matches the fingerprint of *currently* missing
    capabilities, so a stale dialog (or a value replayed after new warnings
    appeared) falls back to a freshly rendered dialog instead of bypassing
    it. If every capability is now configured, confirmation is moot and the
    run proceeds regardless of what was posted.
    """
    warnings = missing_capability_warnings(config)
    if warnings:
        current_fingerprint = warnings_fingerprint(warnings)
        if not confirm_missing or confirmed_fingerprint != current_fingerprint:
            response = templates.TemplateResponse(
                request,
                "_pipeline_confirmation.html",
                context={"warnings": warnings, "fingerprint": current_fingerprint},
            )
            response.headers["HX-Retarget"] = "#pipeline-confirmation"
            response.headers["HX-Reswap"] = "innerHTML"
            response.headers["Cache-Control"] = "no-store"
            return response
    result = await asyncio.to_thread(pipeline.run_once)
    refresh_status = (
        "Data refreshed successfully" if result.success else "Data refresh failed"
    )
    return templates.TemplateResponse(
        request,
        "_watchlist.html",
        context=build_watchlist_context(
            trader,
            portfolio,
            alerts,
            refresh_status=refresh_status,
            refresh_success=result.success,
            refresh_details="" if result.success else result.details,
            refresh_stages=(
                [
                    "Sources and market data collected",
                    "Stocks analysed and scored",
                    "Alerts, history, and exports updated",
                ]
                if result.success
                else []
            ),
        ),
    )
