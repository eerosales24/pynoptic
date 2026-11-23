def posicion_de(nombres: list, buscado: str) -> int:
    """ Posicion de un nombre en la lista
    Parametros:
      nombres (list): Lista de nombres registrados
      buscado (str): Nombre a buscar
    Retorno:
      int: La posicion del nombre, o -1 si no esta.
    """
    for i in range(len(nombres)):
        if nombres[i] == buscado:
            return i
