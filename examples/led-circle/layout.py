import math
import yaml

# The number of LEDs
N_LEDS = 10
# The radius to place them (mm)
RADIUS = 12
# If true, LEDs are rotated to be tangent to the circle
ROTATE = True
# If true, place the LEDs on the bottom
BOTTOM = True
# Specifies the x, y coordinate of the center of the circle
ORIGIN = [200, 80]

components = {}

for n in range(N_LEDS):
    refdes = f"D{n+1}"
    # Split the circle up into N equal segments (think pizza slices here)
    dTheta = 2 * math.pi / N_LEDS
    # Place LEDs around the circle, every dTheta radians
    theta = n * dTheta
    # The rounding isn't strictly necessary, but I like that it makes the files more readable
    # and we don't need better than um position resolution for our LEDs! 
    x = round(RADIUS * math.sin(theta), 3)
    y = round(RADIUS * math.cos(theta), 3)

    # theta is in radians, but yaml file rotation value must be written in degrees
    if ROTATE:
        rotation = 180 + theta * 180 / math.pi
    else:
        rotation = 0

    components[refdes] = { 
        'location': [x, y],
        'flip': BOTTOM,
        'rotation': rotation,
    }


layout = {
    'origin': ORIGIN,
    'components': components,
}

with open('layout.yaml', 'w') as f:
    f.write(yaml.safe_dump(layout, default_flow_style=None))