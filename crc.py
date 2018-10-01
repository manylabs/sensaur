# code from the rhizo project: https://github.com/rhizolab/rhizo


# an implementation of the CRC16-CCITT algorithm; assumes message is an ascii string
def crc16_ccitt(message):
    crc = 0xFFFF
    for c in message:
        crc = crc16_update(crc, ord(c))
    return crc


# an implementation of the CRC16-CCITT algorithm; assumes data is an 8-bit value
def crc16_update(crc, data):
    data = data ^ (crc & 0xFF)
    data = data ^ ((data << 4) & 0xFF)
    return (((data << 8) & 0xFFFF) | ((crc >> 8) & 0xFF)) ^ (data >> 4) ^ (data << 3)
