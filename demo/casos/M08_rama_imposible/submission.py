def letra_de_nota(nota: float) -> str:
    """ Letra que corresponde a una nota
    Parametros:
      nota (float): Nota numerica del estudiante
    Retorno:
      str: La letra de la nota.
    """
    if nota > 4.0:
        return "A"
    elif nota > 4.5:
        return "A+"
    elif nota > 3.0:
        return "B"
    return "C"
