from submission import precio_de

inventario = {"pan": 3000, "leche": 4500}

precio_de(inventario, "pan")
# La clave ausente es el punto del caso: sin guarda, esto es un KeyError,
# y ese KeyError es lo que confirma la metrica en tiempo de ejecucion.
precio_de(inventario, "arroz")
