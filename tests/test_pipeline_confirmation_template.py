"""Template-level accessibility checks for the confirmation dialog (#45)."""

from __future__ import annotations

from app.api.templating import templates
from app.schemas.capability_warning import (
    CapabilityCategory,
    CapabilitySeverity,
    CapabilityWarning,
)

_WARNING = CapabilityWarning(
    capability_id="fmp_vcp_screener",
    category=CapabilityCategory.ANALYTICAL_COVERAGE,
    severity=CapabilitySeverity.CRITICAL,
    title="FMP API key",
    impact="The S&P 500 VCP screener will be skipped.",
    required_env_keys=("FMP_API_KEY",),
)


def _render(**overrides) -> str:
    context = {"warnings": [_WARNING], "fingerprint": "abc123"}
    context.update(overrides)
    return templates.get_template("_pipeline_confirmation.html").render(**context)


def test_dialog_is_labelled_and_marked_modal() -> None:
    html = _render()
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-labelledby="pipelineConfirmationTitle"' in html
    assert 'id="pipelineConfirmationTitle"' in html


def test_dialog_offers_the_three_required_actions() -> None:
    html = _render()
    assert "Configure integrations" in html
    assert "Continue with partial refresh" in html
    assert 'id="pipelineConfirmationCancel"' in html
    assert 'data-bs-dismiss="modal"' in html


def test_cancel_button_performs_no_mutation() -> None:
    html = _render()
    cancel_start = html.index('id="pipelineConfirmationCancel"')
    cancel_tag = html[max(0, cancel_start - 200) : cancel_start + 50]
    assert "hx-post" not in cancel_tag
    assert "hx-get" not in cancel_tag


def test_configure_integrations_targets_settings_without_starting_pipeline() -> None:
    html = _render()
    assert 'hx-get="/partials/settings"' in html
    assert '"/refresh-data"' not in html.split('hx-get="/partials/settings"')[0][-200:]


def test_continue_button_posts_confirmation_bound_to_fingerprint() -> None:
    html = _render()
    assert 'hx-post="/refresh-data"' in html
    assert '"confirm_missing": true' in html
    assert '"confirmed_fingerprint": "abc123"' in html


def test_focus_management_script_focuses_cancel_and_cleans_up_on_hide() -> None:
    html = _render()
    assert "shown.bs.modal" in html
    assert "pipelineConfirmationCancel" in html.split("shown.bs.modal", 1)[1][:300]
    assert "hidden.bs.modal" in html
    assert "modal-backdrop" in html


def test_warnings_render_with_category_and_severity_class() -> None:
    html = _render()
    assert "pipeline-warning-critical" in html
    assert "Analytical coverage" in html
    assert "FMP API key" in html
    assert "S&amp;P 500 VCP screener" in html or "S&P 500 VCP screener" in html
