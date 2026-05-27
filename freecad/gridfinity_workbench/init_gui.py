"""Initialize workbench gui.

The file name is given by FreeCAD. FreeCAD uses this file to initialize GUI components.
"""

from collections import OrderedDict
from pathlib import Path

import FreeCAD as fc  # noqa: N813
import FreeCADGui as fcg  # noqa: N813

from . import commands
from .param import PluginSettingsParams

try:
    from FreeCADGui import Workbench
except ImportError:
    fc.Console.PrintWarning(
        "you are using the GridfinityWorkbench with an old version of FreeCAD (<0.16)\n"
        "the class Workbench is loaded, although not imported: magic\n",
    )


# Commands to register globally (available in PartDesign and other workbenches)
GRIDFINITY_COMMANDS: OrderedDict[str, commands.BaseCommand] | None = None


def get_gridfinity_commands() -> OrderedDict[str, commands.BaseCommand]:
    """Get or create the gridfinity commands dictionary."""
    global GRIDFINITY_COMMANDS  # noqa: PLW0603
    if GRIDFINITY_COMMANDS is None:
        GRIDFINITY_COMMANDS = OrderedDict(
            [
                ("CreateBinBlank", commands.CreateBinBlank()),
                ("CreateBinBase", commands.CreateBinBase()),
                ("CreateSimpleStorageBin", commands.CreateSimpleStorageBin()),
                ("CreateEcoBin", commands.CreateEcoBin()),
                ("CreatePartsBin", commands.CreatePartsBin()),
                ("CreateBaseplate", commands.CreateBaseplate()),
                ("CreateStackedBaseplates", commands.CreateStackedBaseplates()),
                ("CreateDrawerBaseplate", commands.CreateDrawerBaseplate()),
                ("CreateConnectingClip", commands.CreateConnectingClip()),
                ("CreateCustomBin", commands.DrawBin()),
                ("ChangeLayout", commands.ChangeLayout()),
                ("StandaloneLabelShelf", commands.StandaloneLabelShelf()),
                ("OpenGridfinitySettings", commands.OpenGridfinitySettings()),
            ],
        )
    return GRIDFINITY_COMMANDS


def register_gridfinity_commands() -> list[str]:
    """Register all gridfinity commands with FreeCAD.

    Returns:
        List of command names that were registered.

    """
    workbench_commands = get_gridfinity_commands()
    for command_name, command in workbench_commands.items():
        fcg.addCommand(command_name, command)
    return list(workbench_commands.keys())


def register_partdesign_toolbar() -> None:
    """Register the Gridfinity toolbar in the PartDesign workbench via FreeCAD params."""
    pd_toolbars = fc.ParamGet("User parameter:BaseApp/Workbench/PartDesignWorkbench/Toolbar")

    command_names = list(get_gridfinity_commands().keys())

    # Check if toolbar already exists
    for tb_name in pd_toolbars.GetGroups():
        tb = pd_toolbars.GetGroup(tb_name)
        if tb.GetString("Name") == "Gridfinity":
            # Update existing toolbar with any new commands
            existing_cmds = [s for s in tb.GetStrings() if s not in ["Active", "Name"]]
            missing = [cmd for cmd in command_names if cmd not in existing_cmds]
            if missing:
                fc.Console.PrintMessage(
                    f"Updating Gridfinity toolbar with new commands: {', '.join(missing)}\n"
                )
                for cmd in missing:
                    tb.SetString(cmd, "Gridfinity")
            return

    # Create new Gridfinity toolbar
    fc.Console.PrintMessage("Registering Gridfinity toolbar into PartDesign workbench...\n")
    gf_toolbar = pd_toolbars.GetGroup("Gridfinity")
    gf_toolbar.SetString("Name", "Gridfinity")

    for cmd in command_names:
        gf_toolbar.SetString(cmd, "Gridfinity")

    gf_toolbar.SetBool("Active", 1)


def unregister_partdesign_toolbar() -> None:
    """Remove the Gridfinity toolbar from the PartDesign workbench."""
    pd_toolbars = fc.ParamGet("User parameter:BaseApp/Workbench/PartDesignWorkbench/Toolbar")

    for tb_name in pd_toolbars.GetGroups():
        tb = pd_toolbars.GetGroup(tb_name)
        if tb.GetString("Name") == "Gridfinity":
            pd_toolbars.RemGroup(tb_name)
            fc.Console.PrintMessage("Removed Gridfinity toolbar from PartDesign workbench\n")
            return


ICONPATH = Path(__file__).parent / "icons"


class GridfinityWorkbench(Workbench):
    """class which gets initiated at startup of the FreeCAD GUI."""

    MenuText = "Gridfinity"

    ToolTip = "FreeCAD Gridfinity Workbench"

    Icon = str(ICONPATH / "gridfinity_workbench_icon.svg")

    def GetClassName(self) -> str:  # noqa: N802
        """Get freecad internal class name.

        Returns:
            str: c++ style class name

        """
        return "Gui::PythonWorkbench"

    def Initialize(self) -> None:  # noqa: N802
        """Initialize workbench.

        This function is called at the first activation of the workbench.
        here is the place to import all the commands.
        """
        fc.Console.PrintMessage("switching to Gridfinity Workbench\n")

        # Load and apply plugin settings (cache sizes)
        from .param import PluginSettingsParams

        plugin_settings = PluginSettingsParams()
        plugin_settings.load_saved_defaults()
        plugin_settings.apply_to_system()

        command_names = register_gridfinity_commands()

        self.appendToolbar("Gridfinity", command_names)
        self.appendMenu("Gridfinity", command_names)


fcg.addWorkbench(GridfinityWorkbench())

# Register commands globally (needed for PartDesign integration)
register_gridfinity_commands()

# Register/unregister Gridfinity toolbar in PartDesign based on settings
_plugin_settings = PluginSettingsParams()
_plugin_settings.load_saved_defaults()
if _plugin_settings.get_value("add_to_part_design"):
    register_partdesign_toolbar()
else:
    unregister_partdesign_toolbar()

fc.__unit_test__ += ["freecad.gridfinity_workbench.test_gridfinity"]
