import time
import logging
import gevent
import serial
import crc


# a component is one input or output channel on a device (generally one sensor or actuator, but some sensors/actuators may have multiple channels)
class Component(object):

    def __init__(self, device):
        self.device = device
        self.name = None  # to be removed; here temporarily for compatibility with data flow system
        self.dir = None
        self.type = None
        self.model = None
        self.units = None
        self.version = '0'  # not used; here temporarily for compatibility with data flow system
        self.store_sequence = False  # not used; here temporarily for compatibility with data flow system
        self.output_value = 0

    # return information about the sensor/actuator as a dictionary
    def as_dict(self):
        return {
            'name': self.name,
            'dir': self.dir,
            'type': self.type,
            'model': self.model,
            'units': self.units,
            'version': self.version,  # not used; here temporarily for compatibility with data flow system
            'store_sequence': self.store_sequence,  # not used; here temporarily for compatibility with data flow system
        }


# a device is a board with sensors and/or actuators
class Device(object):

    def __init__(self, index):
        self.index = index
        self.id = None
        self.components = []
        self.last_message_time = time.time()


# a hub connects to multiple devices and processes data from the devices
class Hub(object):

    def __init__(self, serial_port, baud_rate=38400, debug_serial=False):
        self.devices = {}
        self.components = []
        self.input_handlers = []
        self.serial = serial.Serial(serial_port, baudrate=baud_rate, timeout=0.05)
        self.debug_serial = debug_serial

    # run functions when we receive data from a sensor
    # based on similar code from rhizo auto_devices
    def run_input_handlers(self, component, values):
        for handler in self.input_handlers:
            if hasattr(handler, 'handle_input'):  # handler is object
                handler.handle_input(component, values)
            else:  # handler is function
                handler(component, values)

    # add a function that will get called when we receive data from a sensor
    def add_input_handler(self, handler):
        self.input_handlers.append(handler)

    def start_greenlets(self):
        gevent.spawn(self.polling_loop)
        gevent.spawn(self.receiver_loop)
        gevent.spawn(self.disconnect_checker)

    def run(self):
        self.start_greenlets()
        while True:
            gevent.sleep(1.0)

    # poll devices once a second
    def polling_loop(self):
        while True:
            self.send_serial_emssage('p')
            gevent.sleep(1.0)

    # check for incoming serial messages
    def receiver_loop(self):
        while True:
            message = self.serial.readline().strip()
            if message:
                self.process_serial_message(message)
            gevent.sleep(0.1)

    # check for devices that have been unplugged
    def disconnect_checker(self):
        while True:
            gevent.sleep(1.0)
            t = time.time()
            for (index, d) in self.devices.items():
                if t - d.last_message_time > 3.5:
                    logging.debug('device %d removed' % index)
                    self.components = [c for c in self.components if c.device != d]
                    del self.devices[index]

    # send a value to an actuator
    def set_output_value(self, component, value):
        device = component.device
        component.output_value = value
        output_values = []
        for c in device.components:
            if c.dir == 'out':
                output_values.append(str(c.output_value))
        self.send_serial_emssage('%d>s:%s' % (device.index, ','.join(output_values)))

    # send a serial message to the hub I/O board (pi hat)
    def send_serial_emssage(self, message):
        checksum = crc.crc16_ccitt(message)
        if self.debug_serial:
            print('send %s|%X' % (message, checksum))
        self.serial.write('%s|%X\n' % (message, checksum))

    # process a serial message from the hub I/O board (pi hat)
    def process_serial_message(self, message):
        if self.debug_serial:
            print('recv %s' % message)

        # check checksum
        if '|' in message:
            parts = message.split('|')
            message = parts[0]
            checksum_computed = crc.crc16_ccitt(message)
            checksum_given = int(parts[1], 16)
            if checksum_computed != checksum_given:
                logging.warning('invalid checksum (computed: %x, given: %x)' % (checksum_computed, checksum_given))
                return
        else:
            logging.warning('checksum missing')
            return

        # handle message from device
        if '>' in message:

            # parse the message
            parts = message.split('>', 1)
            try:
                device_index = int(parts[0])
            except ValueError:
                return
            payload = parts[1]
            if ':' in message:
                parts = payload.split(':', 1)
                command = parts[0]
                args = parts[1]
            else:
                command = message
                args = []

            # find devices corresponding to the sender board
            device = self.devices.get(device_index)
            if device:
                device.last_message_time = time.time()

                # if values, send to handlers
                if command == 'v':
                    if device.components:
                        args = args.split(',')
                        arg_index = 0
                        for comp in device.components:
                            if comp.dir == 'in':
                                if arg_index < len(args):
                                    try:
                                        value = float(args[arg_index])  # make sure this is a numeric value (but pass it to handler as a string for now)
                                        self.run_input_handlers(comp, args[arg_index])
                                    except:
                                        pass
                                    arg_index += 1
                                else:
                                    logging.warning('received more values than input components (device %d has %d components; message: %s)' % (device_index, len(device.components), message))
                                    break
                    else:
                        logging.debug('received values for device without metadata; requesting metadata')
                        self.send_serial_emssage('%d>m' % device_index)  # request metadata for this device board

                # if metadata, store in device
                if command == 'm':
                    args = args.split(';')
                    version = args[0]
                    if version != '1':
                        logging.warning('invalid device version (%s)' % version)
                        return
                    device.id = args[1]
                    for arg in args[2:]:
                        comp_info = arg.split(',')
                        type = comp_info[1]
                        found = False
                        for c in device.components:
                            if c.type == type:
                                found = True
                                logging.debug('component with type %s already exists on device %d' % (type, device_index))
                        if not found:
                            comp = Component(device)
                            comp.dir = 'out' if comp_info[0] == 'o' else 'in'
                            comp.type = type
                            if len(comp_info) > 2:
                                comp.model = comp_info[2]
                            if len(comp_info) > 3:
                                comp.units = comp_info[3]
                            comp.name = self.assign_name(comp.type)
                            logging.debug('new component; dir: %s, type: %s, model: %s, units: %s, name: %s' % (comp.dir, comp.type, comp.model, comp.units, comp.name))
                            device.components.append(comp)
                            self.components.append(comp)
                    logging.debug('device %d has %d components' % (device_index, len(device.components)))

            # if response without device record, request meta data
            else:
                logging.debug('new device on device index %d; requesting metadata' % device_index)
                self.devices[device_index] = Device(device_index)
                self.send_serial_emssage('%d>m' % device_index)  # request metadata for this device board

    # ======== temporary functions ========
    # borrowed from auto_devices for compatibility with it; will be removed in future

    # find a component by name; each component should have a unique name
    def find_component(self, name):
        for c in self.components:
            if c.name == name:
                return c
        return None

    # assign component name based on type
    def assign_name(self, type):
        i = 2
        name = type
        while self.find_component(name):
            name = '%s %d' % (type, i)
            i += 1
        return name
