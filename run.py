import gevent
from gevent import monkey
monkey.patch_all()
import sys
import logging
import sensaur


# get serial port from command line if specified
if len(sys.argv) > 1:
    port_name = sys.argv[1]
else:
    port_name = '/dev/ttyS0'


# display data from sensors
def input_handler(component, value):
    print component.device.id, component.type, value


# prepare logging
logging.basicConfig(format='%(message)s', level=logging.DEBUG)


# create and launch sensaur hub manager
hub = sensaur.Hub(port_name, debug_serial=True)
hub.add_input_handler(input_handler)
hub.run()
