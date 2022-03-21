# coding=utf-8
# (C) Copyright 2022 Jindrich Sestak (xsesta05)
# Licenced under MIT.
# Part of diploma thesis.
# Content: File with mesh logic

import uasyncio as asyncio
import machine
import time
from network import AUTH_WPA_WPA2_PSK
from src.net import Net, ESP
from src.espmsg import Advertise, ObtainCreds, RootElected, ClaimChild, ClaimChildRes, NodeFail, pack_message, unpack_message
from src.utils import init_button
from src.ucrypto.hmac import HMAC, compare_digest, new


"""
Base core class responsible for sending and signing of messages.
"""
class BaseCore:
    BROADCAST = b'\xff\xff\xff\xff\xff\xff'
    DEBUG = True

    def __init__(self, creds=b''):
        # Network and ESPNOW interfaces.
        self.ap = Net(1)        # Access point interface.
        self.ap_essid = AP_WIFI_NAME
        self.ap_password = AP_WIFI_PASSWORD    
        self.ap_authmode = AUTH_WPA_WPA2_PSK   # WPA/WPA2-PSK mode.
        self.ap.config(essid=self.ap_essid, password=self.ap_password, authmode=self.ap_authmode, hidden=0)
        self.sta = Net(0)       # Station interface
        self.esp = ESP()
        self._loop = asyncio.get_event_loop()
        self.creds = creds

    def send_msg(self, peer=None, msg: "espmsg.class" = ""):
        """
        Create message from class object and send it through espnow.
        """
        packed_msg = pack_message(msg) # Creates byte-like string.
        digest_hash = self.sign_message(packed_msg)
        signed_msg = packed_msg + digest_hash
        self.esp.send(peer, signed_msg)
        return signed_msg

    def sign_message(self, msg):
        """
        Sign message with HMAC hash from sha256(by default) only if credentials are available.
        """
        if not self.creds:
            return ''
        mac = HMAC(self.creds, msg)
        digest_hash = mac.digest()
        return digest_hash

    def verify_sign(self, msg, msg_digest):
        """
        Check if the digest match with the same credentials. If not drop packet.
        """
        my_digest  = self.sign_message(msg)
        return compare_digest(my_digest, msg_digest)


    def dprint(self, *args):
        if self.DEBUG:
            print(*args)