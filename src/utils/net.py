# coding=utf-8
# (C) Copyright 2022 Jindřich Šesták (xsesta05)
# Licenced under Apache License.
# Part of diploma thesis.
# Content: Classes for network and esp-now interaction.

import gc

try:
    import uasyncio as asyncio
    from uasyncio import StreamReader
    import network
    from esp import espnow
except ImportError:
    import asyncio
    from asyncio import StreamReader
gc.collect()

DEBUG = True


def dprint(*args):
    if DEBUG:
        print(*args)


class Net:
    def __init__(self, mode, channel=1):
        self.mode = mode
        self.wlan = network.WLAN(self.mode)  # Create an interface
        self.wlan.active(True)
        self.wlan.config(channel=channel)

    def isconnected(self):
        return self.wlan.isconnected()

    def connect(self, ssid, password):
        return self.wlan.connect(ssid, password)

    def ifconfig(self):
        return self.wlan.ifconfig()

    def config(self, *args, **kwargs):
        return self.wlan.config(*args, **kwargs)

    async def do_connect(self, ssid, password=""):
        if self.mode == network.AP_IF:
            await self.ap_wifi(ssid, password)
        else:
            await self.sta_wifi(ssid, password)

    async def sta_wifi(self, ssid, password):
        wlan = self.wlan
        if not wlan.isconnected():
            wlan.connect(ssid, password)
            while not wlan.isconnected():
                dprint("Connecting to WIFI on STA_IF")
                await asyncio.sleep_ms(100)
        dprint("Connected on STA_IF")
        return wlan

    async def ap_wifi(self, ssid, password=""):
        wlan = self.wlan
        wlan.config(essid=ssid, password=password)  # set the ESSID of the access point
        while not wlan.active():
            await asyncio.sleep_ms(100)
        dprint("Created AP")
        return wlan


class ESP:
    def __init__(self):
        self.esp = espnow.ESPNow()
        self.esp.config(rxbuf=2048)
        self.esp.init()
        self.stream_reader = StreamReader(self.esp)

    def set_pmk(self, pmk):
        self.esp.set_pmk(pmk)

    def add_peer(self, peer, lmk=None, channel=0, ifidx=network.AP_IF, encrypt=False):
        try:
            return self.esp.add_peer(peer, lmk, channel, ifidx, encrypt)
        except OSError as e:
            if e.args[1] == 'ESP_ERR_ESPNOW_EXIST':
                pass
            else:
                raise e

    def del_peer(self, peer):
        try:
            return self.esp.del_peer(peer)
        except OSError as e:
            if e.args[1] == 'ESP_ERR_ESPNOW_NOT_FOUND':
                pass
            else:
                raise e

    def config(self, *args):
        return self.esp.config(*args)

    def send(self, peer=None, msg=""):
        if peer is None:
            return self.esp.send(msg)
        else:
            return self.esp.send(peer, msg)

    async def read(self, size):
        return await self.stream_reader.read(size)

    def irecv(self):
        return self.esp.irecv()

    def recv(self):
        return self.esp.recv()
