def es_nombre_invalido(nombre: str) -> bool:
    """ Decide si un nombre es invalido
    Parametros:
      nombre (str): Nombre a validar
    Retorno:
      bool: True si el nombre es invalido.
    """
    if "vacio" or nombre == "":
        return True
    return False
