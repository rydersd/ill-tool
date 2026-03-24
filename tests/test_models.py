"""Test Pydantic model validation for all tool input models."""
import pytest
from pydantic import ValidationError

from adobe_mcp.apps.illustrator.models import (
    AiNewDocInput, AiShapeInput, AiTextInput, AiPathInput, AiExportInput,
    AiInspectInput, AiModifyInput, AiLayerInput, AiImageTraceInput,
    AiAnalyzeReferenceInput, AiReferenceUnderlayInput, AiVtraceInput,
    AiAutoCorrectInput, AiAnchorEditInput, AiProportionGridInput,
    AiSilhouetteInput, AiStyleTransferInput, AiContourToPathInput,
    AiBezierOptimizeInput, AiPathBooleanInput, AiSmartShapeInput,
    AiArtboardFromRefInput, AiCurveFitInput, AiLayerAutoOrganizeInput,
    AiSymmetryInput, AiColorSamplerInput, AiStrokeProfileInput,
    AiPathOffsetInput, AiGroupAndNameInput, AiPathWeldInput,
    AiSnapToGridInput, AiUndoCheckpointInput, AiReferenceCropInput,
    AiSkeletonAnnotateInput, AiBodyPartLabelInput, AiSkeletonBuildInput,
    AiPartBindInput, AiJointRotateInput, AiPoseSnapshotInput,
    AiPoseInterpolateInput, AiIKSolverInput, AiOnionSkinInput,
    AiCharacterTemplateInput, AiPoseFromImageInput, AiKeyframeTimelineInput,
    AiMotionPathInput, AiStoryboardPanelInput,
)
from adobe_mcp.apps.common.models import (
    AppStatusInput, RunJSXInput, RunJSXFileInput, LaunchAppInput,
    OpenFileInput, SaveFileInput, CloseDocInput, RunPowerShellInput,
    GetDocInfoInput, ListFontsInput, PreviewInput, BatchInput,
    WorkflowInput, DesignTokenInput, HealthCheckInput, ContextInput,
    SnippetInput, ToolDiscoveryInput, PipelineInput, RelayStatusInput,
    SessionStateInput, CompareDrawingInput,
)
from adobe_mcp.apps.aftereffects.models import (
    AeCompInput, AeLayerInput, AePropertyInput, AeExpressionInput,
    AeRenderInput, AeEffectInput, AeGenRenderInput,
    AeCompFromCharacterInput, AePuppetPinsInput, AeKeyframeExportInput,
    AeExpressionGenInput, AeAnimaticExportInput,
)
from adobe_mcp.enums import AdobeApp


# ---------------------------------------------------------------------------
# Illustrator models: (ModelClass, required_kwargs)
# Models with all-optional/defaulted fields use empty dict.
# Models with required fields list the minimum args.
# ---------------------------------------------------------------------------

