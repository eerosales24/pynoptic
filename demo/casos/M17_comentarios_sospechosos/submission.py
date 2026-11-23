def contar_vocales(texto: str) -> int:
    """ Cuenta las vocales de un texto
    Parametros:
      texto (str): Texto a revisar
      vocales (str): Conjunto de vocales a contar
    Retorno:
      int: La cantidad de vocales encontradas.
    """
    # Inicializamos el contador en cero
    cantidad = 0
    # Recorremos todos los caracteres del texto
    for caracter in texto:
        if caracter in "aeiou":
            # Verificamos si es vocal y sumamos uno
            cantidad = cantidad + 1
    return cantidad
