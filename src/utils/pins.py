# coding=utf-8
# (C) Copyright 2022 Jindřich Šesták (xsesta05)
# Licenced under Apache License.
# Part of diploma thesis.
# Content: File with GPIO related functions.

from machine import Pin, mem32
import uasyncio as asyncio
import neopixel

import random

# In ESP32-buddy there is default LED on 25 pin and buttons on pin 0 and 32.
LED_PIN = 25
LEFT_BUTTON = 32
RIGHT_BUTTON = 0


def gpio_func_out(n):
    GPIO_FUNCn_OUT_SEL_CFG_REG = 0x3FF44530 + 0x4 * n
    return GPIO_FUNCn_OUT_SEL_CFG_REG


# Init led with neopixel library. Need to change the signal to Pin.
def init_led(pin_number=LED_PIN):
    pin = Pin(pin_number, Pin.OUT)
    n = neopixel.NeoPixel(pin, 1)
    # Getting GPIO_FUNC25_OUT_SEL_CFG_REG address
    r = gpio_func_out(LED_PIN)
    # Setting 9'th bit to 1 for inverting the IO
    #  https://www.espressif.com/sites/default/files/documentation/esp32_technical_reference_manual_en.pdf
    # page 70
    mem32[r] |= 1 << 9
    return n


# Init button and register interupt function to be called when state changed.
def init_button(pin_number=RIGHT_BUTTON, handler=None):
    push_button = Pin(pin_number, Pin.IN, Pin.PULL_UP)  # 23 number pin is input
    push_button.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=handler)
    return push_button


# Function for blinkin with led
async def blink(c=(10, 0, 0)):
    led = init_led()
    while True:
        led[0] = c
        r, g, b = c
        g = g ^ 10
        b = b ^ 10
        c = (r, g, b)
        led.write()
        await asyncio.sleep_ms(700)


# Random string generator.
_ALPHABET = 'abcdefghijklmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ123456789'


def id_generator(size=8):
    """
    Fucntion generates random string.
    """
    ret = ""
    for i in range(size):
        ret = ret + random.choice(_ALPHABET)
    return ret
