def promedio_tres_notas(nota1: float, nota2: float, nota3: float) -> float:
    """ Promedio de tres notas
    Parametros:
      nota1 (float): Primera nota del estudiante
      nota2 (float): Segunda nota del estudiante
      nota3 (float): Tercera nota del estudiante
    Retorno:
      float: El promedio con dos decimales.
    """
    acumulado = 0.0
    acumulado = acumulado + round(nota1 * 1.0, 4)
    acumulado = acumulado + round(nota2 * 1.0, 4)
    acumulado = acumulado + round(nota1 * 1.0, 4)
    return round(acumulado / 3, 2)
