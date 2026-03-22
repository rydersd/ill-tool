"""Pydantic input models for all Adobe MCP tools.

Backward-compatibility facade: re-exports from apps/*/models.py so callers can do:
    from adobe_mcp.models import PsLayerInput, AiShapeInput
"""

from adobe_mcp.apps.common.models import (
    AppStatusInput,
    BatchInput,
    CloseDocInput,
    ContextInput,
    DesignTokenInput,
    GetDocInfoInput,
    HealthCheckInput,
    LaunchAppInput,
    ListFontsInput,
    OpenFileInput,
    PipelineInput,
    PreviewInput,
    RunJSXFileInput,
    RunJSXInput,
    RunPowerShellInput,
    SaveFileInput,
    SessionStateInput,
    SnippetInput,
    ToolDiscoveryInput,
    WorkflowInput,
)
from adobe_mcp.apps.photoshop.models import (
    PsActionInput,
    PsAdjustmentInput,
    PsBatchInput,
    PsExportInput,
    PsFilterInput,
    PsGroupInput,
    PsInspectInput,
    PsLayerInput,
    PsNewDocInput,
    PsSelectionInput,
    PsSmartObjectInput,
    PsTextInput,
    PsTransformInput,
)
from adobe_mcp.apps.illustrator.models import (
    AiExportInput,
    AiInspectInput,
    AiLayerInput,
    AiModifyInput,
    AiNewDocInput,
    AiPathInput,
    AiShapeInput,
    AiTextInput,
)
from adobe_mcp.apps.premiere.models import (
    PrEffectInput,
    PrExportInput,
    PrMediaInput,
    PrProjectInput,
    PrSequenceInput,
    PrTimelineInput,
)
from adobe_mcp.apps.aftereffects.models import (
    AeCompInput,
    AeEffectInput,
    AeExpressionInput,
    AeLayerInput,
    AePropertyInput,
    AeRenderInput,
)
from adobe_mcp.apps.indesign.models import (
    IdDocInput,
    IdImageInput,
    IdTextInput,
)
from adobe_mcp.apps.animate.models import (
    AnDocInput,
    AnTimelineInput,
)
from adobe_mcp.apps.media_encoder.models import (
    AmeEncodeInput,
)

__all__ = [
    # Common
    "AppStatusInput", "RunJSXInput", "RunJSXFileInput", "LaunchAppInput",
    "OpenFileInput", "SaveFileInput", "CloseDocInput", "RunPowerShellInput",
    "GetDocInfoInput", "ListFontsInput", "PreviewInput", "SessionStateInput",
    "BatchInput", "WorkflowInput", "PipelineInput", "ToolDiscoveryInput",
    "SnippetInput", "ContextInput", "HealthCheckInput", "DesignTokenInput",
    # Photoshop
    "PsNewDocInput", "PsLayerInput", "PsFilterInput", "PsSelectionInput",
    "PsTransformInput", "PsAdjustmentInput", "PsTextInput", "PsExportInput",
    "PsBatchInput", "PsActionInput", "PsSmartObjectInput",
    "PsInspectInput", "PsGroupInput",
    # Illustrator
    "AiNewDocInput", "AiShapeInput", "AiTextInput", "AiPathInput", "AiExportInput",
    "AiInspectInput", "AiModifyInput", "AiLayerInput",
    # Premiere Pro
    "PrProjectInput", "PrSequenceInput", "PrMediaInput", "PrTimelineInput",
    "PrExportInput", "PrEffectInput",
    # After Effects
    "AeCompInput", "AeLayerInput", "AePropertyInput", "AeExpressionInput",
    "AeRenderInput", "AeEffectInput",
    # InDesign
    "IdDocInput", "IdTextInput", "IdImageInput",
    # Animate
    "AnDocInput", "AnTimelineInput",
    # Media Encoder
    "AmeEncodeInput",
]
