# Control de la campaña «Descarga Dossier CTN — Prospecting España»

Panel de una sola página para vigilar la campaña de Meta Ads de Planeta Vital.
Sin servidor, sin base de datos: un script escribe un JSON y una página estática
lo lee.

- **Fuente:** API de conectores de Windsor.ai, conector `facebook`.
- **Cuenta:** `10156076156735123` · **Campaña:** `52506066958996`
- **Referencia:** CPL objetivo **1,43 €** (el real del 31-jul al 15-ago-2026).

## Cómo funciona

```
GitHub Actions (cron diario)
   └─ fetch_data.py  ──GET──▶  connectors.windsor.ai/facebook
                                    │
                                    ▼
                            docs/data.json  ──lee──▶  docs/index.html
                                                          (GitHub Pages)
```

`fetch_data.py` hace **dos** llamadas:

1. **Diaria**, con el campo `date`: alimenta la serie temporal y todos los
   agregados por suma.
2. **Agregada de 7 días**, sin el campo `date`: solo para la **frecuencia**.
   La frecuencia es un promedio de Meta (impresiones ÷ personas alcanzadas) y
   **no se puede reconstruir sumando o promediando los valores diarios** — daría
   ~1,15 donde la real es 1,30 o 1,56.

El filtrado por campaña se hace en Python, no en la URL: la API no documenta un
parámetro de filtro estable y `campaign_id` es único.

## Campos y trampas

Los 15 campos usados están verificados contra el conector. **No existen los
campos `leads` ni `cost_per_lead`**: el CPL se calcula como `spend / actions_lead`.

Divisiones por cero, todas contempladas:

| Caso real | Qué hace |
|---|---|
| 13-ago: 0,01 € y 0 leads | CPL = `n/d`, nunca infinito ni cero |
| 6-ago: el anuncio A1 tuvo 1 lead con 0 € de gasto (atribución diferida) | el lead cuenta; el CPL del anuncio se calcula sobre su gasto total |
| Un anuncio sin entrega en la ventana de 7 días | frecuencia `n/d`, no 0 |
| 13-ago: un solo anuncio se llevó el 100 % de 0,01 € | **no** se marca como concentración: por debajo de `MIN_DAY_SPEND` no hay entrega que repartir |

Windsor devuelve `null` en abundancia (`link_clicks`, `actions_lead`…). Todo pasa
por `num()`, que convierte `null` en 0.

## Umbrales del semáforo

Se ajustan por variable de entorno, sin tocar el código:

| Variable | Por defecto | Qué marca |
|---|---|---|
| `CPL_AMBER` | `2.00` | CPL de 7 días por encima → ámbar |
| `CPL_RED` | `2.86` | el doble del objetivo → rojo |
| `FREQ_AMBER` | `4.0` | frecuencia de 7 días por encima → ámbar (fatiga) |
| `CTR_DROP_AMBER` | `0.30` | caída del CTR mayor del 30 % vs. semana anterior |
| `CONV_MIN_7D` | `50` | conjunto por debajo → aprendizaje limitado |
| `CONCENTRATION_RED` | `0.80` | un anuncio por encima de esta cuota del gasto del conjunto |
| `MIN_DAY_SPEND` | `1.00` | gasto diario mínimo para que un día cuente |
| `TARGET_CPL` | `1.43` | el objetivo de referencia |

## Actualizar a mano

```bash
./actualizar.sh
```

La clave se guarda una sola vez, fuera del repositorio:

```bash
mkdir -p ~/.config/windsor && read -s -p "Windsor API key: " k && printf '%s' "$k" > ~/.config/windsor/api_key && chmod 600 ~/.config/windsor/api_key
```

En GitHub la clave vive en **Settings → Secrets and variables → Actions**, como
`WINDSOR_API_KEY`. **Nunca en el repositorio.**

## Comprobaciones

```bash
python3 tests/test_build.py
```

38 comprobaciones sobre datos reales congelados (`tests/fixture_2026-08-15.json`),
sin llamar a la API ni necesitar la clave. Cubren totales, ventanas de 7 días,
divisiones por cero, orden de las tablas, reparto de entrega y semáforo.

Con `--write` además regenera `docs/data.json` a partir del fixture, útil para
trabajar en el front sin gastar llamadas.

## Si algo falla

- **El panel dice «No se han podido cargar los datos»** → `docs/data.json` no
  existe todavía o Pages aún no lo ha publicado. Mira la pestaña Actions.
- **La Action falla** → casi siempre es la clave: caducada, mal copiada o el
  secret no existe. El script lo dice en el log.
- **Los datos no cambian** → Windsor puede ir con retraso respecto a Meta. El
  pie del panel indica la hora exacta de la última descarga.
- **Las Actions programadas se desactivan solas** si el repositorio pasa 60 días
  sin actividad. Aquí no pasa: `generated_at` cambia en cada ejecución, así que
  siempre hay un commit diario.

## Decisiones que conviene no deshacer sin pensarlo

- **Tres paneles separados para gasto, leads y CPL**, no uno con dos ejes. Un
  gráfico de doble eje inventa una correlación que no está en los datos.
- **El color sigue al anuncio, no a su posición en la tabla.** Las tablas se
  ordenan por CPL, que cambia a diario; si el color siguiera al orden, cada
  mañana los reels cambiarían de color y la lectura se rompería.
- **El porcentaje solo se escribe en el día concentrado más reciente.** Un número
  sobre cada barra se solapa con el vecino y no lo lee nadie; la marca roja bajo
  el eje ya da la señal en todos, y la tabla tiene todas las cifras.
- **La paleta está validada** (bandas de luminosidad, suelo de croma, separación
  para daltonismo y contraste) en modo claro y oscuro.
