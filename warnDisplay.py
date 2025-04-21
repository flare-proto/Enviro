"""
DO NOT USE UNLESS YOU KNOW WHAT YOU ARE DOING
THIS USES EAS TONES
"""

import configparser
import re
import textwrap
import threading
import time

import pika
import pygame
import pyttsx3
import win32api
import win32con
import win32gui

config = configparser.ConfigParser()
config.read("config.ini")

testSrv = pika.URLParameters(config["warn"]["amqp"])

engine = pyttsx3.init()
def onEnd():
    engine.endLoop()
engine.connect('finished-utterance', onEnd)
voices = engine.getProperty('voices')       #getting details of current voice
#engine.setProperty('voice', voices[0].id)  #changing index, changes voices. o for male
engine.setProperty('voice', voices[1].id)   #changing index, changes voices. 1 for female

class TextPrint:
    def __init__(self):
        self.reset()
        self.font = pygame.font.Font(None, 25)

    def tprint(self, screen, text):
        text_bitmap = self.font.render(text, False, (255, 255, 255))
        screen.blit(text_bitmap, (self.x, self.y))
        self.y += self.line_height

    def reset(self):
        self.x = 500
        self.y = 45
        self.line_height = 20

    def indent(self):
        self.x += 10

    def unindent(self):
        self.x -= 10

pygame.init()
warnbeep2 = pygame.mixer.Sound("canada-eas-alert.mp3")
infoObject = pygame.display.Info()
scr = pygame.display.set_mode((infoObject.current_w, infoObject.current_h),pygame.NOFRAME|pygame.FULLSCREEN) # For borderless, use pygame.NOFRAME
done = False
fuchsia = (255, 0, 128)  # Transparency color
red = (255, 0, 0)

# Create layered window
hwnd = pygame.display.get_wm_info()["window"]
win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE,
                       win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) | win32con.WS_EX_LAYERED)
# Set window transparency color
win32gui.SetLayeredWindowAttributes(hwnd, win32api.RGB(*fuchsia), 0, win32con.LWA_COLORKEY)
win32gui.SetWindowPos(pygame.display.get_wm_info()['window'], win32con.HWND_TOPMOST, 0,0,0,0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)

size = min(infoObject.current_w,infoObject.current_h)
redSquare = pygame.Rect(0,0,size,size)
redSquare.centerx = infoObject.current_w/2
redSquare.centery = infoObject.current_h/2
text = []
def say(s):
    text.extend([line for line in re.findall(r'.{1,100}(?:\s+|$)', s)])
    def trd():
        global text
        warnbeep2.play()
        time.sleep(warnbeep2.get_length())
        
        engine.say(s)
        engine.runAndWait()
        text = []
    t = threading.Thread(None,trd,daemon=True)
    t.start()


tp = TextPrint()
hidden = False

connection = pika.BlockingConnection(testSrv)
channel = connection.channel()

result = channel.queue_declare(queue='', exclusive=True)
channel.queue_bind(exchange='alerting',
                   queue=result.method.queue)

def callback(ch, method, properties, body):
    b = body.decode()
    say(b)


def runAMQP():
    channel.basic_consume(
    queue=result.method.queue, on_message_callback=callback, auto_ack=True)
    channel.start_consuming()
threading.Thread(target=runAMQP,daemon=True).start()


while not done:
    tp.reset()
    if len(text) == 0:
        if not hidden:
            scr = pygame.display.set_mode((800, 600), flags=pygame.HIDDEN)
    elif hidden:
        scr = pygame.display.set_mode((infoObject.current_w, infoObject.current_h),pygame.NOFRAME|pygame.FULLSCREEN)
    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            done = True
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                done = True
            if e.key == pygame.K_F1:
                pygame.display.iconify()

    scr.fill((0,0,0))  # Transparent background
    pygame.draw.rect(scr, red, redSquare)
    tp.tprint(scr,"ENVIROTRON")
    for t in text:
        tp.tprint(scr,t)
    
    pygame.display.update()