"""Allows controlling the location and footprint assignment of components from a 
layout.yaml file

Example file: 

    origin: [x0, y0] # Offset applied to all component locations
    components:
        R1: 
            location: [x, y] # mm
            rotation: [r] # degrees
            flipped: false
            footprint: 
                path: path/to/library.pretty
                name: SomeFootprint
        J1: 
            ...

All the fields are optional for each component (e.g. leave footprint unspecified 
to leave the footprint unchanged)

The footprint path is relative to the directory containing the KiCad PCB file.
"""
import logging
import pcbnew
import os
import sys
import yaml
try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

import os.path
import traceback
import wx
import wx.lib.filebrowsebutton as FBB


WIDGET_SPACING = 5

logger = logging.getLogger(__name__)

# Interface changed between 5.x and 6.x, but we will support either
v5_compat = pcbnew.GetBuildVersion().startswith('5')
# Handle change in 6.x development branch
# NOTE: Some builds enclose the version string in parentheses,
# so leading parens are removed
# TODO: One day this might be released, and that will break this. But
# I don't know when, so we'll just have to wait and see...
use_vector2 = pcbnew.GetBuildVersion().lstrip('(').startswith('6.99')


if hasattr(wx, "GetLibraryVersionInfo"):
    WX_VERSION = wx.GetLibraryVersionInfo()  # type: wx.VersionInfo
    WX_VERSION = (WX_VERSION.Major, WX_VERSION.Minor, WX_VERSION.Micro)
else:
    # old kicad used this (exact version doesn't matter)
    WX_VERSION = (3, 0, 2)


class StreamToLogger(object):
   """
   Fake file-like stream object that redirects writes to a logger instance.
   """
   
   def __init__(self, logger, log_level=logging.INFO):
      self.logger = logger
      self.log_level = log_level
      self.linebuf = ''
 
   def write(self, buf):
      for line in buf.rstrip().splitlines():
         self.logger.log(self.log_level, line.rstrip())


def debug_dialog(msg, exception=None):
    """Show a debug message in a dialog window."""
    
    logger.error(msg)
    if exception:
        msg = "\n".join((msg, str(exception), traceback.format_exc()))
    dlg = wx.MessageDialog(None, msg, "", wx.OK)
    dlg.ShowModal()
    dlg.Destroy()


def get_project_directory():
    """Return the path of the PCB directory."""
    
    return os.path.dirname(os.path.abspath(pcbnew.GetBoard().GetFileName()))


def get_layout():
    """Return dict with component layout info for export to YAML file."""
    
    logger.info("Extracting component layout info from PCB.")

    pcb = pcbnew.GetBoard()

    layout = dict()
    layout["components"] = dict()
    for mod in pcb.GetFootprints():
        props = dict()
        props['flip'] = mod.IsFlipped()
        props['rotation'] = mod.GetOrientationDegrees()
        pos = mod.GetPosition()
        x = pcbnew.Iu2Millimeter(pos.x)
        y = pcbnew.Iu2Millimeter(pos.y)
        props['location'] = [x, y]
        # TODO: Store footprint path and name.
        layout["components"][mod.GetReference()] = props
    return layout


