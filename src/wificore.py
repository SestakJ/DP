# coding=utf-8
# (C) Copyright 2022 Jindřich Šesták (xsesta05)
# Licenced under Apache License.
# Part of diploma thesis.
# Content: File with WiFi logic

import gc

gc.collect()
from src.utils.net import Net

gc.collect()
from src.utils.messages import WIFI_PACKETS, TopologyPropagate, TopologyChanged, \
    pack_wifimessage, unpack_wifimessage, WIFIMSG

gc.collect()
from src.espnowcore import EspNowCore

gc.collect()
from src.utils.tree import Tree, TreeNode, json_to_tree, get_level

gc.collect()

from src.utils.oled_display import SSD1306_SoftI2C

import uasyncio as asyncio
import json
from ubinascii import hexlify, unhexlify
from network import AUTH_WPA_WPA2_PSK, STA_IF, AP_IF
import urandom
import machine

gc.collect()

# Constants
DEFAULT_S = const(7)
BEACON_S = const(15)
SERVER_PORT = const(1234)
CHILDREN_COUNT = const(2)  # Number of maximum children for each node.
ROUTER_PORT_FOR_USER = const(4321)
USER_MAC = "ff0000000000"
# User defined file.
CONFIG_FILE = 'config.json'


def mac_to_str(mac: bytes):
    return hexlify(mac, ':').replace(b':', b'').decode()


def str_to_mac(s: str):
    return unhexlify(s)


def lower_mac_by_one(mac: str):
    lower_by_one = int(mac, 16) - 1
    return hex(lower_by_one)[2:]


async def mem_info():
    while True:
        print(f"Allocated memory:{gc.mem_alloc()} free memory: {gc.mem_free()}")
        await asyncio.sleep(3)


