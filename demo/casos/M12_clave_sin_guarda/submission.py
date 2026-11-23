def precio_de(inventario: dict, producto: str) -> int:
    """ Precio de un producto del inventario
    Parametros:
      inventario (dict): Mapa de producto a precio
      producto (str): Nombre del producto consultado
    Retorno:
      int: El precio del producto.
    """
    precio = inventario[producto]
    return precio
