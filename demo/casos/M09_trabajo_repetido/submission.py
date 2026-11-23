def contar_pares_e_impares(numeros: list) -> int:
    """ Cuenta los numeros pares de una lista
    Parametros:
      numeros (list): Lista de numeros enteros
    Retorno:
      int: La cantidad de numeros pares.
    """
    cantidad_pares = 0
    cantidad_impares = 0
    for numero in numeros:
        if numero % 2 == 0:
            cantidad_pares = cantidad_pares + 1
    for numero in numeros:
        if numero % 2 == 1:
            cantidad_impares = cantidad_impares + 1
    return cantidad_pares
