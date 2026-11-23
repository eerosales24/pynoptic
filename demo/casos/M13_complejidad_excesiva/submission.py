def contar_repetidos(numeros: list) -> int:
    """ Cuenta cuantos numeros aparecen mas de una vez
    Parametros:
      numeros (list): Lista de numeros enteros
    Retorno:
      int: La cantidad de numeros repetidos.
    """
    repetidos = 0
    for numero in numeros:
        if numeros.count(numero) > 1:
            repetidos = repetidos + 1
    return repetidos