class WifiCore:

    def __init__(self, app: "BlinkApp"):
        self.app = app
        with open(CONFIG_FILE) as f:
            self.config = json.loads(f.read())
        self.DEBUG = self.config.get("WifiConfig", 0)
        self.wifi_ssid = self.wifi_password = None
        self.wifi_channel = 1
        wifi = self.config.get("WIFI", None)
        if wifi:
            self.wifi_ssid = wifi[0]
            self.wifi_password = wifi[1]
            self.wifi_channel = wifi[2]
        # Network interfaces.
        self.ap = Net(AP_IF, self.wifi_channel)  # Access point interface.
        self.sta = Net(STA_IF, self.wifi_channel)  # Station interface
        self.core = EspNowCore(self.config, self.ap, self.sta)  # EspNowCore with ESP-NOW module
        self.loop = self.core.loop
        self.sta.wlan.disconnect()
        self.ap_essid = self.core.ap_essid
        self.ap_password = self.core.ap_password
        self.sta_ssid = self.sta_password = None
        self.ap_authmode = AUTH_WPA_WPA2_PSK  # WPA/WPA2-PSK mode.

        # Node definitions.
        self.id = mac_to_str(self.core.id)
        # Sockets and tree topology. 
        self.children_writers = {}  # {mac: (writer, (ip, port))}
        self.parent = self.parent_reader = self.parent_writer = None

        self.tree_topology = None
        self.routing_table = {}  # Routing for descendants, everything else is transmitted to parent

    def dprint(self, *args):
        if self.DEBUG:
            print(*args)

    def start(self):
        """
        Blocking start of firmware core.
        """
        print(f"\nStart WifiCore: node ID: {self.id}")
        try:
            self.core.start()  # Run ESPNOW core.
            self.loop.create_task(mem_info())
            self.loop.create_task(self.oled_info())
            self.loop.create_task(self._run())
        except Exception as e:  # Every except raises exception meaning that the task is broken, reset whole device
            asyncio.run(self.close_all())
            print(f"Error in WifiCore {e}")
            machine.reset()  # It solves the problem with ERROR 104 ECONNRESET after Soft Reset on child.

    async def _run(self):
        """ Starting points in the mesh. Additional task created in called functions. """
        # Node must open socket to parent node on station interface, then start its own AP interface. 
        # Otherwise, socket would bind to AP interface.
        await self.connect()
        self.loop.create_task(self.start_parenting_server())

    def am_i_root(self):
        return mac_to_str(self.core.root) == self.id

    async def oled_info(self):
        SoftI2C = machine.SoftI2C(scl=machine.Pin(23), sda=machine.Pin(18))
        oled_width = 128
        oled_height = 32
        oled = SSD1306_SoftI2C(oled_width, oled_height, SoftI2C)
        while True:
            oled.text(f"ID:{self.id}", 0, 0)
            oled.text(f"Par:{self.parent}", 0, 10)
            if self.am_i_root() and self.sta.isconnected():
                oled.text(f"IP {self.sta.ifconfig()[0]}", 0, 20)
            elif self.tree_topology:
                oled.text(f"Depth {get_level(self.tree_topology.search(self.id))}", 0, 20)
            oled.show()
            await asyncio.sleep(3)
            oled.fill(0)

    async def connect(self):
        """
        When received send_wifi_creds from parent -> connect to parent AP and open connection with socket to him.
        Or when node is the root node -> create Tree topology (connect to the WiFI router)
        Create tasks for communication to parent.
        """
        while not (self.core.sta_ssid or mac_to_str(
                self.core.root) == self.id):  # Either on_send_wifi_creds received or is root node.
            await asyncio.sleep(DEFAULT_S)
        self.core.DEBUG = False  # Stop Debug messages in EspnowCore
        self.sta.wlan.disconnect()  # Disconnect from any previously connected Wi-Fi.
        if self.core.sta_ssid:  # Has ssid to parent WIFI which was received in EspNowCore.
            await self.connect_to_parent()
        elif self.am_i_root():  # Node is root node. Create Topology with itself on top.
            await self.connect_to_router()

    async def connect_to_parent(self):
        """Connects to parent node and creates socket connection."""
        self.sta_ssid = self.core.sta_ssid
        self.sta_password = self.core.sta_password
        try:
            await asyncio.wait_for(self.sta.do_connect(self.sta_ssid, self.sta_password),
                                   15)  # Wait to connect only 15s.
            print("[Connect to parent WiFi] Done")
            self.parent_reader, self.parent_writer = await asyncio.open_connection(self.sta.ifconfig()[2], SERVER_PORT)
            print("[Open connection to parent] Done")
            self.loop.create_task(self.send_beacon_to_parent())
            self.loop.create_task(self.listen_to_parent())
        except:
            machine.reset()

    async def connect_to_router(self):
        """Only the root node connects to the WiFi router and open port for user to connect to."""
        if self.wifi_ssid:  # If is wifi defined in config, connect to it.
            try:
                await asyncio.wait_for(self.sta.do_connect(self.wifi_ssid, self.wifi_password), 15)
                print(f"[Connect to WiFi router {self.wifi_ssid}] Done")
                await asyncio.start_server(self.listen_to_user, '0.0.0.0', ROUTER_PORT_FOR_USER)
                print(f"[Socket to WiFi router {self.wifi_ssid}] Done")
            except TimeoutError:
                print(f"[Connect to WiFi router {self.wifi_ssid}] TimeoutError - not connected")
        tree = Tree()
        tree.root = TreeNode(self.id, None)
        self.tree_topology = tree
        return

    async def listen_to_user(self, reader, writer):
        """Listen for users commands."""
        # Mimic the user socket as normal child socket. This could work without any further changes,
        res = await reader.read(100)
        msg = json.loads(res)
        addr = writer.get_extra_info('peername')
        print(f"Received {res} from {addr}")
        self.loop.create_task(self.process_message(res, msg["src"]))
        self.children_writers[USER_MAC] = (writer, addr)
        # self.loop.create_task(self.topology_propagate(USER_MAC, writer))  # Send topology to user if you want.
        self.loop.create_task(self.on_message(reader, USER_MAC))

    async def send_beacon_to_parent(self):
        """ Send blank messages to parent for him to save my MAC addr and beacon to him."""
        msg = TopologyPropagate(self.id, "parent", None)
        while True:
            self.dprint("[SEND] to parent")
            await self.send_msg(self.parent, self.parent_writer, msg)
            await asyncio.sleep(BEACON_S)

    async def listen_to_parent(self):
        self.parent = await self.register_mac(self.parent_reader)  # Register peer with mac address
        self.loop.create_task(self.on_message(self.parent_reader, self.parent))

    async def start_parenting_server(self):
        """
        Create own WiFi AP and start server for listening for children to connect.
        """
        self.ap.config(essid=self.ap_essid, password=self.ap_password, authmode=self.ap_authmode, hidden=0)
        while not self.ap.wlan.active():
            await asyncio.sleep(DEFAULT_S)
        print("[START SERVER]")
        try:
            await self.in_tree_topology()  # Either root node has created topology or must wait for parent to send topology.
            await asyncio.start_server(self.listen_to_children, '0.0.0.0', SERVER_PORT)
            self.loop.create_task(self.claim_children())
        except Exception as e:
            print("[Start Server] error: ", e)
            raise e

    async def in_tree_topology(self):
        while not self.tree_topology:  # Received Tree topology from parent node.
            await asyncio.sleep(1)
        while not self.tree_topology.search(self.id):  # Received updated Tree topology from parent node.
            await asyncio.sleep(1)
        return True

    async def listen_to_children(self, reader, writer):
        """
        Must update tree topology first. The topology has to be received earlier from its parent.
        Add new node and inform root about topology change.
        Create task to send periodic update to each new child.
        """
        mac = await self.register_mac(reader)  # Register peer with mac address.
        self.children_writers[mac] = (writer, writer.get_extra_info('peername'))
        my_node = self.tree_topology.search(self.id)
        new_child = TreeNode(mac, my_node)
        self.tree_topology.search(self.id).add_child(new_child)
        self.dprint("[Receive] child added: ", mac, writer.get_extra_info('peername'))
        await self.topology_changed(self.tree_topology.root.data, self.parent_writer, mac)
        self.loop.create_task(self.topology_propagate(mac, writer))  # Send topology to each child
        self.dprint("[Receive new child] tree changed ", self.tree_topology.pack())
        self.loop.create_task(self.on_message(reader, mac))

    async def topology_propagate(self, child_mac, writer):
        """ Periodically propagate tree topology to child node."""
        msg = TopologyPropagate(self.id, child_mac, None)
        tree = self.tree_topology
        tree_pack = self.tree_topology.pack
        all_children = self.children_writers
        while child_mac in all_children:
            msg.packet["msg"] = self.tree_topology.pack() if self.tree_topology else None
            self.loop.create_task(self.send_msg(child_mac, writer, msg))
            await asyncio.sleep(DEFAULT_S)

    async def claim_children(self):
        """
        Claim child nodes while there are some nodes present in mesh but not in the tree topology.
        """
        while True:  # neighbour_nodes are nodes with ttl value 0 (elem[1][4] == 0)
            neighbour_nodes = list(dict(filter(lambda elem: elem[1][4] == 0, self.core.neighbours.items())).keys())
            tree_nodes = []
            tree = self.tree_topology
            cnt_children = 0
            if tree:
                tmp = tree.root.get_all() + [tree.root.data]
                tree_nodes = [str_to_mac(i) for i in tmp]
                cnt_children = len(tree.search(self.id).children)
            possible_children = [mac for mac in neighbour_nodes if mac not in tree_nodes]
            if possible_children and cnt_children < CHILDREN_COUNT:
                for i in range(CHILDREN_COUNT - cnt_children):
                    self.core.claim_children([urandom.choice(possible_children)])
            await asyncio.sleep(DEFAULT_S + 3)  # Leave some time for node to connect to my WiFi.

    async def register_mac(self, reader):
        """
        Receive first blank packet to be able to register MAC address of node
        """
        new_mac = None
        while not new_mac:
            try:
                res = await reader.readline()
                msg = json.loads(res)
                if msg["flag"] == WIFIMSG.APP:  # Ignore App meseges until register MAC.
                    continue
                if res == b'':  # Connection closed by host, should not happen.
                    self.dprint("[Receive] conn is dead")
                    return
                new_mac = msg["src"]
                self.loop.create_task(self.process_message(res, msg["src"]))

            except Exception as e:
                self.dprint("[Receive] x conn is prob dead, stop listening. Error: ", e)
                return
        return new_mac

    async def on_message(self, reader, mac):
        """
        Wait for messages. Lightweight function to not block recv process. Further, processing in another coroutine.
        """
        try:
            while True:
                res = await reader.readline()
                if res == b'':  # Connection closed by host, clean up. Maybe hard reset.
                    print("[Receive] conn is dead")
                    await self.close_connection(mac)
                    return
                self.loop.create_task(
                    self.process_message(res, mac))  # Create task so this function is as fast as possible.
        except Exception as e:  # Connection closed by Parent node, clean up. Maybe hard reset
            print("[Receive] x conn is prob dead, stop listening. Error: ", e)
            await self.close_connection(mac)
            return

    async def process_message(self, msg, src_mac):
        """
        Decide what to do with messages, eventually just resend them further into the mesh.
        """
        self.dprint(f"[Processed msg] from: {src_mac} and MSG {msg}")
        # self.dprint("[Processed msg] ", msg)
        js = json.loads(msg)
        self.dprint(f'JS.dst {js["dst"]} == {self.id} ID')
        if js["dst"] == self.id:
            obj = await unpack_wifimessage(msg, self)
        elif js["dst"] == "ffffffffffff":  # Message destined to everyone. Process and resend.
            obj = await unpack_wifimessage(msg, self)
            nodes = [self.parent] + list(self.children_writers.keys())
            if src_mac:
                nodes.remove(src_mac)
            await self.send_to_nodes(msg,
                                     nodes)  # Resend broadcast to every other node you see. They will resend it also.
        elif js["dst"] == "parent":
            pass  # Message destined fo parent node from child (Beacon message, just for mac register, can drop).
        else:
            await self.resend(msg, js)

    async def resend(self, msg, js):
        routing_table = self.routing_table
        if js["dst"] in routing_table.keys():
            dst = routing_table.get(js["dst"])
            writer = self.get_writer(dst)
            await self.send_msg(dst, writer, msg)
        else:
            await self.send_msg(self.parent, self.parent_writer, msg)

    def get_writer(self, mac):
        if mac == self.parent:
            return self.parent_writer
        elif mac in self.children_writers.keys():
            return self.children_writers.get(mac)[0]
        else:
            return None

    async def send_msg(self, mac, writer, message):
        """
        Create message from class object message and send it through WiFi socket writer to mac.
        """
        if not writer:
            return
        if not self.is_peer_alive(mac):
            await self.close_connection(mac)
            return
        try:
            self.dprint("[SEND] to:", mac, " message: ", message)
            if type(message) is bytes or type(message) is str:  # Resending just string.
                writer.write(message)
            else:  # Message is object, must be packed.
                writer.write('{}\n'.format(pack_wifimessage(message)))
            await writer.drain()
            self.dprint("[SEND] drained and done")
        except Exception as e:
            print("[Send] Whew! ", e, " occurred.")
            await self.close_connection(mac)

    def is_peer_alive(self, mac):
        """ Check if peer is connected based on ESP-NOW Advertisement neighbours database.
            Mainly for deleting dead Child nodes. """
        if not mac or mac == USER_MAC:  # Blank MAC only on first send when they don't know MAC address of a peer.
            return True
        if str_to_mac(mac) in self.core.neighbours:
            return True
        else:
            return False

    async def send_to_nodes(self, msg, nodes=None):
        """ Send to directly connected nodes. Used for broadcast messages and for application.  """
        if nodes is None:
            nodes = [self.parent] + list(self.children_writers.keys())
        for node in nodes:
            writer = self.get_writer(node)
            await self.send_msg(node, writer, msg)

    async def send_to_all(self, msg):
        """ Send to every node in the mesh. Can be also used by application, But resend() adds overhead. """
        nodes = self.tree_topology.root.get_all() + [self.tree_topology.root.data]
        nodes.remove(self.id)
        for node in nodes:
            msg.packet["dst"] = node
            await self.resend(msg, msg.packet)

    def on_topology_propagate(self, topology: TopologyPropagate):
        """
        Called from message.py. Save tree topology only from parent node.
        """
        if not topology.packet["msg"]:  # Topology Exchanges are blank from children as beacons
            return
        tree = Tree()
        json_to_tree(topology.packet["msg"], tree, None)

        if topology.packet["src"] == self.parent or topology.packet["src"] == self.tree_topology.root.data:
            tmp = self.tree_topology
            self.tree_topology = None
            del tmp
            self.tree_topology = tree
            self.dprint("[OnTopologyPropagate]\n", self.tree_topology)
        self.update_routing_table()

    async def topology_changed(self, node, writer, mac):
        # When new node connects or child node fails down inform just only root node.
        msg = TopologyChanged(self.id, node, {"changed_mac": mac, \
                                              "new_topology": self.tree_topology.pack()})  # Send Topology update.
        await self.send_msg(node, writer, msg)
        self.update_routing_table()

    def on_topology_changed(self, topology: TopologyChanged):
        """
        Called from message.py. Topology update is saved on root node. Root node immediately sends new topology.
        On intermediate parent node the message is processed as Topology Propagate. And immediately resends to his children.
        This way is bubbles through all the tree.
        """
        if not topology.packet["msg"]:  # and not self.id != self.tree_topology.root.data:
            return
        tree = Tree()
        if not self.tree_topology:  # If it is first packet form parent ever.
            self.dprint("[OnTopologyChanged] First topo for node \n")
            json_to_tree(topology.packet["msg"]["new_topology"], tree, None)
            self.tree_topology = tree
        elif self.id == self.tree_topology.root.data:  # Node is a root and updates tree. Already has a tree, must update him.
            self.dprint("[OnTopologyChanged] Root node updates \n")
            json_to_tree(topology.packet["msg"]["new_topology"], tree, None)
            origin_node = self.tree_topology.search(topology.packet["src"])
            if self.tree_topology.search(topology.packet["msg"]["changed_mac"]):  # It is in tree, so node is dead.
                origin_node.del_child(self.tree_topology.search(topology.packet["msg"]["changed_mac"]))
            else:  # It is not in tree, so new node was added.
                new_node = tree.search(topology.packet["msg"]["changed_mac"])
                origin_node.add_child(new_node)
        else:  # Intermediate parents updates whole tree as Topology Propagation
            self.dprint(
                "[OnTopologyChanged] Intermediate parent just drop tree and create new one in On topology propagate\n")
            self.on_topology_propagate(TopologyPropagate(topology.packet["src"], topology.packet["dst"], \
                                                         topology.packet["msg"]["new_topology"]))
        self.dprint("[OnTopologyChanged]\n", self.tree_topology)
        self.send_to_children_once({"changed_mac": topology.packet["msg"]["changed_mac"], \
                                    "new_topology": self.tree_topology.pack()})

    def send_to_children_once(self, topo_changed: dict):
        self.dprint("[SEND to children once]")
        for destination, writers in self.children_writers.items():  # writers is a tuple(stream_writer, tuple(IP, port))
            msg = TopologyChanged(self.id, destination, topo_changed)
            self.dprint(f"[SEND to children once] {destination} msg> {msg.packet}")
            self.loop.create_task(self.send_msg(destination, writers[0], msg))

    def update_routing_table(self):
        if self.tree_topology.search(self.id):
            self.routing_table = self.tree_topology.search(self.id).get_routes()

    async def close_connection(self, mac):
        writer = None
        if mac == self.parent:
            writer = self.parent_writer
            self.parent = None
            self.parent_writer = None
            self.parent_reader = None
            print("[Close connection] Parent node dead, reset itself.")
            await self.close_all()
            machine.reset()
            del self.tree_topology  # Lost connection to parent so drop whole topology.
            self.tree_topology = None
        elif mac in self.children_writers:
            writer, ip = self.children_writers[mac]
            del self.children_writers[mac]
            try:
                to_delete = self.tree_topology.search(mac)
                to_delete.parent.del_child(to_delete)  # Delete lost child from topology.
                await self.topology_changed(self.tree_topology.root.data, self.parent_writer, mac)
            except Exception as e:
                print(f"[Close connection] to child - Error:{e}")
            print("[Close connection] to child, tree changed \n", self.tree_topology)
        if writer:
            writer.close()
            await writer.wait_closed()

    async def close_all(self):
        """ Clean up function."""
        for address, writer in self.children_writers.items():
            await self.close_connection(address)
        self.children_writers.clear()
        if self.parent_writer:
            await self.close_connection(self.parent)
        print("[Clean UP of sockets] Done")


def main():
    from src.wificore import WifiCore
    c = WifiCore("blank")
    c.start()
