import sys
import select
from machine import Pin, PWM


pwm = PWM(Pin(0))
pwm.freq(100_000)
pwm.duty_u16(0)

MAX = 0.4
TIMEOUT_MS = 500

poller = select.poll()
poller.register(sys.stdin, select.POLLIN)


def setze(stufe):
    pwm.duty_u16(int(65535 * MAX * stufe / 15))

while True:
    if poller.poll(TIMEOUT_MS):
        zeile = sys.stdin.readline().strip()
        try:
            stufe = max(0, min(15, int(zeile)))
            setze(stufe)
            print(stufe)
        except ValueError:
            pass
    else:
        setze(0)