def apply_layout(layout):
    """Apply dict with component layout info to PCB."""

    logger.info("Applying layout to PCB components.")

    pcb = pcbnew.GetBoard()

    try:
        x0, y0 = layout['origin']
    except KeyError:
        x0, y0 = 0.0, 0.0
    
    if not 'components' in layout:
        logger.warning("No components field found in YAML.")

    for refdes, props in layout.get('components', {}).items():
        if v5_compat:
            mod = pcb.FindModuleByReference(refdes)
        else:
            mod = pcb.FindFootprintByReference(refdes)
        if mod is None:
            logger.warning("Did not find component {} in PCB design".format(refdes))
            continue
        
        flip = props.get('flip', False) # Generally, flip means put on the bottom
        
        if 'footprint' in props:
            # I think there's no API to map the library nickname to a library
            # (e.g. using the global and project libraries) so path is passed in.
            # I also see no way to find the path from which the footprint was 
            # previously found, so we're only comparing the name. This should
            # be good enough in pretty much all cases, but it is a bit ugly.
            footprint_path = os.path.join(projdir, props['footprint']['path'])
            footprint_name = props['footprint']['name']
            
            if mod.GetFPID().GetUniStringLibId() != footprint_name:
                # As far as I can tell, you can't change the footprint of a module, you have to delete and re-add
                # Save important properties of the existing module
                ref = mod.GetReference()
                pads = list(mod.Pads())
                nets = [p.GetNet() for p in pads]
                value = mod.GetValue()

                newmod = pcbnew.FootprintLoad(footprint_path, footprint_name)
                if newmod is None:
                    logging.error("Failed to load footprint {} from {}".format(footprint_name, footprint_path))
                    raise RuntimeError("Failed to load footprint %s from %s" % (footprint_name, footprint_path))
                pcb.Remove(mod)

                # Restore original props to the new module
                newmod.SetReference(ref)
                for p, net in zip(pads, nets):
                    p.SetNet(net)
                newmod.SetValue(value)
                pcb.Add(newmod)
                mod = newmod
            
        if 'location' in props:
            x, y = props['location']

            ## Latest needs a pcbnew.VECTOR2I, 6.0.1 needs wxPoint
            if use_vector2:
                mod.SetPosition(pcbnew.VECTOR2I_MM(x0 + x, y0 + y))
            else:
                mod.SetPosition(pcbnew.wxPointMM(x0 + x, y0 + y))
        
        if flip ^ (mod.IsFlipped()):
            if v5_compat:
                mod.Flip(mod.GetPosition())
            else:
                mod.Flip(mod.GetPosition(), False)
        
        if 'rotation' in props:
            rotation = props['rotation']
            mod.SetOrientationDegrees(rotation)

    pcbnew.Refresh()


