def todos_aprobaron(notas: list) -> bool:
    """ Decide si todos los estudiantes aprobaron
    Parametros:
      notas (list): Lista de notas del curso
    Retorno:
      bool: True si todas las notas son aprobatorias.
    """
    for nota in notas:
        if nota >= 3.0:
            return True
        else:
            return False
