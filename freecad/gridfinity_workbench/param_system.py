"""Param system for Gridfinity workbench - the single source of truth for parameters.

This module provides a declarative parameter system that handles:

1. **FreeCAD Property Mapping**: Parameters automatically create and sync with
   FreeCAD DocumentObject properties. Property names are generated from
   group + parameter names (e.g., "fundamentals_grid_units_x").

2. **Automatic UI Generation**: ParameterGroup.build_ui() creates Qt forms
   automatically based on parameter types. BooleanParam -> checkbox,
   FloatParam/IntParam -> spinbox, LiteralParam with choices -> combo box.

3. **Validation**: Each parameter type has built-in validation (bounds checking,
   type checking, choice enforcement). ParameterGroup.validate() runs all
   parameter validations and returns error messages.

4. **Default Management**: Default type is set at the ParameterGroup level via
   `_default_type` class attribute. All parameters in a group share the same
   default resolution strategy:
   - VALUE: Hardcoded in parameter definition (default)
   - SAVED: Persisted in FreeCAD preferences (user customizable)
   - MEM: Session-only memory (remember last used value)

5. **Composition**: CombinedParams aggregates multiple ParameterGroups for
   objects that need parameters from different logical domains.

Key classes:
- BaseParam / BooleanParam / FloatParam / IntParam / LiteralParam: Parameter types
- ParameterGroup: Base class for parameter groups (extend this, set _default_type)
- CombinedParams: Aggregates multiple ParameterGroups
- ParamDefaultResolver: Handles SAVED and MEM default storage
- ParamSystemRouter: Routes FreeCAD objects to their parameter classes

Usage pattern:
    class MyFeatureParams(ParameterGroup):
        _default_type = DefaultType.MEM  # All params remember last value

        def __init__(self):
            super().__init__([
                FloatParam("width", "Width", fc.Units.Quantity("10 mm")),
                BooleanParam("enabled", "Enabled", True),
            ])

    # Create object properties
    params = MyFeatureParams()
    params.add_properties_to_object(obj)

    # Read from object
    params = MyFeatureParams().from_obj(obj)

    # Build UI automatically
    controls, widget = params.build_ui()
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Literal

import FreeCAD as fc  # noqa: N813

# Type alias for parameter values - using Any to avoid strict type narrowing
# since parameter values can be bool, int, float, str, or fc.Units.Quantity
ParamValue = Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from PySide.QtWidgets import QLabel, QLayout, QWidget


@dataclass(frozen=True)
class ValidationError:
    """A validation error affecting one or more parameters.

    Attributes:
        message: Human-readable error description.
        affected_params: Parameter keys that should display this error.
            For ParameterGroup: just param names (e.g., "filler_top_enabled").
            For CombinedParams: prefixed names (e.g., "baseplate_size.filler_top_enabled").

    """

    message: str
    affected_params: tuple[str, ...]


def validation_errors_to_dict(errors: list[ValidationError]) -> dict[str, str]:
    """Expand ValidationErrors to param_key -> message dict.

    When multiple errors affect the same param, the last error wins.
    """
    result: dict[str, str] = {}
    for err in errors:
        for param in err.affected_params:
            result[param] = err.message
    return result


def map_errors_to_compound_params(
    error_dict: dict[str, str],
    expanded_to_compound: dict[str, str],
) -> dict[str, str]:
    """Map expanded param error keys to compound param keys.

    Args:
        error_dict: Dict mapping param keys to error messages.
        expanded_to_compound: Dict mapping expanded names to compound names.

    Returns:
        New dict with compound param keys, accumulating messages with '; '.

    """
    result: dict[str, str] = {}
    for param_key, message in error_dict.items():
        if param_key in expanded_to_compound:
            compound_name = expanded_to_compound[param_key]
            if compound_name in result:
                result[compound_name] += f"; {message}"
            else:
                result[compound_name] = message
        else:
            result[param_key] = message
    return result


@dataclass
class ParamErrorDisplay:
    """Manages error display state for a parameter control.

    Encapsulates the control widget and its associated error label,
    providing methods to show/clear validation errors with consistent styling.
    """

    control: QWidget
    error_label: QLabel

    def show_error(self, message: str) -> None:
        """Display error with red text styling."""
        self.error_label.setText(message)
        self.error_label.setStyleSheet("color: #ff4d4d; font-style: italic; font-size: 11px;")
        self.error_label.show()

    def clear_error(self) -> None:
        """Hide error label and clear text."""
        self.error_label.setText("")
        self.error_label.hide()


class DefaultType(Enum):
    """Types of default values for parameters.

    Set at the ParameterGroup level via `_default_type` class attribute.
    All parameters in a group share the same default resolution strategy.

    - VALUE: Hardcoded default defined in the parameter declaration (default).
    - SAVED: Persisted default stored in FreeCAD preferences (survives restarts).
    - MEM: Runtime session memory (cleared when FreeCAD closes).

    Use SAVED for user-customizable defaults via "Edit Defaults" commands.
    Use MEM for "remember last used value" behavior within a session.

    Example:
        class MySizeParams(ParameterGroup):
            _default_type = DefaultType.MEM  # Remember last values

    """

    VALUE = "Value"  # Hardcoded default
    SAVED = "Saved"  # From plugin config
    MEM = "Mem"  # Runtime memory


class ParamDefaultResolver:
    """Resolver for persisted (SAVED) and runtime (MEM) parameter defaults.

    Used internally by ParameterGroup to resolve defaults based on the group's
    `_default_type` setting. You typically don't need to interact with this
    class directly.

    SAVED defaults:
        - Stored in FreeCAD's preference system under the GridfinityWorkbench path.
        - Persist across FreeCAD sessions.
        - Used when ParameterGroup._default_type = DefaultType.SAVED.

    MEM defaults:
        - Stored in a class-level runtime cache (_runtime_cache).
        - Only persist within a single FreeCAD session.
        - Used when ParameterGroup._default_type = DefaultType.MEM.

    The resolver is keyed by "group_name.param_name" to avoid collisions.
    A global `default_resolver` instance is provided for standard usage.
    """

    _prefs_path = "User parameter:BaseApp/Preferences/Mod/GridfinityWorkbench"
    # Class-level session memory for MEM defaults
    _runtime_cache: ClassVar[dict[str, ParamValue]] = {}

    def _make_key(self, group_name: str, param_name: str) -> str:
        return f"{group_name}.{param_name}"

    def get_saved(
        self,
        group_name: str,
        param_name: str,
        fallback: ParamValue,
        value_type: type,
    ) -> ParamValue:
        """Load from FreeCAD prefs by type."""
        prefs = fc.ParamGet(self._prefs_path)
        key = self._make_key(group_name, param_name)
        if value_type is bool:
            return prefs.GetBool(key, fallback)
        if value_type is int:
            return prefs.GetInt(key, fallback)
        if value_type is float:
            return prefs.GetFloat(key, fallback)
        if value_type is str:
            return prefs.GetString(key, fallback)
        return fallback

    def set_saved(self, group_name: str, param_name: str, value: ParamValue) -> None:
        """Persist to FreeCAD prefs."""
        prefs = fc.ParamGet(self._prefs_path)
        key = self._make_key(group_name, param_name)
        if isinstance(value, bool):
            prefs.SetBool(key, value)
        elif isinstance(value, int):
            prefs.SetInt(key, value)
        elif isinstance(value, float):
            prefs.SetFloat(key, value)
        elif isinstance(value, str):
            prefs.SetString(key, value)

    def get_runtime(self, group_name: str, param_name: str, fallback: ParamValue) -> ParamValue:
        """Get from session memory."""
        key = self._make_key(group_name, param_name)
        return self._runtime_cache.get(key, fallback)

    def set_runtime(self, group_name: str, param_name: str, value: ParamValue) -> None:
        """Store in session memory."""
        key = self._make_key(group_name, param_name)
        self._runtime_cache[key] = value


# Global resolver instance
default_resolver = ParamDefaultResolver()


class BaseParam:
    """Base class for individual parameters with FreeCAD property mapping.

    BaseParam is the foundation for all parameter types. Each parameter defines:
    - name: Internal identifier (snake_case, e.g., "wall_thickness")
    - display_name: Human-readable label for UI (e.g., "Wall Thickness")
    - freecad_property_type: The FreeCAD property type (e.g., "App::PropertyLength")
    - description: Tooltip text for UI and property documentation

    Key responsibilities:
    - Generate canonical property names via property_name_for_group()
    - Provide validation hooks for subclasses

    Note: default_type is managed at the ParameterGroup level, not per-parameter.
    All parameters in a group share the same default resolution strategy.

    Subclasses (BooleanParam, FloatParam, IntParam, LiteralParam) add type-specific
    default values, validation rules, and appropriate FreeCAD property types.
    """

    def __init__(
        self,
        name: str,
        display_name: str,
        freecad_property_type: str = "App::PropertyFloat",
        description: str = "",
    ) -> None:
        """Initialize a base parameter with name, display name, and property type."""
        self.name = name
        self.display_name = display_name
        self.freecad_property_type = (
            freecad_property_type  # FreeCAD property type (e.g., "App::PropertyLength")
        )
        self.description = description

    def property_name_for_group(self, group_class_name: str) -> str:
        """Generate canonical prefixed snake_case property name."""
        group_name = group_class_name.replace("Params", "")
        group_snake = re.sub(r"(?<!^)(?=[A-Z])", "_", group_name).lower()
        return f"{group_snake}_{self.name}"

    def default(self) -> ParamValue:
        """Return the actual default value."""
        return 0  # Subclasses should override this

    def default_value_type(self) -> type:
        """Return the Python type of the default value for resolver lookups."""
        return type(self.default())

    def validate(self, value: ParamValue) -> bool:  # noqa: ARG002
        """Validate the given value."""
        return True


class BooleanParam(BaseParam):
    """Boolean parameter for on/off flags and feature toggles.

    Maps to App::PropertyBool in FreeCAD by default.
    Validation ensures the value is a Python bool.

    Example usage:
        BooleanParam("enabled", "Enabled", default_value=True)
    """

    def __init__(
        self,
        name: str,
        display_name: str,
        default_value: bool = False,  # noqa: FBT001, FBT002
        freecad_property_type: str = "App::PropertyBool",
        description: str = "",
    ) -> None:
        """Initialize a boolean parameter."""
        super().__init__(
            name,
            display_name,
            freecad_property_type,
            description,
        )
        self.default_value = default_value

    def default(self) -> bool:
        """Return the default boolean value."""
        return self.default_value

    def validate(self, value: ParamValue) -> bool:
        """Validate value is boolean."""
        return isinstance(value, bool)


class FloatParam(BaseParam):
    """Floating-point parameter for dimensional values (lengths, angles, etc.).

    Maps to App::PropertyLength by default, storing FreeCAD Quantity objects.
    Supports min/max bounds and positive_only constraint.

    Validation checks:
    - Value is convertible to float
    - Value is within min_value/max_value bounds (if specified)
    - Value is positive (if positive_only=True)

    Example usage:
        FloatParam("height", "Height", default_value=fc.Units.Quantity("42 mm"))
    """

    def __init__(  # noqa: PLR0913
        self,
        name: str,
        display_name: str,
        default_value: fc.Units.Quantity,
        min_value: fc.Units.Quantity | None = None,
        max_value: fc.Units.Quantity | None = None,
        freecad_property_type: str = "App::PropertyLength",  # Default to Length for measurements
        description: str = "",
        positive_only: bool = False,  # noqa: FBT001, FBT002 - Whether this param should be positive
    ) -> None:
        """Initialize a float/quantity parameter with optional bounds."""
        super().__init__(
            name,
            display_name,
            freecad_property_type,
            description,
        )
        self.default_value = default_value
        self.min_value = min_value
        self.max_value = max_value
        self.positive_only = positive_only

    def default(self) -> fc.Units.Quantity:
        """Return the default quantity value."""
        return self.default_value

    def validate(self, value: ParamValue) -> bool:
        """Validate number is within bounds if specified and is numeric."""
        try:
            float_val = float(value)
            if self.min_value is not None and float_val < float(self.min_value):
                return False
            if self.max_value is not None and float_val > float(self.max_value):
                return False
        except (TypeError, ValueError):
            return False
        else:
            return not (self.positive_only and float_val <= 0)


class LiteralParam(BaseParam):
    """String parameter with optional enumeration constraint.

    Maps to App::PropertyString by default. If choices are provided,
    the UI will render as a combo box and validation enforces the value
    is one of the allowed choices.

    Example usage:
        LiteralParam("mode", "Mode", default_value="auto", choices=["auto", "manual"])
    """

    def __init__(  # noqa: PLR0913
        self,
        name: str,
        display_name: str,
        default_value: str,
        choices: list[str] | None = None,
        freecad_property_type: str = "App::PropertyString",
        description: str = "",
    ) -> None:
        """Initialize a literal/string parameter with optional choices."""
        super().__init__(
            name,
            display_name,
            freecad_property_type,
            description,
        )
        self.default_value = default_value
        self.choices = choices

    def default(self) -> str:
        """Return the default string value."""
        return self.default_value

    def validate(self, value: ParamValue) -> bool:
        """Validate string is in choices if specified and is a string."""
        if not isinstance(value, str):
            return False
        return not (self.choices is not None and value not in self.choices)


class IntParam(BaseParam):
    """Integer parameter for counts, indices, and discrete quantities.

    Maps to App::PropertyInteger by default.
    Supports min/max bounds and positive_only constraint.

    Validation checks:
    - Value is an int (bool is rejected)
    - Value is within min_value/max_value bounds (if specified)
    - Value is positive (if positive_only=True)

    Example usage:
        IntParam("grid_units_x", "Grid Units X", default_value=3, min_value=1)
    """

    def __init__(  # noqa: PLR0913
        self,
        name: str,
        display_name: str,
        default_value: int,
        min_value: int | None = None,
        max_value: int | None = None,
        freecad_property_type: str = "App::PropertyInteger",
        description: str = "",
        positive_only: bool = False,  # noqa: FBT001, FBT002
    ) -> None:
        """Initialize an integer parameter with optional bounds."""
        super().__init__(
            name,
            display_name,
            freecad_property_type,
            description,
        )
        self.default_value = int(default_value)
        self.min_value = min_value
        self.max_value = max_value
        self.positive_only = positive_only

    def default(self) -> int:
        """Return the default integer value."""
        return self.default_value

    def validate(self, value: ParamValue) -> bool:
        """Validate integer is within bounds if specified."""
        if isinstance(value, bool):
            return False
        if not isinstance(value, int):
            return False
        if self.min_value is not None and value < self.min_value:
            return False
        if self.max_value is not None and value > self.max_value:
            return False
        return not (self.positive_only and value <= 0)


class LayoutParam(BaseParam):
    """Layout parameter for storing 2D boolean grid layouts.

    Maps to App::PropertyString in FreeCAD, storing the layout as JSON.
    UI renders as a button that opens a layout editor dialog.

    Example usage:
        LayoutParam("custom_layout", "Custom Layout")
    """

    def __init__(
        self,
        name: str,
        display_name: str,
        freecad_property_type: str = "App::PropertyString",
        description: str = "",
    ) -> None:
        """Initialize a layout parameter."""
        super().__init__(
            name,
            display_name,
            freecad_property_type,
            description,
        )

    def default(self) -> None:  # type: ignore[override]
        """Return the default value (None = no custom layout)."""

    def default_value_type(self) -> type:
        """Return the Python type for resolver lookups."""
        return type(None)

    def validate(self, value: ParamValue) -> bool:
        """Validate value is None or a nested list of bools."""
        if value is None:
            return True
        if not isinstance(value, list):
            return False
        for row in value:
            if not isinstance(row, list):
                return False
            for cell in row:
                if not isinstance(cell, bool):
                    return False
        return True

    def to_json(self, value: list[list[bool]] | None) -> str:
        """Convert layout to JSON string for FreeCAD property storage."""
        import json

        if value is None:
            return ""
        return json.dumps(value)

    def from_json(self, json_str: str) -> list[list[bool]] | None:
        """Convert JSON string from FreeCAD property to layout."""
        import json

        if not json_str:
            return None
        return json.loads(json_str)


class ParamCombination(ABC):
    """Base class for compound parameters that expand to multiple BaseParams.

    ParamCombination allows defining a single logical parameter that internally
    manages multiple underlying BaseParams. This is useful for related parameters
    that should appear as a single UI row (e.g., enabled checkbox + value spinbox).

    Subclasses must implement:
    - expand(): Return list of underlying BaseParams
    - build_control(): Create combined Qt widget
    - read_control(): Extract values from combined widget

    The ParameterGroup handles expansion automatically in __init__ and provides
    special handling in UI generation methods.
    """

    name: str
    display_name: str

    @abstractmethod
    def expand(self) -> list[BaseParam]:
        """Return list of underlying BaseParams that this combination expands to."""
        ...

    def expanded_names(self) -> list[str]:
        """Return names of all expanded params (for filtering in ui_descriptors)."""
        return [p.name for p in self.expand()]

    @abstractmethod
    def build_control(self, values: dict[str, ParamValue]) -> QWidget:
        """Build combined UI widget.

        Args:
            values: Dict mapping expanded param names to their current values.

        Returns:
            Combined Qt widget (e.g., HBoxLayout with checkbox + spinbox).

        """
        ...

    @abstractmethod
    def read_control(self, widget: QWidget) -> dict[str, ParamValue]:
        """Extract values from combined widget.

        Args:
            widget: The combined widget created by build_control().

        Returns:
            Dict mapping expanded param names to their values.

        """
        ...

    @abstractmethod
    def connect_signals(self, widget: QWidget, callback: Callable[[], None]) -> None:
        """Connect widget signals to a callback for change notifications.

        Args:
            widget: The combined widget created by build_control().
            callback: Function to call when any value changes.

        """
        ...


class OptionalQuantityParam(ParamCombination):
    """Compound parameter: checkbox (enabled) + spinbox (quantity).

    Expands to two params: {name}{enabled_suffix} and {name}{quantity_suffix}.
    Renders as single UI row: [checkbox] Label [spinbox mm]

    Example usage:
        OptionalQuantityParam(
            "filler_top",
            "Top Filler",
            enabled_suffix="_enabled",
            quantity_suffix="_width",
            default_quantity=fc.Units.Quantity("30 mm"),
        )
        # Expands to: filler_top_enabled (bool), filler_top_width (Quantity)
    """

    def __init__(
        self,
        name: str,
        display_name: str,
        enabled_suffix: str,
        quantity_suffix: str,
        default_quantity: fc.Units.Quantity,
        default_enabled: bool = False,  # noqa: FBT001, FBT002
        positive_only: bool = True,  # noqa: FBT001, FBT002
    ) -> None:
        """Initialize an optional quantity parameter.

        Args:
            name: Base name (e.g., "filler_top")
            display_name: Human-readable label for UI
            enabled_suffix: Suffix for the boolean param
            quantity_suffix: Suffix for the quantity param
            default_quantity: Default quantity value when enabled
            default_enabled: Whether enabled by default
            positive_only: Whether quantity must be positive

        """
        self.name = name
        self.display_name = display_name
        self.enabled_suffix = enabled_suffix
        self.quantity_suffix = quantity_suffix
        self.default_quantity = default_quantity
        self.default_enabled = default_enabled
        self.positive_only = positive_only

    @property
    def enabled_name(self) -> str:
        """Full name for the enabled param."""
        return f"{self.name}{self.enabled_suffix}"

    @property
    def quantity_name(self) -> str:
        """Full name for the quantity param."""
        return f"{self.name}{self.quantity_suffix}"

    def expand(self) -> list[BaseParam]:
        """Return enabled (bool) and quantity params."""
        return [
            BooleanParam(
                self.enabled_name,
                f"{self.display_name} Enabled",
                self.default_enabled,
            ),
            FloatParam(
                self.quantity_name,
                f"{self.display_name} Width",
                self.default_quantity,
                positive_only=self.positive_only,
            ),
        ]

    def build_control(self, values: dict[str, ParamValue]) -> QWidget:
        """Build checkbox + spinbox in horizontal layout."""
        from PySide.QtWidgets import QCheckBox, QDoubleSpinBox, QHBoxLayout, QWidget

        enabled_val = values.get(self.enabled_name, self.default_enabled)
        quantity_val = values.get(self.quantity_name, self.default_quantity)

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        checkbox = QCheckBox()
        checkbox.setChecked(bool(enabled_val))
        checkbox.setObjectName("enabled")

        spinbox = QDoubleSpinBox()
        spinbox.setMinimum(0)
        spinbox.setMaximum(999999)
        spinbox.setValue(float(quantity_val))
        spinbox.setObjectName("quantity")
        # Store unit for later conversion
        spinbox.setProperty("unit", self.default_quantity / float(self.default_quantity))

        layout.addWidget(checkbox)
        layout.addWidget(spinbox)

        return widget

    def read_control(self, widget: QWidget) -> dict[str, ParamValue]:
        """Extract enabled and quantity values from combined widget."""
        checkbox = widget.findChild(widget.__class__, "enabled")
        spinbox = widget.findChild(widget.__class__, "quantity")

        # Fallback to searching by type if objectName search fails
        if checkbox is None or spinbox is None:
            from PySide.QtWidgets import QCheckBox, QDoubleSpinBox

            for child in widget.children():
                if isinstance(child, QCheckBox):
                    checkbox = child
                elif isinstance(child, QDoubleSpinBox):
                    spinbox = child

        enabled = checkbox.isChecked() if checkbox else self.default_enabled
        if spinbox:
            unit = spinbox.property("unit")
            quantity = (
                spinbox.value() * unit if unit else fc.Units.Quantity(spinbox.value(), "mm")
            )
        else:
            quantity = self.default_quantity

        return {
            self.enabled_name: enabled,
            self.quantity_name: quantity,
        }

    def connect_signals(self, widget: QWidget, callback: Callable[[], None]) -> None:
        """Connect checkbox and spinbox signals to callback."""
        from PySide.QtWidgets import QCheckBox, QDoubleSpinBox

        for child in widget.children():
            if isinstance(child, QCheckBox):
                child.stateChanged.connect(lambda *_: callback())
            elif isinstance(child, QDoubleSpinBox):
                child.valueChanged.connect(lambda *_: callback())


class OptionalLayoutParam(ParamCombination):
    """Compound parameter: checkbox (enabled) + layout editor button.

    Expands to two params: {name}{enabled_suffix} and {name}{layout_suffix}.
    Renders as single UI row: [checkbox] Label [Edit Layout... button]

    Example usage:
        OptionalLayoutParam(
            "custom_layout",
            "Custom Layout",
            enabled_suffix="_enabled",
            layout_suffix="",  # empty suffix -> "custom_layout" itself
        )
        # Expands to: custom_layout_enabled (bool), custom_layout (list[list[bool]] | None)
    """

    def __init__(
        self,
        name: str,
        display_name: str,
        enabled_suffix: str = "_enabled",
        layout_suffix: str = "",
        default_enabled: bool = False,  # noqa: FBT001, FBT002
    ) -> None:
        """Initialize an optional layout parameter.

        Args:
            name: Base name (e.g., "custom_layout")
            display_name: Human-readable label for UI
            enabled_suffix: Suffix for the boolean param
            layout_suffix: Suffix for the layout param (empty string for base name)
            default_enabled: Whether enabled by default

        """
        self.name = name
        self.display_name = display_name
        self.enabled_suffix = enabled_suffix
        self.layout_suffix = layout_suffix
        self.default_enabled = default_enabled

    @property
    def enabled_name(self) -> str:
        """Full name for the enabled param."""
        return f"{self.name}{self.enabled_suffix}"

    @property
    def layout_name(self) -> str:
        """Full name for the layout param."""
        return f"{self.name}{self.layout_suffix}"

    def expand(self) -> list[BaseParam]:
        """Return enabled (bool) and layout params."""
        return [
            BooleanParam(
                self.enabled_name,
                f"{self.display_name} Enabled",
                self.default_enabled,
            ),
            LayoutParam(
                self.layout_name,
                self.display_name,
            ),
        ]

    def build_control(self, values: dict[str, ParamValue]) -> QWidget:
        """Build checkbox + layout button in horizontal layout."""
        from PySide.QtWidgets import QCheckBox, QHBoxLayout, QPushButton, QWidget

        enabled_val = values.get(self.enabled_name, self.default_enabled)
        layout_val = values.get(self.layout_name)

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        checkbox = QCheckBox()
        checkbox.setChecked(bool(enabled_val))
        checkbox.setObjectName("enabled")

        button = QPushButton("Edit Layout...")
        button.setObjectName("layout_button")
        button.setProperty("layout_value", layout_val)
        button._layout_changed_callback = None  # noqa: SLF001

        def on_click() -> None:
            from freecad.gridfinity_workbench import custom_shape

            current = button.property("layout_value")
            result = custom_shape.custom_bin_dialog([], current)
            if result is not None:
                button.setProperty("layout_value", result.layout)
                # Enable the checkbox when a layout is accepted
                checkbox.setChecked(True)
                # Trigger preview update callback if set
                if button._layout_changed_callback is not None:  # noqa: SLF001
                    button._layout_changed_callback()  # noqa: SLF001

        button.clicked.connect(on_click)

        layout.addWidget(checkbox)
        layout.addWidget(button)

        return widget

    def read_control(self, widget: QWidget) -> dict[str, ParamValue]:
        """Extract enabled and layout values from combined widget."""
        checkbox = widget.findChild(widget.__class__, "enabled")
        button = widget.findChild(widget.__class__, "layout_button")

        # Fallback to searching by type if objectName search fails
        if checkbox is None or button is None:
            from PySide.QtWidgets import QCheckBox, QPushButton

            for child in widget.children():
                if isinstance(child, QCheckBox):
                    checkbox = child
                elif isinstance(child, QPushButton):
                    button = child

        enabled = checkbox.isChecked() if checkbox else self.default_enabled
        layout_value = button.property("layout_value") if button else None

        return {
            self.enabled_name: enabled,
            self.layout_name: layout_value,
        }

    def connect_signals(self, widget: QWidget, callback: Callable[[], None]) -> None:
        """Connect checkbox and layout button signals to callback."""
        from PySide.QtWidgets import QCheckBox, QPushButton

        for child in widget.children():
            if isinstance(child, QCheckBox):
                child.stateChanged.connect(lambda *_: callback())
            elif isinstance(child, QPushButton):
                # Store callback as Python attr so layout dialog can trigger preview
                child._layout_changed_callback = callback  # noqa: SLF001


class ParameterGroup(ABC):
    """Base class for parameter groups with automatic UI, validation, and FreeCAD integration.

    ParameterGroup is the **single source of truth** for a cohesive set of parameters.
    Subclass this to define parameter groups like "FundamentalsParams" or "BinWallParams".

    Key responsibilities:
    1. **FreeCAD Property Management**:
       - add_properties_to_object(): Creates FreeCAD properties on DocumentObjects
       - from_obj(): Extracts current values from a FreeCAD object
       - to_obj(): Applies values back to a FreeCAD object (also updates MEM defaults)

    2. **Automatic UI Generation**:
       - ui_descriptors(): Returns UIField metadata for all parameters
       - get_ui_controls(): Creates Qt widgets (checkbox, spinbox, combo) automatically
       - build_ui(): Builds a complete form layout from parameters
       - update_from_ui_controls(): Reads values back from Qt widgets

    3. **Validation**:
       - validate(): Runs validation on all parameters, returns dict of errors
       - Each parameter's validate() method is called automatically

    4. **Default Management**:
       - Set `_default_type` class attribute to control default resolution for ALL params
       - VALUE (default): Use hardcoded defaults from parameter definitions
       - SAVED: Load from FreeCAD preferences, persist via save_as_defaults()
       - MEM: Remember last values within session, auto-updated by to_obj()

    5. **Serialization**:
       - to_ui_payload() / from_ui_payload(): Convert to/from UI-friendly dicts

    Subclasses must define parameters in __init__ and may override data() to return
    a frozen data object for computation.

    Class attributes:
    - _default_type: Default resolution strategy for all params in this group
      (VALUE, SAVED, or MEM). Subclasses override to change behavior.

    Derived properties (from class name):
    - category: FreeCAD property category (e.g., "Gridfinity_Baseplate_Size")
    - section_title: UI section title (e.g., "Baseplate Size")
    """

    # Subclasses override to change default resolution strategy for all params
    _default_type: DefaultType = DefaultType.VALUE

    def __init__(
        self,
        parameters: Sequence[BaseParam | ParamCombination] | None = None,
        resolver: ParamDefaultResolver | None = None,
    ) -> None:
        """Initialize a parameter group with optional parameters and resolver."""
        # Expand ParamCombination instances into their underlying params
        expanded_params: list[BaseParam] = []
        self._compound_params: dict[str, ParamCombination] = {}
        # Track UI order: list of param names (compound params use their base name)
        self._ui_order: list[str] = []

        for param in parameters or []:
            if isinstance(param, ParamCombination):
                self._compound_params[param.name] = param
                self._ui_order.append(param.name)
                expanded_params.extend(param.expand())
            else:
                self._ui_order.append(param.name)
                expanded_params.append(param)

        self._parameters: dict[str, BaseParam] = {p.name: p for p in expanded_params}
        self._values: dict[str, ParamValue] = {}
        self._resolver = resolver if resolver is not None else default_resolver
        self._group_name = self._compute_group_name()

        # Dynamically create getter methods for each parameter
        for param_name in self._parameters:
            # Create method name by removing underscores
            method_name = param_name.replace("_", "")

            # Create a closure that captures the param_name
            def make_getter(pn: str) -> Callable[[ParameterGroup], ParamValue]:
                def getter(self: ParameterGroup) -> ParamValue:
                    return self.get_value(pn)

                return getter

            # Add the method to the class
            setattr(self.__class__, method_name, make_getter(param_name))

    def add_properties_to_object(self, obj: fc.DocumentObject) -> None:
        """Automatically add all parameter properties to the FreeCAD object."""
        for param_name, param in self._parameters.items():
            value = self.get_value(param_name)

            # Use provided property name or generate one based on group and parameter names
            property_name = self._property_name(param)

            # Add the property to the object using the parameter's defined property type and name
            obj.addProperty(
                param.freecad_property_type,
                property_name,
                self.category,
                param.description or f"{param.display_name} parameter",
            )

            # For LayoutParam, convert list to JSON string
            if isinstance(param, LayoutParam):
                value = param.to_json(value)

            # Set the value appropriately based on property type
            setattr(obj, property_name, value)

    def get_value(self, param_name: str) -> ParamValue:
        """Get value for a specific parameter, handling default resolution."""
        if param_name in self._values:
            return self._values[param_name]

        param = self._parameters[param_name]
        return self._resolve_default(param)

    def _resolve_default(self, param: BaseParam) -> ParamValue:
        """Resolve parameter default based on group's default_type.

        Args:
            param: The parameter to resolve the default for.

        """
        fallback = param.default()
        dt = self._default_type

        if dt == DefaultType.VALUE:
            return fallback

        if self._resolver is None:
            return fallback

        if dt == DefaultType.SAVED:
            return self._resolver.get_saved(
                self._group_name,
                param.name,
                fallback,
                param.default_value_type(),
            )

        if dt == DefaultType.MEM:
            return self._resolver.get_runtime(self._group_name, param.name, fallback)

        return fallback

    def set_value(self, param_name: str, value: ParamValue) -> None:
        """Set value for a specific parameter."""
        if param_name in self._parameters:
            self._values[param_name] = value

    def set_all_values(self, values: dict[str, ParamValue]) -> None:
        """Set multiple parameter values at once."""
        for param_name, value in values.items():
            self.set_value(param_name, value)

    def from_obj(self, obj: fc.DocumentObject) -> ParameterGroup:
        """Extract parameters from FreeCAD object using direct property mapping."""
        values = {}

        # Iterate through all parameters to extract from object using direct property mapping
        for param_name, param in self._parameters.items():
            # Use the direct property name mapping
            obj_property_name = self._property_name(param)
            if hasattr(obj, obj_property_name):
                value = getattr(obj, obj_property_name)
                # For LayoutParam, convert JSON string to list
                if isinstance(param, LayoutParam):
                    value = param.from_json(value)
                values[param_name] = value

        # Create new instance with extracted values
        new_group = self.__class__()
        new_group.set_all_values(values)
        # Preserve error displays if they exist (for UI error rendering)
        if hasattr(self, "_error_displays"):
            new_group._error_displays = self._error_displays  # noqa: SLF001
        return new_group

    def to_obj(self, obj: fc.DocumentObject) -> None:
        """Apply parameters to FreeCAD object and update MEM defaults."""
        for param_name, param in self._parameters.items():
            obj_property_name = self._property_name(param)
            if hasattr(obj, obj_property_name):
                value = self.get_value(param_name)
                # For LayoutParam, convert list to JSON string
                if isinstance(param, LayoutParam):
                    value = param.to_json(value)
                setattr(obj, obj_property_name, value)
        # Update MEM defaults if this group uses MEM default_type
        if self._default_type == DefaultType.MEM:
            for param_name in self._parameters:
                value = self.get_value(param_name)
                self._resolver.set_runtime(self._group_name, param_name, value)

    def save_as_defaults(self) -> None:
        """Save current values as SAVED defaults (for Edit Defaults command)."""
        for param_name in self._parameters:
            value = self.get_value(param_name)
            # Convert Quantity to float for storage
            if hasattr(value, "Value"):
                value = float(value.Value)
            self._resolver.set_saved(self._group_name, param_name, value)

    def load_saved_defaults(self) -> ParameterGroup:
        """Load SAVED defaults into _values (for Edit Defaults UI initialization)."""
        for param_name, param in self._parameters.items():
            fallback = param.default()
            # Convert Quantity to float for comparison
            fallback_for_lookup = float(fallback.Value) if hasattr(fallback, "Value") else fallback
            saved = self._resolver.get_saved(
                self._group_name,
                param_name,
                fallback_for_lookup,
                param.default_value_type(),
            )
            # For FloatParams, convert back to Quantity if needed
            if hasattr(fallback, "Value") and isinstance(saved, int | float):
                saved = fc.Units.Quantity(saved, fallback.Unit)
            self._values[param_name] = saved
        return self

    def _property_name(self, param: BaseParam) -> str:
        return param.property_name_for_group(self.__class__.__name__)

    def _compute_group_name(self) -> str:
        """Return canonical group key generated from class name."""
        explicit_group_key = getattr(self, "_group_name_override", None)
        if explicit_group_key:
            return explicit_group_key

        group_name = self.__class__.__name__.replace("Params", "")
        return re.sub(r"(?<!^)(?=[A-Z])", "_", group_name).lower()

    @property
    def category(self) -> str:
        """Return FreeCAD property category derived from class name.

        E.g., ClickSpringsParams -> "Gridfinity_Click_Springs"
        """
        base = self.__class__.__name__.replace("Params", "")
        # Insert underscore before each capital letter (except first)
        with_underscores = re.sub(r"(?<!^)(?=[A-Z])", "_", base)
        return f"Gridfinity_{with_underscores}"

    @property
    def section_title(self) -> str:
        """Return UI section title derived from class name.

        E.g., ClickSpringsParams -> "Click Springs"
        """
        base = self.__class__.__name__.replace("Params", "")
        # Insert space before each capital letter (except first)
        return re.sub(r"(?<!^)(?=[A-Z])", " ", base)

    def validate(self) -> list[ValidationError]:
        """Validate all parameters in this group.

        Returns:
            List of ValidationError instances. Each error specifies the message
            and which parameters it affects.

        """
        errors: list[ValidationError] = []
        for param_name, param in self._parameters.items():
            value = self.get_value(param_name)
            if not param.validate(value):
                errors.append(
                    ValidationError(
                        message=f"Invalid value for {param.display_name}: {value}",
                        affected_params=(param_name,),
                    )
                )
        return errors

    def to_ui_payload(self) -> dict[str, Any]:
        """Return UI-friendly payload for this parameter group."""
        payload: dict[str, Any] = {}
        for param_name, param in self._parameters.items():
            payload[param_name] = self._to_ui_value(param, self.get_value(param_name))
        return payload

    def from_ui_payload(self, payload: dict[str, Any]) -> None:
        """Apply UI payload values to this parameter group."""
        for param_name, ui_value in payload.items():
            if param_name not in self._parameters:
                continue
            param = self._parameters[param_name]
            self.set_value(param_name, self._from_ui_value(param, ui_value))

    def ui_descriptors(self) -> dict[str, UIField]:
        """Automatically generate UI configuration for all parameters in original order."""
        descriptors = {}
        group_name = self.__class__.__name__.replace("Params", "").lower()

        for name in self._ui_order:
            if name in self._compound_params:
                # Compound param
                cp = self._compound_params[name]
                descriptors[name] = UIField(
                    control_type="compound",
                    label=cp.display_name,
                    param_name=name,
                    group=group_name,
                )
            elif name in self._parameters:
                # Regular param
                param = self._parameters[name]
                descriptors[name] = UIField(
                    control_type=self._get_control_type(param),
                    label=param.display_name,
                    param_name=name,
                    group=group_name,
                )

        return descriptors

    def has_param(self, param_name: str) -> bool:
        """Check if this group has a parameter with the given name."""
        return param_name in self._parameters

    def get_param(self, param_name: str) -> BaseParam:
        """Get the parameter object by name."""
        if param_name in self._parameters:
            return self._parameters[param_name]
        raise KeyError(f"Parameter '{param_name}' not found in group {self.__class__.__name__}")

    def defaults(self) -> dict[str, Any]:
        """Automatically return all default values."""
        defaults = {}
        for param_name, param in self._parameters.items():
            defaults[param_name] = param.default()
        return defaults

    def _get_control_type(self, param: BaseParam) -> ControlType:
        """Determine UI control type based on parameter type."""
        if isinstance(param, BooleanParam):
            return "checkbox"
        if isinstance(param, FloatParam | IntParam):
            return "spinbox"
        if isinstance(param, LiteralParam):
            return "combo" if param.choices else "textbox"
        if isinstance(param, LayoutParam):
            return "button"
        return "textbox"

    def _to_ui_value(self, param: BaseParam, value: ParamValue) -> ParamValue:
        if isinstance(param, IntParam):
            return int(value)
        if isinstance(param, FloatParam):
            return float(value)
        return value

    def _from_ui_value(self, param: BaseParam, ui_value: ParamValue) -> ParamValue:
        if isinstance(param, IntParam):
            return int(ui_value)
        if isinstance(param, FloatParam):
            if isinstance(ui_value, fc.Units.Quantity):
                return ui_value
            # Use the unit from the default value (handles mm, deg, etc.)
            default_qty = param.default()
            unit_qty = default_qty / float(default_qty) if float(default_qty) != 0 else default_qty
            return float(ui_value) * unit_qty
        if isinstance(param, BooleanParam):
            return bool(ui_value)
        if isinstance(param, LiteralParam):
            return str(ui_value)
        return ui_value

    def _get_saved_default(self, param_name: str, fallback: ParamValue) -> ParamValue:
        """Get default value from plugin config."""
        if param_name not in self._parameters:
            return fallback
        if self._resolver is None:
            return fallback
        param = self._parameters[param_name]
        return self._resolver.get_saved(
            self._group_name,
            param.name,
            fallback,
            param.default_value_type(),
        )

    def _get_runtime_default(self, param_name: str, fallback: ParamValue) -> ParamValue:
        """Get default value from runtime memory."""
        if param_name not in self._parameters:
            return fallback
        if self._resolver is None:
            return fallback
        param = self._parameters[param_name]
        return self._resolver.get_runtime(self._group_name, param.name, fallback)

    @abstractmethod
    def data(self) -> object:
        """Return a frozen data object with current parameter values."""
        # This will be overridden by subclasses to return specific data classes
        raise NotImplementedError("Subclasses must implement data() method")

    def get_ui_controls(self) -> dict[str, object]:  # noqa: C901, PLR0912, PLR0915
        """Generate and return UI controls for all parameters in this group."""
        try:
            from PySide.QtWidgets import (
                QCheckBox,
                QComboBox,
                QDoubleSpinBox,
                QPushButton,
            )
        except ImportError:
            # Fallback if GUI is not available
            return {}

        controls = {}

        # Get UI descriptors from the parameter group
        ui_descriptors = self.ui_descriptors()

        for param_name, ui_field in ui_descriptors.items():
            # Handle compound params specially
            if ui_field.control_type == "compound":
                cp = self._compound_params[param_name]
                values = {name: self.get_value(name) for name in cp.expanded_names()}
                control = cp.build_control(values)
                controls[param_name] = control
                continue

            param = self._parameters[param_name]
            default_value = self.get_value(param_name)

            if ui_field.control_type == "checkbox":
                control = QCheckBox()
                if isinstance(default_value, bool):
                    control.setChecked(default_value)
            elif ui_field.control_type == "spinbox":
                # Use QSpinBox for IntParam, QDoubleSpinBox for FloatParam
                if isinstance(param, IntParam):
                    from PySide.QtWidgets import QSpinBox
                    control = QSpinBox()
                    if param.min_value is not None:
                        control.setMinimum(param.min_value)
                    elif param.positive_only:
                        control.setMinimum(1)
                    else:
                        control.setMinimum(-999999)
                    if param.max_value is not None:
                        control.setMaximum(param.max_value)
                    else:
                        control.setMaximum(999999)
                    try:
                        control.setValue(int(default_value))
                    except (TypeError, ValueError):
                        control.setValue(0)
                else:
                    control = QDoubleSpinBox()
                    # Handle min/max values safely for numeric params
                    if isinstance(param, FloatParam):
                        if param.min_value is not None:
                            try:
                                control.setMinimum(float(param.min_value))
                            except (TypeError, ValueError):
                                control.setMinimum(0)
                        else:
                            control.setMinimum(0)
                        if param.max_value is not None:
                            try:
                                control.setMaximum(float(param.max_value))
                            except (TypeError, ValueError):
                                control.setMaximum(999999)
                        else:
                            control.setMaximum(999999)
                    else:
                        control.setMinimum(0)
                        control.setMaximum(999999)
                    try:
                        control.setValue(float(default_value))
                    except (TypeError, ValueError):
                        control.setValue(0.0)
            elif ui_field.control_type == "combo":
                control = QComboBox()
                if isinstance(param, LiteralParam) and param.choices:
                    control.addItems(param.choices)
                    if str(default_value) in param.choices:
                        control.setCurrentText(str(default_value))
            elif ui_field.control_type == "button":
                control = QPushButton("Edit Layout...")
                # Store current layout value on the button for retrieval
                control.setProperty("layout_value", default_value)

                # Create click handler that opens layout dialog
                def make_handler(btn: QPushButton) -> None:
                    def on_click() -> None:
                        from freecad.gridfinity_workbench import custom_shape

                        current = btn.property("layout_value")
                        result = custom_shape.custom_bin_dialog([], current)
                        if result is not None:
                            btn.setProperty("layout_value", result.layout)

                    btn.clicked.connect(on_click)

                make_handler(control)
            else:
                # Default to spinbox
                control = QDoubleSpinBox()
                try:
                    control.setValue(
                        float(default_value) if isinstance(default_value, int | float) else 0,
                    )
                except (TypeError, ValueError):
                    control.setValue(0.0)

            controls[param_name] = control

        return controls

    def update_from_ui_controls(self, controls: dict[str, Any]) -> None:
        """Update parameter values from UI controls.

        Args:
            controls: Dict mapping param_name to Qt widget controls.

        """
        try:
            from PySide.QtWidgets import (
                QCheckBox,
                QComboBox,
                QDoubleSpinBox,
                QPushButton,
                QSpinBox,
            )
        except ImportError:
            return

        for param_name, control in controls.items():
            # Handle compound params specially
            if param_name in self._compound_params:
                cp = self._compound_params[param_name]
                values = cp.read_control(control)
                for expanded_name, value in values.items():
                    self.set_value(expanded_name, value)
                continue

            if param_name not in self._parameters:
                continue
            param = self._parameters[param_name]

            if isinstance(control, QCheckBox):
                value = control.isChecked()
            elif isinstance(control, QDoubleSpinBox | QSpinBox):
                raw_value = control.value()
                # For FloatParam, convert to Quantity
                if isinstance(param, FloatParam):
                    value = fc.Units.Quantity(raw_value, param.default().Unit)
                else:
                    value = int(raw_value) if isinstance(param, IntParam) else raw_value
            elif isinstance(control, QComboBox):
                value = control.currentText()
            elif isinstance(control, QPushButton) and isinstance(param, LayoutParam):
                # For layout buttons, get the stored layout value
                value = control.property("layout_value")
            else:
                continue

            self.set_value(param_name, value)

    def build_ui(
        self,
        layout: QLayout | None = None,
        section_title: str = "",
        show_description: bool = True,  # noqa: FBT001, FBT002
    ) -> tuple[dict[str, object], QWidget | None]:
        """Build UI for this parameter group.

        Args:
            layout: Optional layout to add the UI to
            section_title: Title to display for the section (empty string means no title)
            show_description: Whether to show descriptions/notes

        Returns:
            tuple: (controls_dict, widget) where controls_dict maps parameter names to UI controls
                   and widget is the container widget

        Side effects:
            Populates self._error_displays with ParamErrorDisplay for each parameter.

        """
        try:
            from PySide.QtWidgets import QFormLayout, QLabel, QVBoxLayout, QWidget
        except ImportError:
            # Fallback if GUI is not available
            return {}, None

        _ = show_description  # Reserved for future use

        # Initialize error displays storage
        self._error_displays: dict[str, ParamErrorDisplay] = {}

        widget = QWidget()
        container_layout = QVBoxLayout(widget)

        # Add section title if provided
        if section_title:
            section_label = QLabel(section_title)
            style = "font-weight: bold;"
            section_label.setStyleSheet(style)
            container_layout.addWidget(section_label)

        # Create form layout for the parameters
        form_layout = QFormLayout()
        form_layout.setContentsMargins(20, 0, 0, 0)

        # Generate controls for this group
        controls = self.get_ui_controls()

        # Add each control to the form layout with error label support
        ui_descriptors = self.ui_descriptors()
        for param_name, control in controls.items():
            if param_name not in ui_descriptors:
                continue

            # Create a container for control + error label
            field_container = QWidget()
            field_layout = QVBoxLayout(field_container)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(2)

            # Add the control widget
            field_layout.addWidget(control)  # type: ignore[arg-type]

            # Create hidden error label below the control
            error_label = QLabel("")
            error_label.hide()
            field_layout.addWidget(error_label)

            # Store error display for this param
            self._error_displays[param_name] = ParamErrorDisplay(
                control=control,  # type: ignore[arg-type]
                error_label=error_label,
            )

            form_layout.addRow(ui_descriptors[param_name].label, field_container)

        container_layout.addLayout(form_layout)

        # If a layout was provided, add our widget to it
        if layout:
            layout.addWidget(widget)

        return controls, widget

    def render_errors(self, errors: list[ValidationError]) -> None:
        """Render validation errors under the affected parameter controls.

        Call this after validate() to display errors in the UI.
        Clears errors for parameters not in the error list.

        Args:
            errors: List of ValidationError from validate().

        """
        if not hasattr(self, "_error_displays"):
            return

        # Build mapping from expanded param names to compound param names
        expanded_to_compound: dict[str, str] = {}
        for cp_name, cp in self._compound_params.items():
            for expanded_name in cp.expanded_names():
                expanded_to_compound[expanded_name] = cp_name

        error_dict = validation_errors_to_dict(errors)
        compound_errors = map_errors_to_compound_params(error_dict, expanded_to_compound)

        for param_name, display in self._error_displays.items():
            if param_name in compound_errors:
                display.show_error(compound_errors[param_name])
            else:
                display.clear_error()

    def connect_control_signals(
        self, controls: dict[str, object], callback: Callable[[], None]
    ) -> None:
        """Connect all control signals to a callback for change notifications.

        Handles both regular controls and compound param controls.

        Args:
            controls: Dict mapping param names to Qt widget controls.
            callback: Function to call when any value changes.

        """
        try:
            from PySide.QtWidgets import (
                QCheckBox,
                QComboBox,
                QDoubleSpinBox,
                QSpinBox,
            )
        except ImportError:
            return

        for param_name, control in controls.items():
            # Handle compound params
            if param_name in self._compound_params:
                cp = self._compound_params[param_name]
                cp.connect_signals(control, callback)  # type: ignore[arg-type]
                continue

            # Handle regular controls
            if isinstance(control, QDoubleSpinBox | QSpinBox):
                control.valueChanged.connect(lambda *_: callback())
            elif isinstance(control, QCheckBox):
                control.stateChanged.connect(lambda *_: callback())
            elif isinstance(control, QComboBox):
                control.currentIndexChanged.connect(lambda *_: callback())


class ParameterValidationError(Exception):
    """Exception raised when parameter validation fails.

    Contains a list of ValidationError instances.
    Useful for bubbling validation failures up to UI or logging.
    """

    def __init__(self, errors: list[ValidationError]) -> None:
        """Initialize validation error with list of ValidationError instances."""
        self.errors = errors
        messages = [err.message for err in errors]
        super().__init__(
            f"{len(errors)} parameter validation error(s): {'; '.join(messages)}",
        )


ControlType = Literal["spinbox", "checkbox", "combo", "textbox", "button", "compound"]


class UIField:
    """UI descriptor metadata for a single parameter.

    Generated automatically by ParameterGroup.ui_descriptors() based on
    parameter types. Used by UI builders to create appropriate widgets.

    Attributes:
    - control_type: Widget type ("spinbox", "checkbox", "combo", "textbox", "button")
    - label: Display label from param.display_name
    - param_name: Internal parameter identifier
    - min_val/max_val/step: Optional numeric constraints
    - group: Logical grouping for layout organization

    """

    def __init__(  # noqa: PLR0913
        self,
        control_type: ControlType,
        label: str,
        param_name: str,
        min_val: float | None = None,
        max_val: float | None = None,
        step: float | None = None,
        group: str = "general",
    ) -> None:
        """Initialize UI field descriptor with control type and metadata."""
        self.control_type = control_type
        self.label = label
        self.param_name = param_name
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self.group = group


class CombinedParams:
    """Combines multiple ParameterGroups into a unified interface.

    Use CombinedParams when a FreeCAD object needs parameters from multiple
    logical groups (e.g., BaseplateParams + MagnetHoleParams + ScrewHoleParams).

    Key responsibilities:
    1. **Unified FreeCAD Integration**:
       - from_obj() / to_obj(): Delegates to all contained groups
       - add_all_properties_to_object(): Adds properties from all groups

    2. **Cross-Group Parameter Access**:
       - get_value(param_name): Searches all groups for the parameter
       - set_value(param_name, value): Sets value in the owning group
       - param_exists(): Check if a parameter exists in any group

    3. **Hierarchical Validation**:
       - validate(): Runs validation on all groups, prefixes errors with group name

    4. **Combined UI Generation**:
       - build_ui(): Builds UI for all parameter groups
       - UI control keys are prefixed as "group_name__param_name"

    5. **Serialization**:
       - to_ui_payload() / from_ui_payload(): Nested dicts keyed by group name

    Groups are accessible as attributes (e.g., combined.fundamentals.grid_units_x).
    """

    def __init__(self, **param_groups: ParameterGroup) -> None:
        """Initialize combined params with named parameter groups."""
        self._param_groups = param_groups
        # Dynamically add accessors for each group
        for name, group in param_groups.items():
            setattr(self, name, group)

    def from_obj(self, obj: fc.DocumentObject) -> CombinedParams:
        """Extract all parameter groups from FreeCAD object."""
        new_groups = {}
        for name, group in self._param_groups.items():
            if hasattr(group, "from_obj"):
                new_groups[name] = group.from_obj(obj)
            else:
                new_groups[name] = group  # Keep unchanged if no from_obj method
        new_combined = self.__class__(**new_groups)
        # Preserve error displays if they exist (for UI error rendering)
        if hasattr(self, "_error_displays"):
            new_combined._error_displays = self._error_displays  # noqa: SLF001
        return new_combined

    def to_obj(self, obj: fc.DocumentObject) -> None:
        """Apply all parameter groups to FreeCAD object and update MEM defaults."""
        for group in self._param_groups.values():
            if hasattr(group, "to_obj"):
                group.to_obj(obj)

    def validate(self) -> list[ValidationError]:
        """Validate all parameter groups with hierarchical validation.

        Returns:
            List of ValidationError instances with group-prefixed param keys.
            E.g., "baseplate_size.filler_top_enabled" for params in baseplate_size group.

        """
        errors: list[ValidationError] = []
        for group_name, group in self._param_groups.items():
            if hasattr(group, "validate"):
                group_errors = group.validate()
                # Prefix param keys with group name
                for err in group_errors:
                    prefixed_params = tuple(
                        f"{group_name}.{param}" for param in err.affected_params
                    )
                    errors.append(
                        ValidationError(message=err.message, affected_params=prefixed_params)
                    )
        return errors

    def ui_descriptors(self) -> dict[str, dict[str, UIField]]:
        """Return UI descriptors for all parameter groups."""
        descriptors = {}
        for name, group in self._param_groups.items():
            if hasattr(group, "ui_descriptors"):
                descriptors[name] = group.ui_descriptors()
        return descriptors

    def to_ui_payload(self) -> dict[str, dict[str, Any]]:
        """Return nested UI payload keyed by group names."""
        payload: dict[str, dict[str, Any]] = {}
        for group_name, group in self._param_groups.items():
            if hasattr(group, "to_ui_payload"):
                payload[group_name] = group.to_ui_payload()
        return payload

    def from_ui_payload(self, payload: dict[str, dict[str, Any]]) -> None:
        """Apply nested UI payload keyed by group names."""
        for group_name, group_payload in payload.items():
            group = self._param_groups.get(group_name)
            if group is not None and hasattr(group, "from_ui_payload"):
                group.from_ui_payload(group_payload)

    def apply_to_ui_controls(self, controls_by_key: dict[str, Any]) -> None:
        """Apply values to controls keyed as `group__param`."""
        payload = self.to_ui_payload()
        for group_name, group_payload in payload.items():
            for param_name, value in group_payload.items():
                control = controls_by_key.get(f"{group_name}__{param_name}")
                if control is None or not hasattr(control, "setValue"):
                    continue
                control.setValue(value)

    def apply_to_ui_owner(self, owner: object) -> None:
        """Apply values to UI owner attributes keyed as `group__param`."""
        payload = self.to_ui_payload()

        # Track which params are handled by compound params
        compound_handled: set[str] = set()

        # First, apply compound param values
        for group_name, group in self._param_groups.items():
            if not hasattr(group, "_compound_params"):
                continue
            group_payload = payload.get(group_name, {})
            for cp_name, cp in group._compound_params.items():  # noqa: SLF001
                control = getattr(owner, f"{group_name}__{cp_name}", None)
                if control is None:
                    continue
                # Build values dict from payload for compound param's expanded names
                values = {name: group_payload.get(name) for name in cp.expanded_names()}
                # Apply to compound control's child widgets
                self._apply_compound_values(control, cp, values)
                compound_handled.update(cp.expanded_names())

        # Then apply regular param values
        for group_name, group_payload in payload.items():
            for param_name, value in group_payload.items():
                if param_name in compound_handled:
                    continue  # Already handled by compound param
                control = getattr(owner, f"{group_name}__{param_name}", None)
                if control is None:
                    continue
                if hasattr(control, "setChecked"):
                    control.setChecked(bool(value))
                elif hasattr(control, "setValue"):
                    control.setValue(value)

    def _apply_compound_values(
        self, control: object, cp: ParamCombination, values: dict[str, ParamValue]
    ) -> None:
        """Apply values to a compound control's child widgets."""
        try:
            from PySide.QtWidgets import QCheckBox, QDoubleSpinBox
        except ImportError:
            return

        for child in control.children():  # type: ignore[union-attr]
            if isinstance(child, QCheckBox):
                enabled_val = values.get(cp.expanded_names()[0], False)
                child.setChecked(bool(enabled_val))
            elif isinstance(child, QDoubleSpinBox):
                quantity_val = values.get(cp.expanded_names()[1], 0)
                child.setValue(float(quantity_val))

    def update_from_ui_controls(self, controls_by_key: dict[str, object]) -> None:
        """Update parameters from controls keyed as `group__param`."""
        payload: dict[str, dict[str, ParamValue]] = {}
        for group_name, group in self._param_groups.items():
            if not hasattr(group, "_parameters"):
                continue
            group_payload: dict[str, ParamValue] = {}

            # Handle compound params first
            if hasattr(group, "_compound_params"):
                for cp_name, cp in group._compound_params.items():  # noqa: SLF001
                    control = controls_by_key.get(f"{group_name}__{cp_name}")
                    if control is not None:
                        values = cp.read_control(control)
                        group_payload.update(values)

            # Handle regular params
            for param_name in group._parameters:  # noqa: SLF001
                if param_name in group_payload:
                    continue  # Already handled by compound param
                control = controls_by_key.get(f"{group_name}__{param_name}")
                if control is None:
                    continue
                if hasattr(control, "isChecked"):
                    group_payload[param_name] = control.isChecked()
                elif hasattr(control, "value"):
                    group_payload[param_name] = control.value()
            payload[group_name] = group_payload
        self.from_ui_payload(payload)

    def update_from_ui_owner(self, owner: object) -> None:
        """Update parameters from UI owner attributes keyed as `group__param`."""
        payload: dict[str, dict[str, ParamValue]] = {}
        for group_name, group in self._param_groups.items():
            if not hasattr(group, "_parameters"):
                continue
            group_payload: dict[str, ParamValue] = {}

            # Handle compound params first
            if hasattr(group, "_compound_params"):
                for cp_name, cp in group._compound_params.items():  # noqa: SLF001
                    control = getattr(owner, f"{group_name}__{cp_name}", None)
                    if control is not None:
                        values = cp.read_control(control)
                        group_payload.update(values)

            # Handle regular params
            for param_name, param in group._parameters.items():  # noqa: SLF001
                if param_name in group_payload:
                    continue  # Already handled by compound param
                control = getattr(owner, f"{group_name}__{param_name}", None)
                if control is None:
                    continue
                # Check for layout_value property first (QPushButton for LayoutParam)
                if isinstance(param, LayoutParam) and hasattr(control, "property"):
                    layout_val = control.property("layout_value")
                    group_payload[param_name] = layout_val  # Can be None
                elif type(control).__name__ == "QCheckBox":
                    group_payload[param_name] = control.isChecked()
                elif hasattr(control, "value"):
                    group_payload[param_name] = control.value()
            payload[group_name] = group_payload
        self.from_ui_payload(payload)

    def get_all_values(self) -> dict[str, ParamValue]:
        """Get all values from all parameter groups."""
        all_values: dict[str, ParamValue] = {}
        for group_name, group in self._param_groups.items():
            if hasattr(group, "defaults"):
                all_values.update({f"{group_name}.{k}": v for k, v in group.defaults().items()})
            # Also try getting actual values if available
            if hasattr(group, "_values"):
                for param_name, value in group._values.items():  # noqa: SLF001
                    all_values[f"{group_name}.{param_name}"] = value
        return all_values

    def get_value(self, param_name: str) -> ParamValue:
        """Get value for a parameter by searching through all subgroups."""
        for group in self._param_groups.values():
            if hasattr(group, "_parameters") and param_name in group._parameters:  # noqa: SLF001
                return group.get_value(param_name)

        # If parameter not found in any subgroup, raise an exception
        available_params = []
        for group_name, group in self._param_groups.items():
            if hasattr(group, "_parameters"):
                available_params.extend(
                    [f"{group_name}.{pname}" for pname in group._parameters],  # noqa: SLF001
                )
        raise KeyError(
            f"Parameter '{param_name}' not found in any subgroup. "
            f"Available parameters: {available_params}",
        )

    def set_value(self, param_name: str, value: ParamValue) -> None:
        """Set value for a parameter by searching through all subgroups."""
        for group in self._param_groups.values():
            if hasattr(group, "_parameters") and param_name in group._parameters:  # noqa: SLF001
                group.set_value(param_name, value)
                return

        # If parameter not found in any subgroup, raise an exception
        available_params = []
        for group_name, group in self._param_groups.items():
            if hasattr(group, "_parameters"):
                available_params.extend(
                    [f"{group_name}.{pname}" for pname in group._parameters],  # noqa: SLF001
                )
        raise KeyError(
            f"Parameter '{param_name}' not found in any subgroup. "
            f"Available parameters: {available_params}",
        )

    def find_param_group(self, param_name: str) -> tuple[str, ParameterGroup]:
        """Find which group contains the specified parameter."""
        for group_name, group in self._param_groups.items():
            if hasattr(group, "_parameters") and param_name in group._parameters:  # noqa: SLF001
                return group_name, group
        raise KeyError(f"Parameter '{param_name}' not found in any subgroup")

    def param_exists(self, param_name: str) -> bool:
        """Check if a parameter exists in any subgroup."""
        for group in self._param_groups.values():
            if hasattr(group, "_parameters") and param_name in group._parameters:  # noqa: SLF001
                return True
        return False

    def get_param_info(self) -> dict[str, dict[str, object]]:
        """Get information about all parameters across all subgroups."""
        param_info: dict[str, dict[str, object]] = {}
        for group_name, group in self._param_groups.items():
            if hasattr(group, "_parameters"):
                group_params: dict[str, object] = {}
                for param_name, param_obj in group._parameters.items():  # noqa: SLF001
                    group_params[param_name] = {
                        "display_name": param_obj.display_name,
                        "default": param_obj.default(),
                        "type": type(param_obj).__name__,
                        "current_value": group.get_value(param_name),
                    }
                param_info[group_name] = group_params
        return param_info

    def add_all_properties_to_object(self, obj: fc.DocumentObject) -> None:
        """Add properties from all contained parameter groups to the FreeCAD object."""
        for group in self._param_groups.values():
            if hasattr(group, "add_properties_to_object"):
                group.add_properties_to_object(obj)

    def build_ui(
        self,
        layout: QLayout | None = None,
        section_title: str = "",
        show_description: bool = True,  # noqa: FBT001, FBT002
    ) -> tuple[dict[str, object], QWidget | None]:
        """Build UI controls for all parameter groups combined.

        Args:
            layout: Optional layout to add the UI to
            section_title: Title to display for the combined section (empty string means no title)
            show_description: Whether to show descriptions/notes

        Returns:
            tuple: (controls_dict, widget) where controls_dict maps parameter names to UI controls
                   and widget is the container widget

        Side effects:
            Populates self._error_displays with aggregated ParamErrorDisplay from all groups,
            using prefixed keys like "group_name.param_name".

        """
        try:
            from PySide.QtWidgets import QLabel, QVBoxLayout, QWidget
        except ImportError:
            # Fallback if GUI is not available
            return {}, None

        # Initialize aggregated error displays storage
        self._error_displays: dict[str, ParamErrorDisplay] = {}

        widget = QWidget()
        container_layout = QVBoxLayout(widget)

        # Add section title if provided
        if section_title:
            section_label = QLabel(section_title)
            style = "font-weight: bold;"
            section_label.setStyleSheet(style)
            container_layout.addWidget(section_label)

        # Build UI for each parameter group
        all_controls = {}
        for group_name, group in self._param_groups.items():
            if hasattr(group, "build_ui"):
                # Use group's section_title property if available
                group_title = getattr(group, "section_title", "")
                group_controls, group_widget = group.build_ui(None, group_title, show_description)
                # Prefix control names with group name
                for param_name, control in group_controls.items():
                    all_controls[f"{group_name}__{param_name}"] = control

                # Aggregate error displays with prefixed keys (using . separator)
                if hasattr(group, "_error_displays"):
                    for param_name, display in group._error_displays.items():  # noqa: SLF001
                        self._error_displays[f"{group_name}.{param_name}"] = display

                # Add the group widget to our container
                if group_widget is not None:
                    container_layout.addWidget(group_widget)

        # If a layout was provided, add our widget to it
        if layout:
            layout.addWidget(widget)

        return all_controls, widget

    def connect_control_signals(
        self, controls: dict[str, object], callback: Callable[[], None]
    ) -> None:
        """Connect all control signals to callback across all parameter groups.

        Delegates to each group's connect_control_signals method, filtering
        controls by group prefix. Control keys must be in "group_name__param_name" format.

        Args:
            controls: Dict mapping prefixed param names to Qt widget controls.
            callback: Function to call when any value changes.

        """
        for group_name, group in self._param_groups.items():
            # Filter controls for this group (keys are "group_name__param_name")
            prefix = f"{group_name}__"
            group_controls = {
                key[len(prefix):]: ctrl
                for key, ctrl in controls.items()
                if key.startswith(prefix)
            }
            if group_controls and hasattr(group, "connect_control_signals"):
                group.connect_control_signals(group_controls, callback)

    def render_errors(self, errors: list[ValidationError]) -> None:
        """Render validation errors under the affected parameter controls.

        Call this after validate() to display errors in the UI.
        Clears errors for parameters not in the error list.

        Args:
            errors: List of ValidationError from validate(). Keys should be
                prefixed like "group_name.param_name".

        """
        if not hasattr(self, "_error_displays"):
            return

        # Build mapping from expanded param names to compound param names
        # Keys are like "group_name.expanded_name" -> "group_name.compound_name"
        expanded_to_compound: dict[str, str] = {}
        for group_name, group in self._param_groups.items():
            if hasattr(group, "_compound_params"):
                for cp_name, cp in group._compound_params.items():  # noqa: SLF001
                    for expanded_name in cp.expanded_names():
                        expanded_to_compound[f"{group_name}.{expanded_name}"] = (
                            f"{group_name}.{cp_name}"
                        )

        error_dict = validation_errors_to_dict(errors)
        compound_errors = map_errors_to_compound_params(error_dict, expanded_to_compound)

        for param_key, display in self._error_displays.items():
            if param_key in compound_errors:
                display.show_error(compound_errors[param_key])
            else:
                display.clear_error()


