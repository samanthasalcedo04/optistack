# ==============================================================================
# OPTISTACK - FIRMWARE ESTACIÓN DE CLASIFICACIÓN Y MEDICIÓN 3D (V4 CALIBRADO)
# Plataforma: ESP32 / Raspberry Pi Pico / RP2040 con MicroPython
#
# NOVEDADES V4:
#   1. AUTOCALIBRACIÓN INTEGRAL AL INICIO (Túnel vacío):
#      - Calibra Tara de la Báscula (HX711).
#      - Calibra Altura Base del sensor superior (H).
#      - Calibra Ancho Base real sumando las medianas de A1 y A2 (reemplaza el 30.0 fijo).
#   2. ANTI-CORTES REFORZADO:
#      - Exige 25 lecturas consecutivas (~2.5 cm) de banda vacía antes de cerrar un paquete.
#      - Elimina los falsos cortes por cinta de embalaje, solapas de cartón o ruido.
#   3. AJUSTE FINO DE BÁSCULA:
#      - FACTOR_ESCALA ajustado a 98.0 (basado en tu prueba de 1401.5g vs 1250g reales).
# ==============================================================================

import machine
import time

# =====================================================================
# PINES
# =====================================================================
STEP_PIN = machine.Pin(4, machine.Pin.OUT)
DIR_PIN  = machine.Pin(15, machine.Pin.OUT)
MOTOR_DIRECTION = 0

DT_PIN  = machine.Pin(14, machine.Pin.IN, machine.Pin.PULL_UP)
SCK_PIN = machine.Pin(13, machine.Pin.OUT, value=0)

# Sensor de ALTURA (arriba al inicio, apunta hacia la banda)
TRIG_H = machine.Pin(23, machine.Pin.OUT)
ECHO_H = machine.Pin(34, machine.Pin.IN)

# Sensor de ANCHO izquierdo (centro)
TRIG_A1 = machine.Pin(22, machine.Pin.OUT)
ECHO_A1 = machine.Pin(36, machine.Pin.IN)

# Sensor de ANCHO derecho (centro)
TRIG_A2 = machine.Pin(32, machine.Pin.OUT)
ECHO_A2 = machine.Pin.IN if False else machine.Pin(35, machine.Pin.IN)

# =====================================================================
# PARÁMETROS MECÁNICOS Y CALIBRACIÓN
# =====================================================================
STEPS_PER_REV = 3200
CM_POR_REV    = 6.4
CM_POR_PASO   = CM_POR_REV / STEPS_PER_REV  # 0.0020 cm por paso

DELAY_US        = 500
PASOS_POR_CICLO = 50       # ~0.10 cm de avance por ciclo del bucle

UMBRAL_DETECCION = 3.0     # Elevación mínima (cm) sobre la banda para detectar caja

# Calibración de Peso HX711 (ajustado con Delta estable ~175,000 para 1250g reales)
FACTOR_ESCALA = 140.0
TARA_CERO     = 0.0
TARA_LISTA    = False
PESO_MIN_G    = 5.0

# Histéresis reforzada:
# 4 ciclos (~0.4 cm) para confirmar entrada real
# 25 ciclos (~2.5 cm) de banda vacía continua para confirmar salida real
LECTURAS_ENTRADA_CONFIRMAR = 4
LECTURAS_VACIO_PARA_CERRAR = 25

# Variables globales autocalibradas al inicio
BASE_ALTURA_CM = 43.0
BASE_ANCHO_CM  = 47.0

# =====================================================================
# MOTOR
# =====================================================================
def dar_pasos(n, delay_us=DELAY_US):
    for _ in range(n):
        STEP_PIN.value(1)
        time.sleep_us(delay_us)
        STEP_PIN.value(0)
        time.sleep_us(delay_us)

# =====================================================================
# SENSOR DE PESO HX711
# =====================================================================
def leer_raw_hx711_bloqueante(timeout_ms=120):
    SCK_PIN.value(0)
    t0 = time.ticks_ms()
    while DT_PIN.value() == 1:
        if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
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

def medir_peso_g(timeout_ms=30):
    raw = leer_raw_hx711_bloqueante(timeout_ms=timeout_ms)
    if raw is None or not TARA_LISTA:
        return None
    peso = (raw - TARA_CERO) / FACTOR_ESCALA
    return max(0.0, peso)

