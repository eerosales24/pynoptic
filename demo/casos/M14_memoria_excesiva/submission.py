def acumular_prefijos(numeros: list) -> int:
    """ Suma de todos los prefijos de la lista
    Parametros:
      numeros (list): Lista de numeros enteros
    Retorno:
      int: La suma de las sumas de cada prefijo.
    """
    total = 0
    for i in range(len(numeros)):
        prefijo = numeros[0:i + 1]
        for valor in prefijo:
            total = total + valor
    return total
