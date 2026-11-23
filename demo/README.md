# Demostración: una métrica, un ejercicio

Diecisiete ejercicios, uno por métrica, cada uno escrito para que una
métrica concreta se active. Es la forma de ver la herramienta funcionando
sobre código que se parece al del curso.

```bash
python demo/correr.py                 # la tabla: 17 casos, qué se activó y por qué
python demo/correr.py --sin-ncc       # lo mismo sin Semgrep, ~3x más rápido
python demo/correr.py M06             # un solo caso
python demo/correr.py M06 --traza     # ese caso con el registro de lo que hizo la corrida
python demo/correr.py --detalle       # los 17 perfiles completos
python demo/correr.py --juez          # el contrato JSON de cada métrica, validado
```

## La salida

JSON. El campo que contesta la pregunta es **`activada`**: es `true` cuando
el fenómeno que la métrica mide está en esa entrega. «¿Hay vueltas sin
efecto acá?» → `true`. Es una afirmación sobre el código, no sobre si la
demostración pasó.

```json
{
  "metrica": "M10",
  "nombre": "Iterations with no effect",
  "activada": true,
  "resuelta": true,
  "decidida_por": "dynapyt",
  "lineas": [11],
  "evidencia": [
    {
      "linea": 11,
      "codigo": "encontrado = True",
      "elemento": "encontrado = True",
      "porque": "settled in the loop at line 9, which keeps turning"
    }
  ],
  "observado_al_ejecutar": "6 turns after the last one that changed anything",
  "caso": {
    "carpeta": "M10_vueltas_sin_efecto",
    "nivel": 3,
    "funcion": "contiene_negativo",
    "esperaba_activarse": true,
    "esperaba_resolverse": true,
    "coincide_con_lo_esperado": true
  }
}
```

**`activada` y `coincide_con_lo_esperado` son preguntas distintas** y por eso
viven en niveles distintos. La primera es sobre el código; la segunda es
sobre si el caso se comportó como está escrito que se comporte. Mezclarlas
haría que un caso roto se leyera como una entrega limpia.

**`resuelta`** dice si algo lo decidió. Un candidato que nada decidió no es
una detección, y contarlo como tal sería afirmar que la capa dinámica
funciona sin haberla ejecutado nunca.

## Esto no es la suite de pruebas

`tests/` es la suite: 340 pruebas que corren en medio minuto bajo `pytest` y
no ejecutan nada del otro mundo. `demo/` es esta demostración: diecisiete
entregas que se instrumentan y se ejecutan de verdad, una por una, como se
haría con una entrega real. Por eso tarda minutos y no segundos, y por eso
vive aparte: `pytest` no la recoge.

## Por qué los ejercicios son sintéticos

Están escritos al estilo de SeneCode —nombres en español, firma tipada, el
formato de docstring del curso— pero no son de nadie. Las entregas de los
estudiantes no son nuestras para publicar, que es la política que el README
del proyecto ya declara, así que no entra ninguna al repositorio. La
validación contra el corpus real corre aparte y reporta conteos, no código.

## Qué demuestra cada caso

| | Caso | Quién lo decide |
|---|---|---|
| M01 | un parámetro `descuento` que el cuerpo nunca lee | el árbol |
| M02 | `if "vacio" or nombre == ""`, que siempre es verdadero | el árbol |
| M03 | las dos ramas del `if` con el mismo cuerpo | el árbol |
| M04 | `es_socio or compras > 5 and antiguedad > 2` sin paréntesis | el árbol |
| M05 | el mismo acumulado escrito tres veces, una con la nota equivocada | el árbol |
| M06 | un `for` que contesta por el primer elemento | **la corrida** |
| M07 | una búsqueda que se cae por el final y devuelve `None` | **la corrida** |
| M08 | `if nota > 4.0` seguido de `elif nota > 4.5` | el árbol |
| M09 | dos recorridos sobre la misma lista | **la corrida** |
| M10 | un recorrido completo que ya tenía la respuesta | **la corrida** |
| M11 | un `while` cuyo contador nunca avanza | **la corrida** |
| M12 | `inventario[producto]` con una clave que no está | **la corrida** |
| M13 | `numeros.count(numero)` dentro del bucle | se mide, no se decide |
| M14 | una tajada `numeros[0:i+1]` copiada en cada vuelta | **la corrida** |
| M15 | un área calculada dos veces, la primera descartada | **la corrida** |
| M16 | `a`, `b`, `c1` en lugar de nombres | el árbol |
| M17 | un docstring que documenta un parámetro inexistente | el árbol |

