"""New param system for Gridfinity workbench - complete implementation with direct property mapping."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
import re
from typing import Any, Dict, Literal, Optional, Union

import FreeCAD as fc  # noqa: N813


class DefaultType(Enum):
    """Types of default values."""

    VALUE = "Value"  # Hardcoded default
    SAVED = "Saved"  # From plugin config
    MEM = "Mem"  # Runtime memory


class ParamDefaultResolver:
    """Resolver for persisted and runtime parameter defaults."""

    def get_saved(self, group_name: str, param_name: str, fallback: Any) -> Any:
        """Return persisted default for group/param pair or fallback."""
        return fallback

    def get_runtime(self, group_name: str, param_name: str, fallback: Any) -> Any:
        """Return runtime default for group/param pair or fallback."""
        return fallback


class BaseParam:
    """Base class for individual parameters with FreeCAD property mapping."""

    def __init__(
        self,
        name: str,
        display_name: str,
        property_name: str = None,
        freecad_property_type: str = "App::PropertyFloat",
        description: str = "",
        default_type: DefaultType = DefaultType.VALUE,
    ):
        self.name = name
        self.display_name = display_name
        self.property_name = property_name
        self.freecad_property_type = (
            freecad_property_type  # FreeCAD property type (e.g., "App::PropertyLength")
        )
        self.description = description
        self.group_name: str = ""
        self._default_type = default_type

    def set_group_name(self, group_name: str) -> None:
        """Attach canonical group name to this parameter."""
        self.group_name = group_name

    def default_key(self) -> str:
        """Return canonical key used by default resolvers."""
        if not self.group_name:
            raise ValueError(f"Parameter '{self.name}' is not attached to a group")
        return f"{self.group_name}.{self.name}"

    def property_name_for_group(self, group_class_name: str) -> str:
        """Generate canonical prefixed snake_case property name."""
        group_name = group_class_name.replace("Params", "")
        group_snake = re.sub(r"(?<!^)(?=[A-Z])", "_", group_name).lower()
        return f"{group_snake}_{self.name}"

    def default_type(self) -> DefaultType:
        """Return which default type this parameter uses."""
        return self._default_type

    def default(self) -> Any:
        """Return the actual default value."""
        return None

    def resolve_default(self, resolver: Optional[ParamDefaultResolver] = None) -> Any:
        """Resolve parameter default based on default type and resolver."""
        fallback = self.default()
        default_type = self.default_type()

        if default_type == DefaultType.VALUE:
            return fallback

        if default_type == DefaultType.SAVED:
            if resolver is None:
                return fallback
            return resolver.get_saved(self.group_name, self.name, fallback)

        if default_type == DefaultType.MEM:
            if resolver is None:
                return fallback
            return resolver.get_runtime(self.group_name, self.name, fallback)

        return fallback

    def validate(self, value: Any) -> bool:
        """Validate the given value."""
        return True


class BooleanParam(BaseParam):
    """Boolean parameter (e.g., enabled/disabled)."""

    def __init__(
        self,
        name: str,
        display_name: str,
        default_value: bool = False,
        property_name: str = None,
        freecad_property_type: str = "App::PropertyBool",
        description: str = "",
        default_type: DefaultType = DefaultType.VALUE,
    ):
        super().__init__(
            name,
            display_name,
            property_name,
            freecad_property_type,
            description,
            default_type,
        )
        self.default_value = default_value

    def default(self) -> bool:
        return self.default_value

    def validate(self, value: Any) -> bool:
        """Validate value is boolean."""
        return isinstance(value, bool)


class FloatParam(BaseParam):
    """Floating-point parameter, typically millimeter quantity."""

    def __init__(
        self,
        name: str,
        display_name: str,
        default_value: fc.Units.Quantity,
        min_value: Optional[fc.Units.Quantity] = None,
        max_value: Optional[fc.Units.Quantity] = None,
        property_name: str = None,
        freecad_property_type: str = "App::PropertyLength",  # Default to Length for measurements
        description: str = "",
        positive_only: bool = False,  # Whether this parameter should be positive only
        default_type: DefaultType = DefaultType.VALUE,
    ):
        super().__init__(
            name,
            display_name,
            property_name,
            freecad_property_type,
            description,
            default_type,
        )
        self.default_value = default_value
        self.min_value = min_value
        self.max_value = max_value
        self.positive_only = positive_only

    def default(self) -> fc.Units.Quantity:
        return self.default_value

    def validate(self, value: fc.Units.Quantity) -> bool:
        """Validate number is within bounds if specified and is numeric."""
        try:
            float_val = float(value)
            if self.min_value is not None and float_val < float(self.min_value):
                return False
            if self.max_value is not None and float_val > float(self.max_value):
                return False
            if self.positive_only and float_val <= 0:
                return False
            return True
        except (TypeError, ValueError):
            return False


class LiteralParam(BaseParam):
    """Literal parameter (string, choice, etc.)."""

    def __init__(
        self,
        name: str,
        display_name: str,
        default_value: str,
        choices: Optional[list[str]] = None,
        property_name: str = None,
        freecad_property_type: str = "App::PropertyString",
        description: str = "",
        default_type: DefaultType = DefaultType.VALUE,
    ):
        super().__init__(
            name,
            display_name,
            property_name,
            freecad_property_type,
            description,
            default_type,
        )
        self.default_value = default_value
        self.choices = choices

    def default(self) -> str:
        return self.default_value

    def validate(self, value: Any) -> bool:
        """Validate string is in choices if specified and is a string."""
        if not isinstance(value, str):
            return False
        if self.choices is not None and value not in self.choices:
            return False
        return True


class IntParam(BaseParam):
    """Integer parameter for count-like values."""

    def __init__(
        self,
        name: str,
        display_name: str,
        default_value: int,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
        property_name: str = None,
        freecad_property_type: str = "App::PropertyInteger",
        description: str = "",
        positive_only: bool = False,
        default_type: DefaultType = DefaultType.VALUE,
    ):
        super().__init__(
            name,
            display_name,
            property_name,
            freecad_property_type,
            description,
            default_type,
        )
        self.default_value = int(default_value)
        self.min_value = min_value
        self.max_value = max_value
        self.positive_only = positive_only

    def default(self) -> int:
        return self.default_value

    def validate(self, value: Any) -> bool:
        if isinstance(value, bool):
            return False
        if not isinstance(value, int):
            return False
        if self.min_value is not None and value < self.min_value:
            return False
        if self.max_value is not None and value > self.max_value:
            return False
        if self.positive_only and value <= 0:
            return False
        return True


class ParameterGroup(ABC):
    """Base class for parameter groups with automatic iteration and direct property mapping."""

    # Class attribute to define the category/group name for FreeCAD properties
    _category = "Gridfinity"

    def __init__(
        self,
        parameters: list[Union[BooleanParam, FloatParam, IntParam, LiteralParam]],
        resolver: Optional[ParamDefaultResolver] = None,
    ):
        self._parameters = {param.name: param for param in parameters}
        self._values = {}
        self._resolver = resolver
        self._group_name = self._compute_group_name()

        for param in self._parameters.values():
            param.set_group_name(self._group_name)

        # Dynamically create getter methods for each parameter
        for param_name in self._parameters:
            # Create method name by removing underscores
            method_name = param_name.replace("_", "")

            # Create a closure that captures the param_name
            def make_getter(pn):
                def getter(self):
                    return self.get_value(pn)

                return getter

            # Add the method to the class
            setattr(self.__class__, method_name, make_getter(param_name))

    def add_properties_to_object(self, obj: fc.DocumentObject):
        """Automatically add all parameter properties to the FreeCAD object."""
        for param_name, param in self._parameters.items():
            value = self.get_value(param_name)

            # Use provided property name or generate one based on group and parameter names
            property_name = self._property_name(param)

            # Add the property to the object using the parameter's defined property type and name
            obj.addProperty(
                param.freecad_property_type,
                property_name,
                self._category,
                param.description or f"{param.display_name} parameter",
            )

            # Set the value appropriately based on property type
            setattr(obj, property_name, value)

    def get_value(self, param_name: str) -> Any:
        """Get value for a specific parameter, handling default resolution."""
        if param_name in self._values:
            return self._values[param_name]

        param = self._parameters[param_name]
        return param.resolve_default(self._resolver)

    def set_value(self, param_name: str, value: Any):
        """Set value for a specific parameter."""
        if param_name in self._parameters:
            self._values[param_name] = value

    def set_all_values(self, values: dict[str, Any]):
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
                values[param_name] = getattr(obj, obj_property_name)

        # Create new instance with extracted values
        new_group = self.__class__()
        new_group.set_all_values(values)
        return new_group

    def apply_to_obj(self, obj: fc.DocumentObject):
        """Apply parameters to FreeCAD object using direct property mapping."""
        for param_name in self._parameters.keys():
            # Use the direct property name mapping
            obj_property_name = self._property_name(self._parameters[param_name])
            if hasattr(obj, obj_property_name):
                setattr(obj, obj_property_name, self.get_value(param_name))

    def _property_name(self, param: BaseParam) -> str:
        return param.property_name or param.property_name_for_group(self.__class__.__name__)

    def _compute_group_name(self) -> str:
        """Return canonical group key generated from class name."""
        explicit_group_key = getattr(self, "_group_name_override", None)
        if explicit_group_key:
            return explicit_group_key

        group_name = self.__class__.__name__.replace("Params", "")
        return re.sub(r"(?<!^)(?=[A-Z])", "_", group_name).lower()

    def validate(self) -> Dict[str, str]:
        """Automatically validate all parameters in this group."""
        errors = {}
        for param_name, param in self._parameters.items():
            value = self.get_value(param_name)
            if not param.validate(value):
                errors[param_name] = f"Invalid value for {param.display_name}: {value}"
        return errors

    def to_ui_payload(self) -> Dict[str, Any]:
        """Return UI-friendly payload for this parameter group."""
        payload: Dict[str, Any] = {}
        for param_name, param in self._parameters.items():
            payload[param_name] = self._to_ui_value(param, self.get_value(param_name))
        return payload

    def from_ui_payload(self, payload: Dict[str, Any]) -> None:
        """Apply UI payload values to this parameter group."""
        for param_name, ui_value in payload.items():
            if param_name not in self._parameters:
                continue
            param = self._parameters[param_name]
            self.set_value(param_name, self._from_ui_value(param, ui_value))

    def ui_descriptors(self) -> Dict[str, UIField]:
        """Automatically generate UI configuration for all parameters."""
        descriptors = {}
        for param_name, param in self._parameters.items():
            descriptors[param_name] = UIField(
                control_type=self._get_control_type(param),
                label=param.display_name,
                param_name=param_name,
                group=self.__class__.__name__.replace("Params", "").lower(),
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

    def defaults(self) -> Dict[str, Any]:
        """Automatically return all default values."""
        defaults = {}
        for param_name, param in self._parameters.items():
            defaults[param_name] = param.default()
        return defaults

    def _get_control_type(
        self, param: Union[BooleanParam, FloatParam, IntParam, LiteralParam]
    ) -> str:
        """Determine UI control type based on parameter type."""
        if isinstance(param, BooleanParam):
            return "checkbox"
        elif isinstance(param, (FloatParam, IntParam)):
            return "spinbox"
        elif isinstance(param, LiteralParam):
            return "combo" if param.choices else "textbox"
        return "textbox"

    def _to_ui_value(self, param: BaseParam, value: Any) -> Any:
        if isinstance(param, IntParam):
            return int(value)
        if isinstance(param, FloatParam):
            return float(value)
        return value

    def _from_ui_value(self, param: BaseParam, ui_value: Any) -> Any:
        if isinstance(param, IntParam):
            return int(ui_value)
        if isinstance(param, FloatParam):
            if isinstance(ui_value, fc.Units.Quantity):
                return ui_value
            return float(ui_value) * fc.Units.Quantity("1 mm")
        if isinstance(param, BooleanParam):
            return bool(ui_value)
        if isinstance(param, LiteralParam):
            return str(ui_value)
        return ui_value

    def _get_saved_default(self, param_name: str, fallback: Any) -> Any:
        """Get default value from plugin config."""
        if param_name not in self._parameters:
            return fallback
        resolver = self._resolver
        if resolver is None:
            return fallback
        param = self._parameters[param_name]
        return resolver.get_saved(param.group_name, param.name, fallback)

    def _get_runtime_default(self, param_name: str, fallback: Any) -> Any:
        """Get default value from runtime memory."""
        if param_name not in self._parameters:
            return fallback
        resolver = self._resolver
        if resolver is None:
            return fallback
        param = self._parameters[param_name]
        return resolver.get_runtime(param.group_name, param.name, fallback)

    def data(self) -> Any:
        """Return a frozen data object with current parameter values."""
        # This will be overridden by subclasses to return specific data classes
        raise NotImplementedError("Subclasses must implement data() method")


class ParameterValidationError(Exception):
    """Exception raised when parameter validation fails."""

    def __init__(self, errors: Dict[str, str]):
        self.errors = errors
        super().__init__(
            f"{len(errors)} parameter validation error(s): {'; '.join(errors.values())}"
        )


class UIField:
    """UI descriptor for a parameter."""

    def __init__(
        self,
        control_type: Literal["spinbox", "checkbox", "combo", "slider"],
        label: str,
        param_name: str,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None,
        step: Optional[float] = None,
        group: str = "general",
    ):
        self.control_type = control_type
        self.label = label
        self.param_name = param_name
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self.group = group


class CombinedParams:
    """Combines multiple parameter groups with unified interface and validation."""

    def __init__(self, **param_groups):
        self._param_groups = param_groups
        # Dynamically add accessors for each group
        for name, group in param_groups.items():
            setattr(self, name, group)

    def from_obj(self, obj: fc.DocumentObject) -> "CombinedParams":
        """Extract all parameter groups from FreeCAD object."""
        new_groups = {}
        for name, group in self._param_groups.items():
            if hasattr(group, "from_obj"):
                new_groups[name] = group.from_obj(obj)
            else:
                new_groups[name] = group  # Keep unchanged if no from_obj method
        return self.__class__(**new_groups)

    def apply_to_obj(self, obj: fc.DocumentObject) -> None:
        """Apply all parameter groups to FreeCAD object."""
        for group in self._param_groups.values():
            if hasattr(group, "apply_to_obj"):
                group.apply_to_obj(obj)

    def validate(self) -> Dict[str, str]:
        """Validate all parameter groups with hierarchical validation."""
        errors = {}
        for group_name, group in self._param_groups.items():
            if hasattr(group, "validate"):
                group_errors = group.validate()
                # Prefix errors with group name to avoid conflicts
                for param_name, error in group_errors.items():
                    errors[f"{group_name}.{param_name}"] = error
        return errors

    def ui_descriptors(self) -> Dict[str, Dict[str, UIField]]:
        """Return UI descriptors for all parameter groups."""
        descriptors = {}
        for name, group in self._param_groups.items():
            if hasattr(group, "ui_descriptors"):
                descriptors[name] = group.ui_descriptors()
        return descriptors

    def to_ui_payload(self) -> Dict[str, Dict[str, Any]]:
        """Return nested UI payload keyed by group names."""
        payload: Dict[str, Dict[str, Any]] = {}
        for group_name, group in self._param_groups.items():
            if hasattr(group, "to_ui_payload"):
                payload[group_name] = group.to_ui_payload()
        return payload

    def from_ui_payload(self, payload: Dict[str, Dict[str, Any]]) -> None:
        """Apply nested UI payload keyed by group names."""
        for group_name, group_payload in payload.items():
            group = self._param_groups.get(group_name)
            if group is not None and hasattr(group, "from_ui_payload"):
                group.from_ui_payload(group_payload)

    def apply_to_ui_controls(self, controls_by_key: Dict[str, Any]) -> None:
        """Apply values to controls keyed as `group__param`."""
        payload = self.to_ui_payload()
        for group_name, group_payload in payload.items():
            for param_name, value in group_payload.items():
                control = controls_by_key.get(f"{group_name}__{param_name}")
                if control is None or not hasattr(control, "setValue"):
                    continue
                control.setValue(value)

    def apply_to_ui_owner(self, owner: Any) -> None:
        """Apply values to UI owner attributes keyed as `group__param`."""
        payload = self.to_ui_payload()
        for group_name, group_payload in payload.items():
            for param_name, value in group_payload.items():
                control = getattr(owner, f"{group_name}__{param_name}", None)
                if control is None or not hasattr(control, "setValue"):
                    continue
                control.setValue(value)

    def update_from_ui_controls(self, controls_by_key: Dict[str, Any]) -> None:
        """Update parameters from controls keyed as `group__param`."""
        payload: Dict[str, Dict[str, Any]] = {}
        for group_name, group in self._param_groups.items():
            if not hasattr(group, "_parameters"):
                continue
            group_payload: Dict[str, Any] = {}
            for param_name in group._parameters:
                control = controls_by_key.get(f"{group_name}__{param_name}")
                if control is None or not hasattr(control, "value"):
                    continue
                group_payload[param_name] = control.value()
            payload[group_name] = group_payload
        self.from_ui_payload(payload)

    def update_from_ui_owner(self, owner: Any) -> None:
        """Update parameters from UI owner attributes keyed as `group__param`."""
        payload: Dict[str, Dict[str, Any]] = {}
        for group_name, group in self._param_groups.items():
            if not hasattr(group, "_parameters"):
                continue
            group_payload: Dict[str, Any] = {}
            for param_name in group._parameters:
                control = getattr(owner, f"{group_name}__{param_name}", None)
                if control is None or not hasattr(control, "value"):
                    continue
                group_payload[param_name] = control.value()
            payload[group_name] = group_payload
        self.from_ui_payload(payload)

    def get_all_values(self) -> Dict[str, Any]:
        """Get all values from all parameter groups."""
        all_values = {}
        for group_name, group in self._param_groups.items():
            if hasattr(group, "defaults"):
                all_values.update({f"{group_name}.{k}": v for k, v in group.defaults().items()})
            # Also try getting actual values if available
            if hasattr(group, "_values"):
                for param_name, value in group._values.items():
                    all_values[f"{group_name}.{param_name}"] = value
        return all_values

    def get_value(self, param_name: str) -> Any:
        """Get value for a parameter by searching through all subgroups."""
        for group_name, group in self._param_groups.items():
            if hasattr(group, "_parameters") and param_name in group._parameters:
                return group.get_value(param_name)

        # If parameter not found in any subgroup, raise an exception
        available_params = []
        for group_name, group in self._param_groups.items():
            if hasattr(group, "_parameters"):
                available_params.extend(
                    [f"{group_name}.{pname}" for pname in group._parameters.keys()]
                )
        raise KeyError(
            f"Parameter '{param_name}' not found in any subgroup. "
            f"Available parameters: {available_params}"
        )

    def set_value(self, param_name: str, value: Any):
        """Set value for a parameter by searching through all subgroups."""
        for group_name, group in self._param_groups.items():
            if hasattr(group, "_parameters") and param_name in group._parameters:
                group.set_value(param_name, value)
                return

        # If parameter not found in any subgroup, raise an exception
        available_params = []
        for group_name, group in self._param_groups.items():
            if hasattr(group, "_parameters"):
                available_params.extend(
                    [f"{group_name}.{pname}" for pname in group._parameters.keys()]
                )
        raise KeyError(
            f"Parameter '{param_name}' not found in any subgroup. "
            f"Available parameters: {available_params}"
        )

    def find_param_group(self, param_name: str) -> tuple[str, ParameterGroup]:
        """Find which group contains the specified parameter."""
        for group_name, group in self._param_groups.items():
            if hasattr(group, "_parameters") and param_name in group._parameters:
                return group_name, group
        raise KeyError(f"Parameter '{param_name}' not found in any subgroup")

    def param_exists(self, param_name: str) -> bool:
        """Check if a parameter exists in any subgroup."""
        for group_name, group in self._param_groups.items():
            if hasattr(group, "_parameters") and param_name in group._parameters:
                return True
        return False

    def get_param_info(self) -> Dict[str, Dict[str, Any]]:
        """Get information about all parameters across all subgroups."""
        param_info = {}
        for group_name, group in self._param_groups.items():
            if hasattr(group, "_parameters"):
                group_params = {}
                for param_name, param_obj in group._parameters.items():
                    group_params[param_name] = {
                        "display_name": param_obj.display_name,
                        "default": param_obj.default(),
                        "type": type(param_obj).__name__,
                        "current_value": group.get_value(param_name),
                    }
                param_info[group_name] = group_params
        return param_info

    def add_all_properties_to_object(self, obj: fc.DocumentObject):
        """Add properties from all contained parameter groups to the FreeCAD object."""
        for group_name, group in self._param_groups.items():
            if hasattr(group, "add_properties_to_object"):
                # Update the category to be specific to this group
                group._category = f"Gridfinity_{group_name.title()}"
                group.add_properties_to_object(obj)


def generate_ui_from_param_group(param_group: ParameterGroup):
    """
    Generate UI controls for a parameter group.

    Automatically generates UI controls based on parameter types.
    """
    try:
        from PySide.QtWidgets import (
            QCheckBox,
            QDoubleSpinBox,
            QComboBox,
            QFormLayout,
            QVBoxLayout,
            QWidget,
            QLabel,
        )
        from PySide.QtCore import Qt
    except ImportError:
        # Fallback if GUI is not available
        return {}

    controls = {}

    # Get UI descriptors from the parameter group
    ui_descriptors = param_group.ui_descriptors()

    for param_name, ui_field in ui_descriptors.items():
        param = param_group._parameters[param_name]
        default_value = param_group.get_value(param_name)

        if ui_field.control_type == "checkbox":
            control = QCheckBox()
            if isinstance(default_value, bool):
                control.setChecked(default_value)
        elif ui_field.control_type == "spinbox":
            control = QDoubleSpinBox()
            if hasattr(param, "min_value") and param.min_value is not None:
                control.setMinimum(float(param.min_value))
            else:
                control.setMinimum(ui_field.min_val or 0)
            if hasattr(param, "max_value") and param.max_value is not None:
                control.setMaximum(float(param.max_value))
            else:
                control.setMaximum(ui_field.max_val or 999999)
            control.setValue(float(default_value))
        elif ui_field.control_type == "combo":
            control = QComboBox()
            if hasattr(param, "choices") and param.choices:
                control.addItems(param.choices)
                if str(default_value) in param.choices:
                    control.setCurrentText(str(default_value))
        else:
            # Default to textbox
            control = QDoubleSpinBox()
            control.setValue(float(default_value) if isinstance(default_value, (int, float)) else 0)

        controls[param_name] = control

    return controls


def build_param_group_ui(param_group: ParameterGroup) -> QWidget:
    """
    Build a complete UI widget for a parameter group organized by sections.

    Returns a QWidget with form layout organized by parameter groups.
    """
    try:
        from PySide.QtWidgets import QFormLayout, QVBoxLayout, QWidget, QLabel
    except ImportError:
        # Fallback if GUI is not available
        return None

    widget = QWidget()
    layout = QVBoxLayout(widget)

    # Group UI fields by their group
    grouped_fields = {}
    ui_descriptors = param_group.ui_descriptors()

    for param_name, ui_field in ui_descriptors.items():
        group_name = ui_field.group
        if group_name not in grouped_fields:
            grouped_fields[group_name] = []
        grouped_fields[group_name].append((param_name, ui_field))

    # Create sections for each group
    for group_name, fields in grouped_fields.items():
        # Add section header
        header_label = QLabel(group_name.title())
        header_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(header_label)

        # Create form layout for this group
        form_layout = QFormLayout()
        form_layout.setContentsMargins(20, 0, 0, 0)

        # Get controls for this group
        controls = generate_ui_from_param_group(param_group)

        for param_name, ui_field in fields:
            if param_name in controls:
                form_layout.addRow(ui_field.label, controls[param_name])

        layout.addLayout(form_layout)

    return widget


class ParamConverter:
    """Centralized converter for handling object ↔ param conversions."""

    @staticmethod
    def obj_to_params(obj: fc.DocumentObject, param_class: type) -> Any:
        """Convert FreeCAD object to parameter class instance."""
        if hasattr(param_class, "from_obj"):
            return param_class().from_obj(obj)
        else:
            raise ValueError(f"Parameter class {param_class} does not have a from_obj method")

    @staticmethod
    def params_to_obj(params_instance: Any, obj: fc.DocumentObject) -> None:
        """Apply parameter instance values back to FreeCAD object."""
        if hasattr(params_instance, "apply_to_obj"):
            params_instance.apply_to_obj(obj)
        else:
            raise ValueError(
                f"Parameter instance {type(params_instance)} does not have an apply_to_obj method"
            )

    @staticmethod
    def validate_params(params_instance: Any) -> Dict[str, str]:
        """Validate parameter instance values."""
        if hasattr(params_instance, "validate"):
            return params_instance.validate()
        return {}


class ParamSystemRouter:
    """Router to handle object-to-param routing for different object types."""

    @staticmethod
    def route_obj_to_params(obj: fc.DocumentObject) -> Any:
        """Route to appropriate param conversion based on object type."""
        from .param import (
            CombinedBaseplateParams,
            CombinedStackedBaseplateParams,
            CombinedClipParams,
            FundamentalsParams,
        )

        proxy = getattr(obj, "Proxy", None)

        if proxy and hasattr(proxy, "__class__"):
            class_name = proxy.__class__.__name__

            if class_name == "ConnectingClip":
                return CombinedClipParams().from_obj(obj)
            elif class_name == "Baseplate":
                return CombinedBaseplateParams().from_obj(obj)
            elif class_name == "StackedBaseplates":
                return CombinedStackedBaseplateParams().from_obj(obj)

        # Default fallback - return fundamentals
        return FundamentalsParams().from_obj(obj)

    @staticmethod
    def route_params_to_obj(params_instance: Any, obj: fc.DocumentObject) -> None:
        """Route to appropriate param application based on param type."""
        if hasattr(params_instance, "apply_to_obj"):
            params_instance.apply_to_obj(obj)


def get_current_param_system(obj: fc.DocumentObject) -> Any:
    """Get parameters using appropriate system for the given object."""
    return ParamSystemRouter.route_obj_to_params(obj)


def apply_param_system(params_instance: Any, obj: fc.DocumentObject) -> None:
    """Apply parameters using appropriate system for the given param instance."""
    ParamSystemRouter.route_params_to_obj(params_instance, obj)