class ParamConverter:
    """Utility class for converting between FreeCAD objects and parameter instances.

    Provides static methods for common conversion patterns:
    - obj_to_params(): Create a parameter instance from a FreeCAD object
    - params_to_obj(): Apply parameter values to a FreeCAD object
    - validate_params(): Run validation on a parameter instance

    Use this for generic conversion when the param class is determined dynamically.
    """

    @staticmethod
    def obj_to_params(obj: fc.DocumentObject, param_class: type) -> ParameterGroup:
        """Convert FreeCAD object to parameter class instance."""
        if hasattr(param_class, "from_obj"):
            return param_class().from_obj(obj)
        raise ValueError(f"Parameter class {param_class} does not have a from_obj method")

    @staticmethod
    def params_to_obj(
        params_instance: ParameterGroup | CombinedParams,
        obj: fc.DocumentObject,
    ) -> None:
        """Apply parameter instance values back to FreeCAD object."""
        if hasattr(params_instance, "to_obj"):
            params_instance.to_obj(obj)
        else:
            raise ValueError(
                f"Parameter instance {type(params_instance)} does not have a to_obj method",
            )

    @staticmethod
    def validate_params(
        params_instance: ParameterGroup | CombinedParams,
    ) -> list[ValidationError]:
        """Validate parameter instance values."""
        if hasattr(params_instance, "validate"):
            return params_instance.validate()
        return []


