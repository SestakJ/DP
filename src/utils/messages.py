# coding=utf-8
# (C) Copyright 2022 Jindřich Šesták (xsesta05)
# Licenced under Apache License.
# Part of diploma thesis.
# Content: Messages class definition for ESP-NOW and WI-FI, packing and unpacking.

import gc
import json
import struct

try:
    import uasyncio as asyncio
    from ubinascii import hexlify, unhexlify
    import ucryptolib
except Exception:
    import asyncio
    from binascii import hexlify, unhexlify

gc.collect()

DEBUG = False


def dprint(*args):
    if DEBUG:
        print(*args)


### Messages on ESP-NOW protocol layer.
class Esp_Type:
    ADVERTISE = 1
    OBTAIN_CREDS = 2
    SEND_WIFI_CREDS = 3
    ROOT_ELECTED = 4


# Periodic advertisment to the broadcast
class Advertise:
    type = Esp_Type.ADVERTISE

    def __init__(self, iid, cntr, rssi, tree_root_elected: bool, ttl: int):
        self.id = iid
        self.mesh_cntr = cntr
        self.rssi = rssi
        self.tree_root_elected = tree_root_elected
        self.ttl = ttl

    async def process(self, core: "EspnowCore"):
        core.on_advertise(self)

    def __repr__(self):
        return f"Node_ID: {self.id} Centrality: {self.mesh_cntr} " + \
               f"RSSI: {self.rssi} IsRoot {self.tree_root_elected} TTL: {self.ttl}"


"""
Handshake protocol for exchange of credentials:
Client                              Server
--------------------------------------------
SYN -->>                            
                                    ADD_PEER(LMK)
                              <<--  SYN_ACK
ADD_PEER(LMK)
OBTAIN -->>                         
                              <<--  RESPOND
[[SAVE_CREDENTIALS]]
DEL_PEER()
UNREQ_SYN -->>                      
                                    DEL_PEER()
"""


class ObtainCreds:
    type = Esp_Type.OBTAIN_CREDS
    SYN = 0
    SYN_ACK = 1  # For add_peer on the other side.
    OBTAIN = 2
    RESPOND = 3
    UNREG = 4

    def __init__(self, aflag, asrc_addr, creds=32 * b'\x00'):
        self.aflag = aflag
        self.asrc_addr = asrc_addr
        self.creds = creds

    async def process(self, core: "EspnowCore"):
        instruction = ObtainCreds_methods.get(self.aflag, None)
        if instruction:
            return instruction(self, core)

    def __repr__(self):
        return f"Cred: {self.creds} Flag {self.aflag} Srcaddr {self.asrc_addr}"

    def register_server(self, core):
        core.esp.add_peer(self.asrc_addr, core.esp_lmk, encrypt=True)
        core.send_creds(self.SYN_ACK, 32 * b'\x00')  # BUT send via Broadcast.

    def register_client(self, core):
        core.esp.add_peer(self.asrc_addr, core.esp_lmk, encrypt=True)
        core.send_creds(self.OBTAIN, 32 * b'\x00', peer=self.asrc_addr)

    def exchange_creds(self, core):
        core.send_creds(self.RESPOND, core.creds, peer=self.asrc_addr)  # Send Credentials.

    def unregister_syn(self, core):
        core.creds = self.creds  # Save credentials
        core.send_creds(self.UNREG, 32 * b'\x00', peer=self.asrc_addr)
        core.esp.del_peer(self.asrc_addr)

    def unregister(self, core):
        core.esp.del_peer(self.asrc_addr)


ObtainCreds_methods = {
    ObtainCreds.SYN: ObtainCreds.register_server,
    ObtainCreds.SYN_ACK: ObtainCreds.register_client,
    ObtainCreds.OBTAIN: ObtainCreds.exchange_creds,
    ObtainCreds.RESPOND: ObtainCreds.unregister_syn,
    ObtainCreds.UNREG: ObtainCreds.unregister
}


# For sending ciphered credentials to child nodes to connect to WiFi
class SendWifiCreds:
    type = Esp_Type.SEND_WIFI_CREDS

    def __init__(self, dst_node, length_essid, essid, passwd, key=None):
        self.adst_node = dst_node
        self.bessid_length = length_essid
        self.cessid = essid  # It has 16 chars because it is already encrypted by AES.
        self.zpasswd = passwd  # It has 16 chars because it is already encrypted by AES.

    async def process(self, core: "EspnowCore"):
        core.on_send_wifi_creds(self)


