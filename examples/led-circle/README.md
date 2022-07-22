# LED Circle Layout Example

A Kicad project with an example script for generating layout.yaml to place a number of LEDs in a circle. 

## Steps to Create

Add LEDs to your design in eeschema, and wire them up as needed, and assign them an appropriate footprint. 

Open the PCB design in pcbnew, and draw the board outline: 

- Set the grid to a 1mm so that you can easily place the circle center on a nice even grid location (0.1" is fine, if you prefer those units)
- Draw a circle centered at coordinates (200, 80) -- actually it doesn't matter where, but I recommend a nice round number for ease -- with 15mm radius on the edge.cuts layer. This defines the shape of the board.
- Run "Update PCB from Schematic" to pull in your LED footprints, and place them anywhere. 
- Create the layout.py script, and run it to generate layout.yaml in the project directory
- Run the component layout plugin in pcbnew to read positions from layout.yaml and adjust your footprints.

