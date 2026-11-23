def sumar_hasta(limite: int) -> int:
    """ Suma los enteros desde 1 hasta el limite
    Parametros:
      limite (int): Ultimo entero a sumar
    Retorno:
      int: La suma acumulada.
    """
    contador = 1
    acumulado = 0
    while contador <= limite:
        acumulado = acumulado + contador
    return acumulado