class ImportExportDialog(wx.Dialog):
    """Class for getting filenames for import/export of component placement."""

    def __init__(self, *args, **kwargs):
        logger.info("Instantiating import/export dialog.")
        try:
            wx.Dialog.__init__(
                self,
                None,
                id=wx.ID_ANY,
                title=u"Import/Export Component Placement",
                pos=wx.DefaultPosition,
                size=wx.Size(500, 100),
                style=wx.CAPTION
                | wx.CLOSE_BOX
                | wx.DEFAULT_DIALOG_STYLE
                | wx.RESIZE_BORDER,
            )

            panel = wx.Panel(self)

            # File browser widget for selecting import/export file.
            self.import_export_file_picker = FBB.FileBrowseButton(
                parent=panel,
                labelText="File:",
                buttonText="Browse",
                toolTip="Browse for file or enter file name.",
                dialogTitle="Select file to import/export part placement",
                startDirectory=get_project_directory(),
                initialValue="",
                fileMask="Part Placement File|*.yaml|All Files|*.*",
                fileMode=wx.FD_OPEN,
                size=wx.Size(500, 50)
            )

            # Buttons to select import/export/cancel operations.
            self.import_btn = wx.Button(panel, label="Import")
            self.export_btn = wx.Button(panel, label="Export")
            self.cancel_btn = wx.Button(panel, label="Cancel")
            self.import_btn.Bind(wx.EVT_BUTTON, self.do_import, self.import_btn)
            self.export_btn.Bind(wx.EVT_BUTTON, self.do_export, self.export_btn)
            self.cancel_btn.Bind(wx.EVT_BUTTON, self.cancel, self.cancel_btn)

            # Horizontal sizer for buttons.
            btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
            btn_sizer.AddSpacer(WIDGET_SPACING)
            btn_sizer.Add(self.import_btn, flag=wx.ALL | wx.ALIGN_CENTER)
            btn_sizer.AddSpacer(WIDGET_SPACING)
            btn_sizer.Add(self.export_btn, flag=wx.ALL | wx.ALIGN_CENTER)
            btn_sizer.AddSpacer(WIDGET_SPACING)
            btn_sizer.Add(self.cancel_btn, flag=wx.ALL | wx.ALIGN_CENTER)
            btn_sizer.AddSpacer(WIDGET_SPACING)

            # Create a vertical sizer to hold everything in the panel.
            sizer = wx.BoxSizer(wx.VERTICAL)
            sizer.Add(self.import_export_file_picker, 0, wx.ALL | wx.EXPAND, WIDGET_SPACING)
            sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_CENTER, WIDGET_SPACING)

            # Size the panel.
            panel.SetSizer(sizer)
            panel.Layout()
            panel.Fit()

            # Finally, size the frame that holds the panel.
            self.Fit()

            # Show the dialog.
            self.ShowModal()

        except Exception as e:
            debug_dialog("Failed to instantiate import/export dialog.", e)

    def do_import(self, evt):
        """Import YAML from file and apply to PCB layout."""

        import_file_name = self.import_export_file_picker.GetValue()
        if not import_file_name:
            debug_dialog("You need to select a file to import the component layout!")
        else:
            try:
                if not os.path.isabs(import_file_name):
                    import_file_name = os.path.join(get_project_directory(), import_file_name)
                with open(import_file_name, r"r") as fp:
                    logger.info(f"Importing layout from {import_file_name}")
                    layout = yaml.load(fp.read(), Loader)
                    apply_layout(layout)
            except Exception as e:
                debug_dialog(f"Failed to read {import_file_name}!!", e)
        self.Destroy()

    def do_export(self, evt):
        """Get component layout and export to YAML file."""

        export_file_name = self.import_export_file_picker.GetValue()
        if not export_file_name:
            debug_dialog("You need to select a file to store the exported component layout!")
        else:
            try:
                if not os.path.isabs(export_file_name):
                    export_file_name = os.path.join(get_project_directory(), export_file_name)
                with open(export_file_name, r"w") as fp:
                    logger.info(f"Exporting layout from {export_file_name}")
                    layout = get_layout()
                    yaml.dump(layout, fp, Dumper)
            except Exception as e:
                debug_dialog(f"Failed to write {export_file_name}!!", e)
        self.Destroy()

    def cancel(self, evt):
        self.Destroy()


class ComponentLayout(pcbnew.ActionPlugin):
    """
    Uses data in layout.yaml (location in your kicad project directory) to layout footprints
    """

    buttons = False  # Buttons currently not installed in toolbar.

    def defaults( self ):
        self.name = "Load/store component placement."
        self.category = "Modify PCB"
        self.description = "Import/export component placement from/to a YAML file."
        self.show_toolbar_button = True

    def Run( self ):
        projdir = get_project_directory()

        filehandler = logging.FileHandler(os.path.join(projdir, "component_layout_plugin.log"))
        filehandler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s %(name)s %(lineno)d:%(message)s')
        filehandler.setFormatter(formatter)
        # The log setup is persistent across plugin runs because the kicad python 
        # kernel keeps running, so clear any existing handlers to avoid multiple 
        # outputs
        while len(logger.handlers) > 0:
            logger.removeHandler(logger.handlers[0])
        logger.addHandler(filehandler)
        logger.setLevel(logging.DEBUG)

        logger.info('Logging to {}...'.format(os.path.join(projdir, "component_layout_plugin.log")))
        
        logger.info("Executing component_layout_plugin")
        
        # Redirect stdout and stderr to logfile
        stdout_logger = logging.getLogger('STDOUT')
        sl_out = StreamToLogger(stdout_logger, logging.INFO)
        sys.stdout = sl_out

        stderr_logger = logging.getLogger('STDERR')
        sl_err = StreamToLogger(stderr_logger, logging.ERROR)
        sys.stderr = sl_err

        ImportExportDialog()

ComponentLayout().register()