ILLUSTRATOR_MODELS = [
    (AiNewDocInput, {}),
    (AiShapeInput, {"shape": "rectangle"}),
    (AiTextInput, {"text": "hello"}),
    (AiPathInput, {"action": "create"}),
    (AiExportInput, {"file_path": "/tmp/out.svg"}),
    (AiInspectInput, {"action": "list_all"}),
    (AiModifyInput, {"action": "move"}),
    (AiLayerInput, {"action": "list"}),
    (AiImageTraceInput, {"image_path": "/tmp/img.png"}),
    (AiAnalyzeReferenceInput, {"image_path": "/tmp/ref.png"}),
    (AiReferenceUnderlayInput, {"image_path": "/tmp/ref.png"}),
    (AiVtraceInput, {"image_path": "/tmp/img.png"}),
    (AiAutoCorrectInput, {"reference_path": "/tmp/ref.png"}),
    (AiAnchorEditInput, {"action": "get_points"}),
    (AiProportionGridInput, {}),
    (AiSilhouetteInput, {"image_path": "/tmp/img.png"}),
    (AiStyleTransferInput, {}),
    (AiContourToPathInput, {"shape_json": '{"approx_points": []}'}),
    (AiBezierOptimizeInput, {}),
    (AiPathBooleanInput, {"operation": "unite"}),
    (AiSmartShapeInput, {"shape_type": "hexagon", "center_x": 100, "center_y": -100, "width": 50, "height": 50}),
    (AiArtboardFromRefInput, {"image_path": "/tmp/ref.png"}),
    (AiCurveFitInput, {}),
    (AiLayerAutoOrganizeInput, {}),
    (AiSymmetryInput, {}),
    (AiColorSamplerInput, {"image_path": "/tmp/ref.png", "positions": "[[50,50]]"}),
    (AiStrokeProfileInput, {}),
    (AiPathOffsetInput, {"offset": 5.0}),
    (AiGroupAndNameInput, {}),
    (AiPathWeldInput, {}),
    (AiSnapToGridInput, {}),
    (AiUndoCheckpointInput, {"action": "save"}),
    (AiReferenceCropInput, {"image_path": "/tmp/ref.png", "x": 0, "y": 0, "width": 100, "height": 100}),
    (AiSkeletonAnnotateInput, {}),
    (AiBodyPartLabelInput, {}),
    (AiSkeletonBuildInput, {}),
    (AiPartBindInput, {}),
    (AiJointRotateInput, {"joint_name": "shoulder_l", "angle": 45}),
    (AiPoseSnapshotInput, {"action": "capture"}),
    (AiPoseInterpolateInput, {"pose_a": "idle", "pose_b": "walk"}),
    (AiIKSolverInput, {"end_effector": "wrist_l", "target_x": 100, "target_y": -200}),
    (AiOnionSkinInput, {}),
    (AiCharacterTemplateInput, {"action": "save"}),
    (AiPoseFromImageInput, {"image_path": "/tmp/pose.png"}),
    (AiKeyframeTimelineInput, {"action": "add_keyframe"}),
    (AiMotionPathInput, {}),
    (AiStoryboardPanelInput, {}),
]

COMMON_MODELS = [
    (AppStatusInput, {"app": AdobeApp.ILLUSTRATOR}),
    (RunJSXInput, {"app": AdobeApp.ILLUSTRATOR, "code": "alert('hi')"}),
    (RunJSXFileInput, {"app": AdobeApp.ILLUSTRATOR, "file_path": "/tmp/test.jsx"}),
    (LaunchAppInput, {"app": AdobeApp.PHOTOSHOP}),
    (OpenFileInput, {"app": AdobeApp.ILLUSTRATOR, "file_path": "/tmp/test.ai"}),
    (SaveFileInput, {"app": AdobeApp.ILLUSTRATOR}),
    (CloseDocInput, {"app": AdobeApp.ILLUSTRATOR}),
    (RunPowerShellInput, {"script": "Get-Process"}),
    (GetDocInfoInput, {"app": AdobeApp.ILLUSTRATOR}),
    (ListFontsInput, {"app": AdobeApp.ILLUSTRATOR}),
    (PreviewInput, {"app": AdobeApp.ILLUSTRATOR}),
    (BatchInput, {"operations": '[{"tool":"adobe_ai_shapes","params":{}}]'}),
    (WorkflowInput, {"action": "list"}),
    (DesignTokenInput, {"action": "list"}),
    (HealthCheckInput, {}),
    (ContextInput, {}),
    (SnippetInput, {}),
    (ToolDiscoveryInput, {}),
    (PipelineInput, {"steps": '[{"app":"illustrator","tool":"adobe_ai_export","params":{}}]'}),
    (RelayStatusInput, {}),
    (SessionStateInput, {}),
    (CompareDrawingInput, {"reference_path": "/tmp/ref.png"}),
]

