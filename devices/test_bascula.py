# ==============================================================================
# TEST DE DIAGNÓSTICO DE BÁSCULA HX711 (SIN MOVER LA BANDA)
# Ejecuta este script para ver los valores RAW reales en vivo y detectar:
#   1. Si la celda está invertida (da valores negativos al presionar).
#   2. Si los valores derivan/caen con el tiempo (problema mecánico/cableado).
#   3. El FACTOR_ESCALA exacto para tu celda de carga.
# ==============================================================================

import machine
import time

DT_PIN  = machine.Pin(14, machine.Pin.IN, machine.Pin.PULL_UP)
SCK_PIN = machine.Pin(13, machine.Pin.OUT, value=0)

def leer_raw():
    SCK_PIN.value(0)
    t0 = time.ticks_ms()
    while DT_PIN.value() == 1:
        if time.ticks_diff(time.ticks_ms(), t0) > 200:
            return None
        time.sleep_us(200)
    count = 0
    for _ in range(24):
        SCK_PIN.value(1)
        time.sleep_us(1)
        count = (count << 1) | DT_PIN.value()
        SCK_PIN.value(0)
        time.sleep_us(1)
    SCK_PIN.value(1)
    time.sleep_us(1)
    SCK_PIN.value(0)
    time.sleep_us(1)
    if count & 0x800000:
        count -= 0x1000000
    return count

print("\n=== DIAGNOSTICO HX711 EN VIVO ===")
print("1. Deja la banda VACIA 3 segundos para tomar TARA...")
time.sleep(3)

tara_acum = 0
n = 0
for _ in range(20):
    r = leer_raw()
    if r is not None:
        tara_acum += r
        n += 1
    time.sleep_ms(50)

if n == 0:
    print("[ERROR] El HX711 no responde. Revisa pines DT=14 y SCK=13.")
else:
    tara = tara_acum / n
    print("[OK] TARA = {:.0f}".format(tara))
    print("2. Ahora COLOCA tu caja de 1.25 kg encima de la bascula (sin mover el motor)...")
    print("   Observa si 'Delta' es positivo o negativo y si se mantiene estable:\n")

    try:
        while True:
            r = leer_raw()
            if r is not None:
                delta = r - tara
                peso_aprox = delta / 98.0
                print("RAW: {:10.0f} | Delta: {:10.0f} | Con factor 98: {:8.1f} g".format(
                    r, delta, peso_aprox))
            else:
                print("[WARN] Sin dato listo (DT=1)")
            time.sleep_ms(300)
    except KeyboardInterrupt:
        print("\nDiagnostico finalizado.")
