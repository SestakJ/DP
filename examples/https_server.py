import ubinascii as binascii
from micropython import const
from machine import Pin, mem32
import uasyncio as asyncio
import neopixel
import network
import ussl as ssl
import uasyncio as asyncio
import time


try:
    import usocket as socket
except:
    import socket

# Source codes: https://github.com/micropython/micropython/blob/master/examples/network/http_server_ssl.py
# This self-signed key/cert pair is randomly generated and to be used for
# testing/demonstration only.  You should always generate your own key/cert.
key = binascii.unhexlify(
    b"3082013b020100024100cc20643fd3d9c21a0acba4f48f61aadd675f52175a9dcf07fbef"
    b"610a6a6ba14abb891745cd18a1d4c056580d8ff1a639460f867013c8391cdc9f2e573b0f"
    b"872d0203010001024100bb17a54aeb3dd7ae4edec05e775ca9632cf02d29c2a089b563b0"
    b"d05cdf95aeca507de674553f28b4eadaca82d5549a86058f9996b07768686a5b02cb240d"
    b"d9f1022100f4a63f5549e817547dca97b5c658038e8593cb78c5aba3c4642cc4cd031d86"
    b"8f022100d598d870ffe4a34df8de57047a50b97b71f4d23e323f527837c9edae88c79483"
    b"02210098560c89a70385c36eb07fd7083235c4c1184e525d838aedf7128958bedfdbb102"
    b"2051c0dab7057a8176ca966f3feb81123d4974a733df0f958525f547dfd1c271f9022044"
    b"6c2cafad455a671a8cf398e642e1be3b18a3d3aec2e67a9478f83c964c4f1f"
)
cert = binascii.unhexlify(
    b"308201d53082017f020203e8300d06092a864886f70d01010505003075310b3009060355"
    b"0406130258583114301206035504080c0b54686550726f76696e63653110300e06035504"
    b"070c075468654369747931133011060355040a0c0a436f6d70616e7958595a3113301106"
    b"0355040b0c0a436f6d70616e7958595a3114301206035504030c0b546865486f73744e61"
    b"6d65301e170d3139313231383033333935355a170d3239313231353033333935355a3075"
    b"310b30090603550406130258583114301206035504080c0b54686550726f76696e636531"
    b"10300e06035504070c075468654369747931133011060355040a0c0a436f6d70616e7958"
    b"595a31133011060355040b0c0a436f6d70616e7958595a3114301206035504030c0b5468"
    b"65486f73744e616d65305c300d06092a864886f70d0101010500034b003048024100cc20"
    b"643fd3d9c21a0acba4f48f61aadd675f52175a9dcf07fbef610a6a6ba14abb891745cd18"
    b"a1d4c056580d8ff1a639460f867013c8391cdc9f2e573b0f872d0203010001300d06092a"
    b"864886f70d0101050500034100b0513fe2829e9ecbe55b6dd14c0ede7502bde5d46153c8"
    b"e960ae3ebc247371b525caeb41bbcf34686015a44c50d226e66aef0a97a63874ca5944ef"
    b"979b57f0b3"
)

# Function creates HTML web page with form to insert Mesh credentials
def web_page(led):
  if led[0] != (0,0,0):
    gpio_state="ON"
  else:
    gpio_state="OFF"
  
  html = """
  <html>
  <head> 
  <title>ESP Web Server</title> <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,"> 
  <style>html{font-family: Helvetica; display:inline-block; margin: 0px auto; text-align: center;}
  h1{color: #0F3376; padding: 2vh;}p{font-size: 1.5rem;}.button{display: inline-block; background-color: #e7bd3b; border: none; 
  border-radius: 4px; color: white; padding: 16px 40px; text-decoration: none; font-size: 30px; margin: 2px; cursor: pointer;}
  .button2{background-color: #4286f4;}</style>
  </head>
  
  <body> 
  <h1>ESP Web Server</h1> 
  <p>GPIO state: <strong>""" + gpio_state + """</strong></p>
  <p><a href="/?led=on"><button class="button">ON</button></a></p>
  <p><a href="/?led=off"><button class="button button2">OFF</button></a></p>
  
 <p>MESH ESP NOW setup </p>
   <form action="/" method="POST">
    <input type="text" name="mesh-ssid" placeholder="Mesh SSID"><br> 
    <input type="password" name="mesh-password" placeholder="Mesh Password"><br>
    <left><button type="submit">Submit</button></left>
  </form>     
  </body>
  </html>
  """
  return html

def gpio_func_out(n):
    GPIO_FUNCn_OUT_SEL_CFG_REG = 0x3FF44530 + 0x4 * n
    return GPIO_FUNCn_OUT_SEL_CFG_REG