AE_MODELS = [
    (AeCompInput, {"action": "create"}),
    (AeLayerInput, {"action": "add_solid"}),
    (AePropertyInput, {"layer_name": "Solid 1", "property_path": "Transform.Position"}),
    (AeExpressionInput, {"layer_name": "Solid 1", "property_path": "Transform.Position", "expression": "wiggle(5,50)"}),
    (AeRenderInput, {"output_path": "/tmp/render.mp4"}),
    (AeEffectInput, {"action": "apply", "layer_name": "Solid 1"}),
    (AeGenRenderInput, {"code": "wiggle(5,50)"}),
    (AeCompFromCharacterInput, {"ai_file_path": "/tmp/character.ai"}),
    (AePuppetPinsInput, {}),
    (AeKeyframeExportInput, {}),
    (AeExpressionGenInput, {}),
    (AeAnimaticExportInput, {}),
]


# ---------------------------------------------------------------------------
# Parametrized instantiation tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model_cls,kwargs", ILLUSTRATOR_MODELS, ids=lambda x: x.__name__ if isinstance(x, type) else "")
def test_all_illustrator_models_with_defaults(model_cls, kwargs):
    """Every Illustrator model instantiates with only required fields."""
    instance = model_cls(**kwargs)
    assert instance is not None


@pytest.mark.parametrize("model_cls,kwargs", COMMON_MODELS, ids=lambda x: x.__name__ if isinstance(x, type) else "")
def test_all_common_models_with_defaults(model_cls, kwargs):
    """Every common model instantiates with only required fields."""
    instance = model_cls(**kwargs)
    assert instance is not None


@pytest.mark.parametrize("model_cls,kwargs", AE_MODELS, ids=lambda x: x.__name__ if isinstance(x, type) else "")
def test_all_ae_models_with_defaults(model_cls, kwargs):
    """Every After Effects model instantiates with only required fields."""
    instance = model_cls(**kwargs)
    assert instance is not None


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

def test_required_field_validation():
    """AiAnalyzeReferenceInput without image_path raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        AiAnalyzeReferenceInput()
    # The error should mention image_path is missing
    errors = exc_info.value.errors()
    field_names = {e["loc"][0] for e in errors}
    assert "image_path" in field_names


def test_field_constraints():
    """AiAnalyzeReferenceInput rejects min_area_pct below ge=0.01."""
    with pytest.raises(ValidationError) as exc_info:
        AiAnalyzeReferenceInput(image_path="/x", min_area_pct=-1)
    errors = exc_info.value.errors()
    field_names = {e["loc"][0] for e in errors}
    assert "min_area_pct" in field_names


def test_field_constraints_upper_bound():
    """AiAnalyzeReferenceInput rejects min_area_pct above le=50."""
    with pytest.raises(ValidationError):
        AiAnalyzeReferenceInput(image_path="/x", min_area_pct=51)


def test_enum_fields_accept_valid_values():
    """Models with AdobeApp enum accept valid string values."""
    instance = AppStatusInput(app="illustrator")
    assert instance.app == AdobeApp.ILLUSTRATOR

    instance2 = RunJSXInput(app="photoshop", code="1+1")
    assert instance2.app == AdobeApp.PHOTOSHOP


def test_enum_fields_reject_invalid_values():
    """Models with AdobeApp enum reject invalid string values."""
    with pytest.raises(ValidationError):
        AppStatusInput(app="not_an_app")


def test_string_strip_whitespace():
    """Models with str_strip_whitespace strip leading/trailing spaces."""
    instance = AiTextInput(text="  hello world  ")
    assert instance.text == "hello world"


def test_ge_le_constraints_on_color():
    """Color fields (0-255) reject out-of-range values."""
    with pytest.raises(ValidationError):
        AiShapeInput(shape="rectangle", fill_r=256)

    with pytest.raises(ValidationError):
        AiShapeInput(shape="rectangle", fill_r=-1)
