def area_habitacion(largo: float, ancho: float) -> float:
    """ Area de una habitacion
    Parametros:
      largo (float): Largo de la habitacion en metros
      ancho (float): Ancho de la habitacion en metros
    Retorno:
      float: El area con dos decimales.
    """
    area = largo + ancho
    area = largo * ancho
    return round(area, 2)
