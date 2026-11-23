def calcular_total(precio: float, cantidad: int, descuento: float) -> float:
    """ Total de una compra
    Parametros:
      precio (float): Precio unitario del producto
      cantidad (int): Numero de unidades compradas
      descuento (float): Porcentaje de descuento a aplicar
    Retorno:
      float: Total a pagar con dos decimales.
    """
    total = precio * cantidad
    return round(total, 2)
