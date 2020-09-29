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

        logger.info(f'Logging to {os.path.join(projdir, "component_layout_plugin.log")}...')
        
        with open(os.path.join(projdir, 'layout.yaml')) as f:
            layout = yaml.load(f.read())
        
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
            mod = pcb.FindModuleByReference(refdes)
            if mod is None:
                logger.warning(f"Did not find component {refdes} in PCB design")
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
                        logging.error(f"Failed to load footprint {footprint_name} from {footprint_path}")
                        raise RuntimeError("Failed to load footprint %s from %s" % (footprint_name, footprint_path))
                    pcb.Delete(mod)

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
                mod.SetPosition(pcbnew.wxPointMM(x0 + x, y0 + y))
            
            if flip and not mod.IsFlipped():
                mod.Flip(mod.GetPosition())
            if not flip and mod.IsFlipped():
                mod.Flip(mod.GetPosition())
            
            if 'rotation' in props:
                rotation = props['rotation']
                mod.SetOrientationDegrees(rotation)
            

ComponentLayout().register()
