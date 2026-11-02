from datetime import date


def calculate_monthly_fees(month: date) -> list:
    """Calcula las monthly fees del mes que empieza en `month` (primer día del mes)."""
    raise NotImplementedError


def calculate_monthly_fees_for_range(month_from: date, month_to: date) -> list:
    """Calcula los meses de `month_from` a `month_to`, ambos incluidos (primer día de cada mes).

    Los parámetros son los meses que se cubren, no las fechas de corrida: para cubrir enero y febrero
    se pasa 2023-01-01 → 2023-02-01 (la corrida de febrero sería el 01/03).
    """
    raise NotImplementedError