Ocho de los diecisiete sólo se deciden ejecutando la entrega. Si se corre
sin `--dynamic`, esos ocho reportan una sospecha y lo dicen.

## M13 es el caso honesto

M13 es la única métrica cuyo veredicto ninguna corrida puede dar. Una clase
de crecimiento es una afirmación sobre **cómo escala** el trabajo, y una
sola entrada no sostiene una pendiente. La corrida mide el trabajo real
—vueltas más elementos recorridos dentro de llamadas en C, que ningún
contador de bytecode ve— y deja el veredicto sin resolver.

Su `caso.json` lo declara con `espera_resuelto: false`. Es la razón por la
que ese campo existe: para que la demostración no cuente una medición como
una detección.

## El contrato del juez

Cada métrica le pide a un juez LLM **un objeto JSON de forma fija**, y el
punto del subsistema es que el detector y el juez hablen ese mismo
vocabulario. `--juez` recorre el circuito entero para los diecisiete casos:
arma el prompt que se enviaría, valida la respuesta de ejemplo con el
validador real y la enfrenta al detector.

```json
{
  "metrica": "M05",
  "forma": "count",
  "esquema_valido": true,
  "juez":     { "veredicto": "SI", "lineas": [13], "n": 1 },
  "detector": { "veredicto": "SI", "lineas": [13], "resuelto": true },
  "coinciden": true,
  "evidencia_se_solapa": true
}
```

Tres formas, según lo que la métrica mide: `binary` lleva `veredicto`,
`evidencia` y `razon`; `count` agrega `n`; `class` agrega
`clase_estudiante` y `clase_referencia`. El validador rechaza una respuesta
que cite una línea que no existe —inventar un número de línea es la falla
que más se mide— y un `SI` sin evidencia.

La comparación se hace contra el reporte **resuelto**, no contra el
estático. Nueve métricas son candidatas hasta que la entrega corre, y
comparar un veredicto del juez contra un candidato sólo puede dar «no
comparable», que no diría nada sobre el juez.

M13 sale «no comparable» y está bien: el detector se niega a nombrar una
clase de crecimiento con una sola entrada, y al juez sí se le pidió una. El
reporte dice que no hay con qué comparar en vez de inventar un desacuerdo.

Las respuestas son archivos de ejemplo que vienen con los casos, **no de un
modelo**. Demuestran que el contrato cierra para las tres formas, que es una
afirmación sobre el formato y no sobre la precisión de ningún modelo.

## La traza

`--traza` enciende el registro ordenado de lo que pasó:

```
TRAZA (4 de 4 eventos)
      1 write     L3    = 12.0
      2 write     L4    12.0 -> 12.0  (same value)
      3 exit      L1    area_habitacion returned float 12.0
      4 return    L5    float = 12.0
```

Ahí se ve la evidencia de M15 directamente: la línea 3 dejó `12.0` y la
línea 4 lo reemplazó sin que nadie lo leyera. El veredicto se puede
verificar contra la corrida en vez de contra la regla que lo produjo.

Dos cosas que confunden al leerla la primera vez:

- **`exit` aparece antes de `return`.** Es el orden real del runtime de
  DynaPyt: `_return_` avisa de la salida de la función y después del
  `return` que la causó.
- **La traza se corta a los 600 eventos.** Es para leerla, no para medir;
  los contadores del resumen siguen siendo exactos.

## Agregar un caso

Una carpeta con cuatro archivos:

```
casos/M09_mi_caso/
  submission.py            la entrega
  driver.py                la importa y la ejercita
  caso.json                {"espera": "M09", "nivel": 2, "funcion": "nombre_de_la_funcion"}
  respuesta_ejemplo.json   lo que un juez contestaria, en la forma de esa metrica
```

`correr.py` la encuentra sola. `respuesta_ejemplo.json` sólo hace falta
para `--juez`.
