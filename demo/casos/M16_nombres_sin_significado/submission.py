def calcular_imc(peso: float, estatura: float) -> float:
    """ Indice de masa corporal
    Parametros:
      peso (float): Peso de la persona en kilogramos
      estatura (float): Estatura de la persona en metros
    Retorno:
      float: El indice con dos decimales.
    """
    a = peso
    b = estatura * estatura
    c1 = a / b
    return round(c1, 2)
