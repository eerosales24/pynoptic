def tiene_beneficio(es_socio: bool, compras: int, antiguedad: int) -> bool:
    """ Decide si un cliente tiene beneficio
    Parametros:
      es_socio (bool): Si el cliente es socio
      compras (int): Numero de compras del mes
      antiguedad (int): Anios como cliente
    Retorno:
      bool: True si tiene derecho al beneficio.
    """
    return es_socio or compras > 5 and antiguedad > 2
