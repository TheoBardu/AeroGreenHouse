"""
Arrotondamento dei dati di misura
=================================
Piccolo modulo di supporto per decidere quante cifre tenere dai valori letti
dai sensori prima di loggarli o salvarli su file.

La risoluzione dell'HC-SR04 e' di circa 0.17 cm, quindi per un'altezza in cm
il parametro che conta e' il numero di decimali: 'decimals' in config.yaml.
'round_significant' e' disponibile per i casi in cui serva ragionare a cifre
significative invece che a decimali.
"""

import math


# Decimali usati se config.yaml non specifica nulla
DEFAULT_DECIMALS = 1


def round_decimals(value: float, decimals: int = None) -> float:
    '''
    Arrotonda un valore a un numero fisso di decimali.

    :param value:    valore da arrotondare
    :param decimals: numero di decimali da tenere (default: DEFAULT_DECIMALS)
    :return:         valore arrotondato
    '''
    if decimals is None:
        decimals = DEFAULT_DECIMALS
    return round(float(value), int(decimals))


def round_significant(value: float, sig_digits: int) -> float:
    '''
    Arrotonda un valore a un numero di cifre significative.

    Esempi: round_significant(65.4321, 3) -> 65.4
            round_significant(0.004567, 2) -> 0.0046

    :param value:      valore da arrotondare
    :param sig_digits: numero di cifre significative da tenere (> 0)
    :return:           valore arrotondato (0.0 resta 0.0)
    '''
    value = float(value)
    if value == 0.0:
        return 0.0
    if sig_digits < 1:
        raise ValueError("sig_digits deve essere >= 1")

    # Posizione della prima cifra significativa
    exponent = math.floor(math.log10(abs(value)))
    return round(value, int(sig_digits) - 1 - exponent)