class ParamSystemRouter:
    """Router that maps FreeCAD object types to their parameter classes.

    Examines the object's Proxy class name to determine which CombinedParams
    class should be used. This enables generic code to work with any Gridfinity
    object without hardcoding the parameter class.

    Example:
        params = ParamSystemRouter.route_obj_to_params(baseplate_obj)
        # Returns CombinedBaseplateParams populated from the object

    Supported object types:
    - ConnectingClip -> CombinedConnectingClipsParams
    - Baseplate -> CombinedBaseplateParams
    - StackedBaseplates -> CombinedStackedBaseplatesParams
    - Default fallback -> FundamentalsParams

    """

    @staticmethod
    def route_obj_to_params(obj: fc.DocumentObject) -> ParameterGroup | CombinedParams:
        """Route to appropriate param conversion based on object type."""
        from .param import (
            CombinedBaseplateParams,
            CombinedConnectingClipsParams,
            CombinedStackedBaseplatesParams,
            FundamentalsParams,
        )

        proxy = getattr(obj, "Proxy", None)

        if proxy and hasattr(proxy, "__class__"):
            class_name = proxy.__class__.__name__

            if class_name == "ConnectingClip":
                return CombinedConnectingClipsParams().from_obj(obj)
            if class_name == "Baseplate":
                return CombinedBaseplateParams().from_obj(obj)
            if class_name == "StackedBaseplates":
                return CombinedStackedBaseplatesParams().from_obj(obj)

        # Default fallback - return fundamentals
        return FundamentalsParams().from_obj(obj)

    @staticmethod
    def route_params_to_obj(
        params_instance: ParameterGroup | CombinedParams,
        obj: fc.DocumentObject,
    ) -> None:
        """Route to appropriate param application based on param type."""
        if hasattr(params_instance, "to_obj"):
            params_instance.to_obj(obj)


def get_current_param_system(obj: fc.DocumentObject) -> ParameterGroup | CombinedParams:
    """Get parameters using appropriate system for the given object.

    Convenience function that routes through ParamSystemRouter.
    Returns a CombinedParams or ParameterGroup instance populated from obj.
    """
    return ParamSystemRouter.route_obj_to_params(obj)


def apply_param_system(
    params_instance: ParameterGroup | CombinedParams,
    obj: fc.DocumentObject,
) -> None:
    """Apply parameters using appropriate system for the given param instance.

    Convenience function that routes through ParamSystemRouter.
    Writes parameter values back to the FreeCAD object properties.
    """
    ParamSystemRouter.route_params_to_obj(params_instance, obj)