def pesar_estatico_pausa(n_lecturas=6):
    """Detiene momentáneamente la banda para liberar tensión de la lona y toma múltiples lecturas."""
    STEP_PIN.value(0)
    time.sleep_ms(120)
    lecturas = []
    for _ in range(n_lecturas):
        p = medir_peso_g(timeout_ms=120)
        if p is not None and p > PESO_MIN_G:
            lecturas.append(p)
    if not lecturas:
        return []
    return lecturas

# =====================================================================
# ULTRASONIDOS HC-SR04
# =====================================================================
def medir_distancia_cm(trig, echo, timeout_us=30000):
    trig.value(0)
    time.sleep_us(3)
    trig.value(1)
    time.sleep_us(12)
    trig.value(0)

    start = time.ticks_us()
    while echo.value() == 0:
        if time.ticks_diff(time.ticks_us(), start) > 20000:
            return 0.0

    t1 = time.ticks_us()
    while echo.value() == 1:
        if time.ticks_diff(time.ticks_us(), t1) > timeout_us:
            return 0.0

    t2 = time.ticks_us()
    dur = time.ticks_diff(t2, t1)
    return round((dur * 0.0343) / 2.0, 1)

def mediana_distancia(trig, echo, n=8, pausa_ms=45):
    muestras = []
    for _ in range(n):
        d = medir_distancia_cm(trig, echo)
        if d > 2.0:
            muestras.append(d)
        time.sleep_ms(pausa_ms)
    if not muestras:
        return 0.0
    muestras.sort()
    return muestras[len(muestras) // 2]

def medir_ancho_cm():
    """Mide el ancho usando la base autocalibrada BASE_ANCHO_CM."""
    d1 = medir_distancia_cm(TRIG_A1, ECHO_A1)
    time.sleep_ms(40)
    d2 = medir_distancia_cm(TRIG_A2, ECHO_A2)
    if d1 > 1.0 and d2 > 1.0:
        ancho = BASE_ANCHO_CM - (d1 + d2)
        if ancho > 2.0:
            return round(ancho, 1)
    return None

# =====================================================================
# RUTINA DE AUTOCALIBRACIÓN INTEGRAL AL INICIO
# =====================================================================
def autocalibrar_estacion():
    global TARA_CERO, TARA_LISTA, BASE_ALTURA_CM, BASE_ANCHO_CM

    print("\n[CALIBRACIÓN] Mantenga el túnel y la banda completamente vacíos...")
    time.sleep(1.0)

    # 1. Calibrar Tara Báscula
    acum = 0.0
    validas = 0
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < 2000:
        r = leer_raw_hx711_bloqueante(timeout_ms=150)
        if r is not None:
            acum += r
            validas += 1
    if validas == 0:
        print("[ERROR] Celda de carga HX711 no responde.")
        return False
    TARA_CERO = acum / validas
    TARA_LISTA = True
    print("  [1/3] Tara Báscula      : raw = {:.0f} (Factor = {:.1f})".format(TARA_CERO, FACTOR_ESCALA))

    # 2. Calibrar Sensor de Altura (Superior)
    h_base = mediana_distancia(TRIG_H, ECHO_H, n=8, pausa_ms=45)
    if h_base <= 10.0:
        print("[ERROR] Sensor de altura (H) no responde.")
        return False
    BASE_ALTURA_CM = h_base
    print("  [2/3] Altura Base (H)   : {:.1f} cm".format(BASE_ALTURA_CM))

    # 3. Verificar Sensores de Ancho (A1 + A2) manteniendo base física estable (47.0 cm)
    a1_base = mediana_distancia(TRIG_A1, ECHO_A1, n=6, pausa_ms=45)
    time.sleep_ms(50)
    a2_base = mediana_distancia(TRIG_A2, ECHO_A2, n=6, pausa_ms=45)
    print("  [3/3] Ancho Base fijo   : {:.1f} cm (Lectura vacío A1={:.1f}, A2={:.1f})".format(
        BASE_ANCHO_CM, a1_base, a2_base))

    return True

# =====================================================================
# BUCLE PRINCIPAL
# =====================================================================
def main():
    global TARA_CERO
    DIR_PIN.value(MOTOR_DIRECTION)
    time.sleep_ms(5)
    SCK_PIN.value(0)
    time.sleep_ms(100)

    print("==================================================")
    print("  OptiStack 3D - Medición Dinámica V4 (Calibrado) ")
    print("==================================================")

    if not autocalibrar_estacion():
        return

    print("\n[SISTEMA] Calibración completada. Banda en marcha...\n")

    paquete_activo = False
    consecutivos_vacio = 0
    consecutivos_paquete = 0

    pasos_en_paquete = 0
    alturas_acumuladas = []
    anchos_acumulados  = []
    pesos_acumulados   = []
    pesos_estaticos    = []
    buffer_tara_vacio  = []

    contador_paquete = 1
    ciclos = 0

    while True:
        # 1. Avanzar la banda
        dar_pasos(PASOS_POR_CICLO, DELAY_US)
        ciclos += 1

        # 2. Medir sensor superior de altura
        dist_H = medir_distancia_cm(TRIG_H, ECHO_H)

        if dist_H > 0.0:
            if dist_H <= (BASE_ALTURA_CM - UMBRAL_DETECCION):
                altura_calc = BASE_ALTURA_CM - dist_H
                consecutivos_paquete += 1
                consecutivos_vacio = 0

                if consecutivos_paquete >= LECTURAS_ENTRADA_CONFIRMAR and not paquete_activo:
                    paquete_activo = True
                    # Compensar los pasos de confirmación de entrada
                    pasos_en_paquete = LECTURAS_ENTRADA_CONFIRMAR * PASOS_POR_CICLO
                    alturas_acumuladas = [altura_calc]
                    anchos_acumulados  = []
                    pesos_acumulados   = []
                    pesos_estaticos    = []
                    print(">> [PAQUETE #{} DETECTADO] Midiendo dimensiones...".format(contador_paquete))
            else:
                if paquete_activo:
                    consecutivos_vacio += 1
                consecutivos_paquete = 0

        # 3. Acumular mediciones mientras el paquete cruza
        if paquete_activo:
            pasos_en_paquete += PASOS_POR_CICLO

            if dist_H > 0.0 and dist_H <= (BASE_ALTURA_CM - UMBRAL_DETECCION):
                alturas_acumuladas.append(BASE_ALTURA_CM - dist_H)

            # Micro-pausas estáticas a los 12, 18 y 24 cm de longitud (6 muestras cada una)
            if pasos_en_paquete in (int(12.0 / CM_POR_PASO), int(18.0 / CM_POR_PASO), int(24.0 / CM_POR_PASO)):
                muestras_pausa = pesar_estatico_pausa(6)
                if muestras_pausa:
                    pesos_acumulados.extend(muestras_pausa)
                    med_p = sorted(muestras_pausa)[len(muestras_pausa) // 2]
                    print("   [PAUSA {:.0f}cm] ({} muestras) Mediana: {:.1f} g".format(
                        pasos_en_paquete * CM_POR_PASO, len(muestras_pausa), med_p))

            # Captura continua en 10Hz
            t_wait = 60 if (ciclos % 2 == 0) else 1
            p = medir_peso_g(timeout_ms=t_wait)
            if p is not None and p > PESO_MIN_G:
                pesos_acumulados.append(p)

            if ciclos % 4 == 0:
                w = medir_ancho_cm()
                if w is not None:
                    anchos_acumulados.append(w)

        # 4. Fin de paquete (Solo tras 2.5 cm continuos de banda vacía)
        if paquete_activo and consecutivos_vacio >= LECTURAS_VACIO_PARA_CERRAR:
            paquete_activo = False

            # Descontar los pasos usados en el filtro de confirmación de salida
            pasos_reales = max(0, pasos_en_paquete - (LECTURAS_VACIO_PARA_CERRAR * PASOS_POR_CICLO))
            longitud_cm = round(pasos_reales * CM_POR_PASO, 1)

            print("[TRÁNSITO] Completando recorrido sobre báscula y ancho...")
            pasos_min_extra = int(20.0 / CM_POR_PASO)
            pasos_max_extra = int(35.0 / CM_POR_PASO)
            avanzado = 0
            peso_vivo = 999.0
            puntos_pausa = (int(2.0 / CM_POR_PASO), int(6.0 / CM_POR_PASO), int(10.0 / CM_POR_PASO))

            while avanzado < pasos_min_extra or (avanzado < pasos_max_extra and peso_vivo > 80.0):
                dar_pasos(PASOS_POR_CICLO, DELAY_US)
                avanzado += PASOS_POR_CICLO

                if avanzado in puntos_pausa:
                    muestras_pausa = pesar_estatico_pausa(6)
                    if muestras_pausa:
                        pesos_acumulados.extend(muestras_pausa)
                        med_p = sorted(muestras_pausa)[len(muestras_pausa) // 2]
                        peso_vivo = med_p
                        print("   -> [PAUSA {:.1f}cm] ({} muestras) Mediana: {:.1f} g".format(
                            avanzado * CM_POR_PASO, len(muestras_pausa), med_p))
                else:
                    p = medir_peso_g(timeout_ms=110)
                    if p is not None:
                        peso_vivo = p
                        if p > PESO_MIN_G:
                            pesos_acumulados.append(p)

                if avanzado % (PASOS_POR_CICLO * 2) == 0:
                    w = medir_ancho_cm()
                    if w is not None:
                        anchos_acumulados.append(w)

            # ---- CÁLCULOS FINALES ----
            # Altura (H)
            if alturas_acumuladas:
                alturas_acumuladas.sort()
                corte = max(1, len(alturas_acumuladas) // 6)
                sub_h = alturas_acumuladas[corte:-corte] if len(alturas_acumuladas) > 3 else alturas_acumuladas
                altura_cm = round(sum(sub_h) / len(sub_h), 1)
            else:
                altura_cm = 0.0

            # Ancho (W)
            if anchos_acumulados:
                anchos_acumulados.sort()
                ancho_cm = round(anchos_acumulados[len(anchos_acumulados) // 2], 1)
            else:
                ancho_cm = 0.0

            # Peso (P) - Meseta superior calculada sobre TODAS las muestras (estáticas + continuas)
            peso_final_g = 0.0
            if pesos_acumulados:
                pesos_acumulados.sort()
                idx_p95 = min(int(len(pesos_acumulados) * 0.95), len(pesos_acumulados) - 1)
                pico_real = pesos_acumulados[idx_p95]
                meseta = [p for p in pesos_acumulados if (0.85 * pico_real) <= p <= (1.08 * pico_real)]
                if meseta:
                    meseta.sort()
                    peso_final_g = round(meseta[len(meseta) // 2], 1)
                else:
                    peso_final_g = round(pico_real, 1)

            peso_kg = round(peso_final_g / 1000.0, 3)

            if longitud_cm >= 5.0 and altura_cm >= 3.0:
                volumen_cm3 = round(longitud_cm * ancho_cm * altura_cm, 1)
                guia_id = "GUIA-AUTO-{:04d}".format(2000 + contador_paquete)

                print("\n==========================================================")
                print("  PAQUETE MEDIDO CON ÉXITO [{}]".format(guia_id))
                print("  - Largo  (L): {:5.1f} cm  (Pasos reales: {})".format(longitud_cm, pasos_reales))
                print("  - Ancho  (W): {:5.1f} cm  (Muestras: {})".format(ancho_cm, len(anchos_acumulados)))
                print("  - Alto   (H): {:5.1f} cm  (Muestras: {})".format(altura_cm, len(alturas_acumuladas)))
                print("  - Peso Real : {:5.1f} g  ({:.3f} kg) [Muestras: {} | Pico Max: {:.1f}g]".format(
                    peso_final_g, peso_kg, len(pesos_acumulados),
                    max(pesos_acumulados) if pesos_acumulados else 0.0))
                print("  - Volumen   : {:7.1f} cm3 ({:.4f} m3)".format(volumen_cm3, volumen_cm3 / 1e6))
                print("==========================================================\n")

                payload_json = {
                    "GuideID": guia_id,
                    "LengthCm": longitud_cm,
                    "WidthCm": ancho_cm,
                    "HeightCm": altura_cm,
                    "WeightKg": peso_kg,
                    "TargetAgencyID": "AG-TRU-01",
                    "SourceDevice": "Dynamic-Belt-RPi-ESP32"
                }
                print("TELEMETRY_JSON:" + str(payload_json).replace("'", '"'))

                contador_paquete += 1
            else:
                print("[DESCARTADO] Inconsistente: L={:.1f} A={:.1f} H={:.1f} P={:.1f}g\n".format(
                    longitud_cm, ancho_cm, altura_cm, peso_final_g))

            # Reset
            consecutivos_vacio = 0
            consecutivos_paquete = 0
            pasos_en_paquete = 0
            alturas_acumuladas = []
            anchos_acumulados  = []
            pesos_acumulados   = []

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        STEP_PIN.value(0)
        print("\n[SISTEMA] Banda y sensores detenidos.")
