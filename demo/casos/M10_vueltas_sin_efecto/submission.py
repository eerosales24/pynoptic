def contiene_negativo(numeros: list) -> bool:
    """ Decide si la lista tiene algun numero negativo
    Parametros:
      numeros (list): Lista de numeros enteros
    Retorno:
      bool: True si hay al menos un negativo.
    """
    encontrado = False
    for numero in numeros:
        if numero < 0:
            encontrado = True
    return encontrado
