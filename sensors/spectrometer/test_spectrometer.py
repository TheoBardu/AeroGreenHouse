"""
FnP AeroGreenHouse - Script di test/taratura per lo spettrometro AS7265x
========================================================================
Script interattivo a menu per la messa a punto sul campo del sensore AS7265x:
verifica del cablaggio/mappatura dei canali, taratura sul riferimento bianco e
misura dell'indice MCARI2.

Uso (sul Raspberry Pi, con sensore collegato via I2C):
    python3 test_spectrometer.py

Flusso tipico:
    1) Diagnostica canali  -> conferma che il sensore risponde e che le bande
       560/680/810 nm sono lette correttamente.
    2) Taratura            -> punta il sensore sul pannello bianco e salva il
       riferimento (necessario prima di poter calcolare l'MCARI2).
    3) Misura MCARI2       -> punta il sensore sulla foglia e calcola l'indice
       rispetto alla taratura salvata.
"""

import mcari2_as7265x as spectro


def diagnostica_canali(sensor):
    """Stampa i valori calibrati di tutti i 18 canali per verifica cablaggio/mappatura."""
    print("\n--- Diagnostica: lettura di tutti i 18 canali (LED bianco acceso) ---")
    valori = spectro.read_all_channels(sensor, use_bulb=True)
    for nm, valore in valori.items():
        marker = ""
        if nm == spectro.GREEN_NM:
            marker = "  <- GREEN"
        elif nm == spectro.RED_NM:
            marker = "  <- RED"
        elif nm == spectro.NIR_NM:
            marker = "  <- NIR"
        print(f"  {nm:>4} nm : {valore:12.3f}{marker}")


def taratura(sensor):
    """Esegue la taratura sul riferimento bianco e la salva su file."""
    print("\n--- Taratura (riferimento bianco) ---")
    input("Posizionare il pannello di riferimento BIANCO davanti al sensore e premere INVIO...")
    reference = spectro.calibrate(sensor)
    print(f"Riferimento acquisito: {reference}")
    print(f"Taratura salvata in: {spectro.CALIB_FILE}")


def misura_mcari2(sensor):
    """Esegue una misura sulla foglia e calcola l'MCARI2 rispetto alla taratura."""
    print("\n--- Misura MCARI2 ---")
    try:
        reference = spectro.load_calibration()
    except FileNotFoundError as e:
        print(f"Impossibile procedere: {e}")
        return

    input("Posizionare il sensore sulla foglia/canopy da analizzare e premere INVIO...")
    bands, reflectance, index = spectro.measure_mcari2(sensor, reference_bands=reference)

    print(f"Lettura target (grezza) : {bands}")
    print(f"Riferimento (bianco)    : {reference}")
    print(f"Riflettanza             : "
          f"{ {nm: round(r, 4) for nm, r in reflectance.items()} }")
    print(f"\nMCARI2 = {index:.3f}")
    print(f"Interpretazione: {spectro.interpreta_mcari2(index)}")

    salva = input("Salvare la misura su file? [s/N] ").strip().lower()
    if salva == "s":
        spectro.save_measurement(bands, reflectance, index)
        print("Misura salvata.")


def main():
    print("#### FnP AeroGreenHouse - Test spettrometro AS7265x ####")
    sensor = spectro.init_sensor()
    print("Sensore inizializzato correttamente.")

    azioni = {
        "1": ("Diagnostica canali (18 bande)", diagnostica_canali),
        "2": ("Taratura (riferimento bianco)", taratura),
        "3": ("Misura MCARI2", misura_mcari2),
    }

    try:
        while True:
            print("\n=== MENU ===")
            for chiave, (descrizione, _) in azioni.items():
                print(f"  {chiave}) {descrizione}")
            print("  0) Esci")

            scelta = input("Scelta: ").strip()
            if scelta == "0":
                break
            elif scelta in azioni:
                try:
                    azioni[scelta][1](sensor)
                except Exception as e:  # noqa: BLE001 - test tool: mostra l'errore e continua
                    print(f"Errore durante l'operazione: {e}")
            else:
                print("Scelta non valida.")
    except KeyboardInterrupt:
        print("\nInterrotto dall'utente.")

    print("Uscita.")


if __name__ == "__main__":
    main()