class RootElected(Advertise):
    type = Esp_Type.ROOT_ELECTED

    async def process(self, core: "EspnowCore"):
        await asyncio.sleep(0.30)


ESP_PACKETS = {
    Esp_Type.ADVERTISE: (Advertise, "!6sffBi"),
    Esp_Type.OBTAIN_CREDS: (ObtainCreds, "!B6s32s"),
    Esp_Type.SEND_WIFI_CREDS: (SendWifiCreds, "!6sh16s16s"),
    Esp_Type.ROOT_ELECTED: (RootElected, "!6shf"),
}


# Pack msg into bytes.
def pack_espmessage(obj):
    klass, pattern = ESP_PACKETS[obj.type]
    msg = struct.pack('B', obj.type) + struct.pack(pattern, *[x[1] for x in sorted(obj.__dict__.items())])
    dprint("pack_espmessage: ", msg)
    return msg


# Unpack received message from bytes into Object and process message.
async def unpack_espmessage(msg, core: "EspnowCore"):
    msg_type = msg[0]
    klass, pattern = ESP_PACKETS[msg_type]
    obj = klass(*struct.unpack(pattern, msg[1:]))
    dprint("unpack_espmessage: ", pattern, obj)
    await obj.process(core)
    return obj


### WIFI messages for mesh
# In JSON with structure:
# {'src':'\xxx',
# 'dst' : '\xxx',
# 'flag': Num,
# 'msg' : Payload
# }

class WIFIMSG:
    TOPOLOGY_PROPAGATE = 1
    TOPOLOGY_CHANGED = 2
    CLAIM_CHILD_REQUEST = 3
    CLAIM_CHILD_RESPONSE = 4
    APP = 5


class WifiMSGBase:
    def __init__(self, src, dst):
        self.packet = {"src": src, "dst": dst}


class TopologyPropagate(WifiMSGBase):
    """
    Sends root periodically to all other nodes.
    """
    type = WIFIMSG.TOPOLOGY_PROPAGATE

    def __init__(self, src, dst, topology, flag=WIFIMSG.TOPOLOGY_PROPAGATE):
        super().__init__(src, dst)
        self.packet["flag"] = flag
        self.packet["msg"] = topology

    async def process(self, wificore: "wificore.WifiCore"):
        wificore.on_topology_propagate(self)

    def __repr__(self):
        return f'SRC: {self.packet["src"]} DST: {self.packet["dst"]} ' + \
               f'flag: {self.packet["flag"]} MSG {self.packet["msg"]}'


class TopologyChanged(WifiMSGBase):
    """
    Nodes send update when new node have been added or some node failed down. Sends to root and root then propagates.
    """
    type = WIFIMSG.TOPOLOGY_CHANGED

    def __init__(self, src, dst, my_topology, flag=WIFIMSG.TOPOLOGY_CHANGED):
        super().__init__(src, dst)
        self.packet["flag"] = flag
        self.packet["msg"] = my_topology

    async def process(self, wificore: "wificore.WifiCore"):
        wificore.on_topology_changed(self)


class AppMessage(WifiMSGBase):
    type = WIFIMSG.APP

    def __init__(self, src, dst, app_msg, flag=WIFIMSG.APP):
        super().__init__(src, dst)
        self.packet["flag"] = flag
        self.packet["msg"] = app_msg

    async def process(self, wificore: "wificore.WifiCore"):
        app = wificore.app
        wificore.loop.create_task(app.process(self))


WIFI_PACKETS = {
    WIFIMSG.TOPOLOGY_PROPAGATE: TopologyPropagate,
    WIFIMSG.TOPOLOGY_CHANGED: TopologyChanged,
    WIFIMSG.APP: AppMessage
}


# Prepare WiFi message to be sent
def pack_wifimessage(obj):
    j = json.dumps(obj.packet)
    return j


# Unpack received WiFi message and process it.
async def unpack_wifimessage(msg, core: "wificore.WifiCore"):
    d = json.loads(msg)
    klass = WIFI_PACKETS[d["flag"]]
    obj = klass(d["src"], d["dst"], d["msg"])
    await obj.process(core)
    return obj


async def main():
    idn = b'\xff\xff\xff\xff\xff\xa0'  # machine.unique_id()
    cntr = 1452
    rssi = -74.2
    ad = Advertise(idn, cntr, rssi, True, 1)
    msg = pack_espmessage(ad)
    print(f"Advertise message {ad}")
    tmpmsg = await unpack_espmessage(msg, None)
    print(tmpmsg)

if __name__ == "__main__":
    asyncio.run(main())