def init_LED(pin_number=25):  
    pin = Pin(pin_number, Pin.OUT)
    n = neopixel.NeoPixel(pin, 1)
    r = gpio_func_out(25)
    mem32[r] |= 1 << 9
    return n

start = time.ticks_us()
async def connect_wifi(ssid, password):
    wlan = network.WLAN(network.STA_IF)
    print(f"Create WLAN", time.ticks_us() - start)
    await asyncio.sleep_ms(0)
    wlan.active(True)
    print(f"WLAN active", time.ticks_us() - start)
    if not wlan.isconnected():
        wlan.connect(ssid, password)
        print(f"WLAN connect", time.ticks_us() - start)
        while not wlan.isconnected():
            print("Sleep here?")
            await asyncio.sleep_ms(10)

    print("Connected")
    print(wlan.ifconfig())
    return wlan

c = (10, 0, 0)
async def blink():
    led = init_LED()
    global c
    while True:
        led[0] = c
        r, g, b = c
        g = g ^ 10
        b = b ^ 10
        r = r ^ 10
        c = ( r, g, b)
        led.write()
        print("[LED] BLINK", time.ticks_us() - start)
        await asyncio.sleep_ms(500)


async def main():
    loop = asyncio.get_event_loop()
    print("Blink()")
    # asyncio.create_task(blink())
    loop.create_task(blink())
    await asyncio.sleep_ms(20)
    ssid = "FourMusketers_2.4GHz"
    password = "pass"
    wlan = await connect_wifi(ssid, password)

    s = socket.socket()

    # s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # # Binding to all interfaces - server will be accessible to other hosts!
    # ai = socket.getaddrinfo("0.0.0.0", 8443)
    # print("Bind address info:", ai)
    # addr = ai[0][-1]

    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    #s.setsockopt(socket.AF_INET, socket.SOCK_STREAM, 0)
    s.bind(('', 8443))
    s.listen(5)
    # s.setblocking(0)
    print("Listening, connect your browser to https://<this_host>:8443/")

    print("Webserver()")
    # asyncio.create_task(webserver(s))
    # await asyncio.sleep_ms(1000)

    #await webserver(s)
    loop.create_task(webserver(s))
    print("Running for eternity")

    try: 
        loop.run_forever()
    except KeyboardInterrupt:
        print("loop closing")
        loop.close()
    except e:
        print(e)
        loop.close()
    # Close the server
    # loop.run_until_complete(server.wait_closed())
    loop.close()
    print("END")
    
async def webserver(sockets, use_stream=True):
    counter = 0
    s = sockets
    n = init_LED(25)
    print("Inside webserver before WHILE")
    global c
    while True:
        # await asyncio.sleep_ms(20)
        res = s.accept()
        client_s = res[0]
        client_addr = res[1]
        print("Client address:", client_addr)
        print("Client socket:", client_s)
        # CPython uses key keyfile/certfile arguments, but MicroPython uses key/cert
        client_s = ssl.wrap_socket(client_s, server_side=True, key=key, cert=cert)
        print(client_s)
        print("Request:")
        if use_stream:
            # Both CPython and MicroPython SSLSocket objects support read() and
            # write() methods.
            # Browsers are prone to terminate SSL connection abruptly if they
            # see unknown certificate, etc. We must continue in such case -
            # next request they issue will likely be more well-behaving and
            # will succeed.
            try:
                req = client_s.readline()
                response = str(req)
                print(req)
                while True:
                    h = client_s.readline()
                    if h == b"" or h == b"\r\n":
                        break
                    print(h)
                    response = response + str(h)
                if req:
                    # client_s.send('HTTP/1.0 200 OK\n')
                    # client_s.send('Content-Type: text/html\n')
                    # client_s.send('Connection: close\n\n')
                    # client_s.sendall(html)

                    # client_s.write('HTTP/1.1 200 OK\n')
                    # client_s.write('Content-Type: text/html\n')
                    
                    led_on = response.find('/?led=on')
                    led_off = response.find('/?led=off')
                    if led_on == 6:
                        print('LED ON')
                        
                        c = (0, 10, 0)
                        n[0] = c
                        n.write()
                    if led_off == 6:
                        print('LED OFF')
                        
                        c = (0, 0, 10)
                        n[0] = c
                        n.write()
                    response = web_page(n)
                    client_s.write('HTTP/1.0 200 OK\n')
                    client_s.write('Content-Type: text/html\n')
                    client_s.write('Connection: close\n\n')
                    client_s.write(response)
                    print("Data written")
                    # client_s.write(CONTENT % counter)
            except Exception as e:
                print("Exception serving request:", e)
        else:
            print(client_s.recv(4096))
            client_s.send(CONTENT % counter)
        client_s.close()
        counter += 1
        print()


if __name__=='__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, Exception) as e:
        print("Exception {}".format(type(e).__name__))
    finally:
        asyncio.new_event_loop()