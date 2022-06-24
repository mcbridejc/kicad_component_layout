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

class ComponentLayout(pcbnew.ActionPlugin):
    """
    Uses data in layout.yaml (location in your kicad project directory) to layout footprints
    """
    def defaults( self ):
        self.name = "Layout footprints from layout.yaml"
        self.category = "Modify PCB"
        self.description = "Move the components to match the layout.yaml file in the project diretory"
        self.show_toolbar_button = True

    def Run( self ):
        # Interface changed between 5.x and 6.x, but we will support either
        v5_compat = pcbnew.GetBuildVersion().startswith('5')
        # Handle change in 6.x development branch
        # TODO: One day this might be released, and that will break this. But
        # I don't know when, so we'll just have to wait and see...
        use_vector2 = pcbnew.GetBuildVersion().startswith('6.99')

        pcb = pcbnew.GetBoard()
        # In some cases, I have seen KIPRJMOD not set correctly here.
        #projdir = os.environ['KIPRJMOD']
        projdir = os.path.dirname(os.path.abspath(pcb.GetFileName()))

        filehandler = logging.FileHandler(os.path.join(projdir, "component_layout_plugin.log"))
        filehandler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s %(name)s %(lineno)d:%(message)s')
        filehandler.setFormatter(formatter)
        logger = logging.getLogger(__name__)
        # The log setup is persistent accross plugin runs because the kicad python 
        # kernel keeps running, so clear any existing handlers to avoid multiple 
        # outputs
        while len(logger.handlers) > 0:
            logger.removeHandler(logger.handlers[0])
        logger.addHandler(filehandler)
        logger.setLevel(logging.DEBUG)

        logger.info('Logging to {}...'.format(os.path.join(projdir, "component_layout_plugin.log")))
        
        with open(os.path.join(projdir, 'layout.yaml')) as f:
            layout = yaml.load(f.read(), Loader)
        
        logger.info("Executing component_layout_plugin")
        
        # Redirect stdout and stderr to logfile
        stdout_logger = logging.getLogger('STDOUT')
        sl_out = StreamToLogger(stdout_logger, logging.INFO)
        sys.stdout = sl_out

        stderr_logger = logging.getLogger('STDERR')
        sl_err = StreamToLogger(stderr_logger, logging.ERROR)
        sys.stderr = sl_err
        
        if 'origin' in layout:
            x0 = layout['origin'][0]
            y0 = layout['origin'][1]
        else: 
            x0 = 0.0
            y0 = 0.0
        
        if not 'components' in layout:
            logger.warning("No components field found in layout.yaml")

        for refdes, props in layout.get('components', {}).items():
            if v5_compat:
                mod = pcb.FindModuleByReference(refdes)
            else:
                mod = pcb.FindFootprintByReference(refdes)
            if mod is None:
                logger.warning("Did not find component {} in PCB design".format(refdes))
                continue
            
            flip = props.get('flipped', False) # Generally, flip means put on the bottom
            
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
                x = props['location'][0]
                y = props['location'][1]

                ## Latest needs a pcbnew.VECTOR2I, 6.0.1 needs wxPoint
                if use_vector2:
                    mod.SetPosition(pcbnew.VECTOR2I_MM(x0 + x, y0 + y))
                else:
                    mod.SetPosition(pcbnew.wxPointMM(x0 + x, y0 + y))
            
            if flip ^ (mod.IsFlipped()):
                mod.Flip(mod.GetPosition(), False)
            
            if 'rotation' in props:
                rotation = props['rotation']
                mod.SetOrientationDegrees(rotation)
            

ComponentLayout().register()
