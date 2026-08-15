#!/usr/bin/env python3
"""
Descarga la campaña de Meta Ads desde Windsor.ai y genera docs/data.json.

Solo biblioteca estandar: funciona igual en el Mac de Victoria (python3.9)
y en el runner de GitHub Actions.

La API key se lee de la variable de entorno WINDSOR_API_KEY. Nunca se escribe
en disco ni aparece en la URL (va en la cabecera X-Api-Key).

Uso:
    WINDSOR_API_KEY=xxx python3 fetch_data.py
    WINDSOR_API_KEY=xxx python3 fetch_data.py --dry-run   # no escribe nada
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Madrid")
except Exception:  # pragma: no cover - fallback si no hay tzdata
    TZ = None

# --------------------------------------------------------------------------
# Configuracion
# --------------------------------------------------------------------------

BASE_URL = "https://connectors.windsor.ai/facebook"
CAMPAIGN_ID = os.environ.get("CAMPAIGN_ID", "52506066958996")
ACCOUNT_ID = os.environ.get("ACCOUNT_ID", "10156076156735123")
START_DATE = os.environ.get("START_DATE", "2026-07-31")
TARGET_CPL = float(os.environ.get("TARGET_CPL", "1.43"))

# Umbrales del semaforo. Todos ajustables por variable de entorno para poder
# moverlos sin tocar el codigo (p. ej. FREQ_AMBER=4 si la frecuencia alta
# resulta rentable y no molesta).
CPL_AMBER = float(os.environ.get("CPL_AMBER", "2.00"))
CPL_RED = float(os.environ.get("CPL_RED", "2.86"))            # 2x el objetivo
FREQ_AMBER = float(os.environ.get("FREQ_AMBER", "3.0"))
CTR_DROP_AMBER = float(os.environ.get("CTR_DROP_AMBER", "0.30"))
CONV_MIN_7D = int(os.environ.get("CONV_MIN_7D", "50"))
CONCENTRATION_RED = float(os.environ.get("CONCENTRATION_RED", "0.80"))
# Por debajo de este gasto diario no hay entrega que repartir: un dia con 0,01 EUR
# da un 100% matematico que no significa nada. Sin este minimo, la alerta de
# concentracion se dispara con dias en los que no paso nada.
MIN_DAY_SPEND = float(os.environ.get("MIN_DAY_SPEND", "1.00"))

DAILY_FIELDS = [
    "date", "campaign", "campaign_id", "adset_name", "adset_id",
    "ad_name", "ad_id", "spend", "impressions", "clicks", "link_clicks",
    "reach", "frequency", "actions_lead", "actions_landing_page_view",
]

# Sin "date": Windsor agrega sobre toda la ventana. Imprescindible para la
# frecuencia, que es un promedio y NO se puede sumar ni promediar por dias.
WINDOW_FIELDS = [
    "campaign_id", "adset_id", "adset_name", "ad_id", "ad_name",
    "spend", "impressions", "clicks", "reach", "frequency", "actions_lead",
]

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(ROOT, "docs", "data.json")


# --------------------------------------------------------------------------
# Utilidades numericas: Windsor devuelve null a punta pala
# --------------------------------------------------------------------------

def num(value):
    """null / '' / basura -> 0.0"""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def ratio(numerator, denominator):
    """Division protegida. Devuelve None si no se puede dividir.

    None significa "no calculable", que es distinto de 0. Hay dias con gasto
    y cero leads (CPL infinito, no cero) y dias con leads y cero gasto por
    atribucion diferida (CPL 0, que tampoco significa nada).
    """
    if not denominator:
        return None
    return numerator / float(denominator)


def today_madrid():
    if TZ is not None:
        return datetime.now(TZ).date()
    return date.today()


def dstr(d):
    return d.isoformat()


# --------------------------------------------------------------------------
# Llamadas a la API
# --------------------------------------------------------------------------

def windsor_get(api_key, fields, date_from, date_to):
    """GET a la API de conectores de Windsor. Devuelve la lista de filas."""
    params = {
        "fields": ",".join(fields),
        "date_from": date_from,
        "date_to": date_to,
        "_renderer": "json",
    }
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "X-Api-Key": api_key,
        "Accept": "application/json",
        "User-Agent": "pv-dashboard/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:500]
        raise SystemExit(
            "ERROR: Windsor devolvio HTTP %s para %s-%s\n%s"
            % (exc.code, date_from, date_to, body)
        )
    except urllib.error.URLError as exc:
        raise SystemExit("ERROR: no se pudo contactar con Windsor: %s" % exc.reason)

    rows = payload.get("data", payload.get("result", payload))
    if not isinstance(rows, list):
        raise SystemExit("ERROR: respuesta inesperada de Windsor: %r" % (payload,)[:300])
    # El filtrado por campana se hace aqui: la API no documenta un parametro
    # de filtro estable, y campaign_id es unico.
    return [r for r in rows if str(r.get("campaign_id") or "") == CAMPAIGN_ID]


# --------------------------------------------------------------------------
# Agregacion
# --------------------------------------------------------------------------

def blank():
    return {
        "spend": 0.0, "leads": 0.0, "impressions": 0.0, "clicks": 0.0,
        "link_clicks": 0.0, "reach": 0.0, "lpv": 0.0,
    }


def accumulate(bucket, row):
    bucket["spend"] += num(row.get("spend"))
    bucket["leads"] += num(row.get("actions_lead"))
    bucket["impressions"] += num(row.get("impressions"))
    bucket["clicks"] += num(row.get("clicks"))
    bucket["link_clicks"] += num(row.get("link_clicks"))
    bucket["reach"] += num(row.get("reach"))
    bucket["lpv"] += num(row.get("actions_landing_page_view"))
    return bucket


def finish(bucket, extra=None):
    out = dict(bucket)
    out["leads"] = int(round(out["leads"]))
    out["impressions"] = int(round(out["impressions"]))
    out["clicks"] = int(round(out["clicks"]))
    out["link_clicks"] = int(round(out["link_clicks"]))
    out["lpv"] = int(round(out["lpv"]))
    out["spend"] = round(out["spend"], 2)
    out["cpl"] = ratio(out["spend"], out["leads"])
    out["ctr"] = ratio(out["clicks"], out["impressions"])
    out["link_ctr"] = ratio(out["link_clicks"], out["impressions"])
    if out["cpl"] is not None:
        out["cpl"] = round(out["cpl"], 4)
    if extra:
        out.update(extra)
    return out


def sum_rows(rows):
    bucket = blank()
    for row in rows:
        accumulate(bucket, row)
    return finish(bucket)


# --------------------------------------------------------------------------
# Construccion del informe
# --------------------------------------------------------------------------

def build(daily_rows, last7_rows, window):
    today, yday, l7_from, l7_to, p7_from, p7_to = window

    campaign_name = ""
    for row in daily_rows:
        if row.get("campaign"):
            campaign_name = row["campaign"]
            break

    # --- serie diaria ---------------------------------------------------
    by_day = {}
    for row in daily_rows:
        day = str(row.get("date") or "")[:10]
        if not day:
            continue
        accumulate(by_day.setdefault(day, blank()), row)

    days_sorted = sorted(by_day)
    daily = []
    for day in days_sorted:
        entry = finish(by_day[day], {"date": day})
        entry["partial"] = (day == dstr(today))
        daily.append(entry)

    # --- totales y ventanas ---------------------------------------------
    totals = sum_rows(daily_rows)
    last7 = sum_rows([r for r in daily_rows
                      if l7_from <= str(r.get("date") or "")[:10] <= l7_to])
    prev7 = sum_rows([r for r in daily_rows
                      if p7_from <= str(r.get("date") or "")[:10] <= p7_to])

    yesterday = next((d for d in daily if d["date"] == dstr(yday)), None)

    # --- frecuencia real de la ventana de 7 dias -------------------------
    # Viene de la llamada agregada, no de promediar las diarias.
    freq_by_ad = {}
    freq_by_adset = {}
    for row in last7_rows:
        freq_by_ad[str(row.get("ad_id"))] = num(row.get("frequency"))
        aid = str(row.get("adset_id"))
        # A nivel de conjunto Windsor repite la fila por anuncio; nos quedamos
        # con la frecuencia mas alta observada como referencia conservadora.
        freq_by_adset[aid] = max(freq_by_adset.get(aid, 0.0), num(row.get("frequency")))

    # --- tabla por anuncio ----------------------------------------------
    ads_acc, ads_meta = {}, {}
    for row in daily_rows:
        key = str(row.get("ad_id"))
        accumulate(ads_acc.setdefault(key, blank()), row)
        ads_meta[key] = {
            "ad_id": key,
            "ad_name": row.get("ad_name") or "(sin nombre)",
            "adset_name": row.get("adset_name") or "",
            "adset_id": str(row.get("adset_id")),
        }
    ads = [finish(v, ads_meta[k]) for k, v in ads_acc.items()]
    for ad in ads:
        ad["frequency_7d"] = round(freq_by_ad.get(ad["ad_id"], 0.0), 2) or None

    # --- tabla por conjunto ----------------------------------------------
    sets_acc, sets_meta = {}, {}
    for row in daily_rows:
        key = str(row.get("adset_id"))
        accumulate(sets_acc.setdefault(key, blank()), row)
        sets_meta[key] = {
            "adset_id": key,
            "adset_name": row.get("adset_name") or "(sin nombre)",
        }
    adsets = [finish(v, sets_meta[k]) for k, v in sets_acc.items()]
    for st in adsets:
        st["frequency_7d"] = round(freq_by_adset.get(st["adset_id"], 0.0), 2) or None

    # leads de los ultimos 7 dias por conjunto (aprendizaje limitado)
    leads7_by_adset = {}
    for row in daily_rows:
        day = str(row.get("date") or "")[:10]
        if l7_from <= day <= l7_to:
            key = str(row.get("adset_id"))
            leads7_by_adset[key] = leads7_by_adset.get(key, 0.0) + num(row.get("actions_lead"))
    for st in adsets:
        st["leads_7d"] = int(round(leads7_by_adset.get(st["adset_id"], 0.0)))

    # ordenadas por CPL ascendente; las que no tienen CPL, al final
    sort_key = lambda r: (r["cpl"] is None, r["cpl"] if r["cpl"] is not None else 0)
    ads.sort(key=sort_key)
    adsets.sort(key=sort_key)

    # --- reparto de entrega ----------------------------------------------
    # Por dia y conjunto: que porcentaje del gasto se llevo cada anuncio.
    spend_map = {}
    for row in daily_rows:
        day = str(row.get("date") or "")[:10]
        if not day:
            continue
        key = (str(row.get("adset_id")), day, str(row.get("ad_id")))
        spend_map[key] = spend_map.get(key, 0.0) + num(row.get("spend"))

    delivery = []
    for st in sorted(adsets, key=lambda s: s["adset_name"]):
        aid = st["adset_id"]
        ad_ids = [a["ad_id"] for a in ads if a["adset_id"] == aid]
        ad_names = {a["ad_id"]: a["ad_name"] for a in ads}
        days = []
        for day in days_sorted:
            total = sum(spend_map.get((aid, day, x), 0.0) for x in ad_ids)
            shares = []
            for x in ad_ids:
                spent = spend_map.get((aid, day, x), 0.0)
                shares.append({
                    "ad_id": x,
                    "ad_name": ad_names.get(x, x),
                    "spend": round(spent, 2),
                    "pct": (spent / total) if total > 0 else None,
                })
            top = max((s["pct"] for s in shares if s["pct"] is not None), default=None)
            days.append({
                "date": day,
                "total": round(total, 2),
                "shares": shares,
                "top_pct": top,
                # Solo tiene sentido hablar de concentracion si hubo entrega real.
                "concentrated": bool(total >= MIN_DAY_SPEND and top is not None
                                     and top > CONCENTRATION_RED),
                "no_delivery": total <= 0,
                "negligible": bool(0 < total < MIN_DAY_SPEND),
            })
        delivery.append({
            "adset_id": aid,
            "adset_name": st["adset_name"],
            "ads": [{"ad_id": x, "ad_name": ad_names.get(x, x)} for x in ad_ids],
            "days": days,
        })

    # --- semaforo ---------------------------------------------------------
    alerts = build_alerts(last7, prev7, ads, adsets, delivery, l7_from, l7_to)

    return {
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds") if TZ
                        else datetime.now().isoformat(timespec="seconds"),
        "campaign": {"id": CAMPAIGN_ID, "name": campaign_name},
        "account_id": ACCOUNT_ID,
        "target_cpl": TARGET_CPL,
        "thresholds": {
            "cpl_amber": CPL_AMBER, "cpl_red": CPL_RED,
            "freq_amber": FREQ_AMBER, "ctr_drop_amber": CTR_DROP_AMBER,
            "conv_min_7d": CONV_MIN_7D, "concentration_red": CONCENTRATION_RED,
            "min_day_spend": MIN_DAY_SPEND,
        },
        "period": {"from": days_sorted[0] if days_sorted else START_DATE,
                   "to": days_sorted[-1] if days_sorted else dstr(today)},
        "windows": {"last7": {"from": l7_from, "to": l7_to},
                    "prev7": {"from": p7_from, "to": p7_to},
                    "yesterday": dstr(yday), "today": dstr(today)},
        "totals": totals,
        "last7": last7,
        "prev7": prev7,
        "yesterday": yesterday,
        "daily": daily,
        "ads": ads,
        "adsets": adsets,
        "delivery": delivery,
        "alerts": alerts,
    }


def eur(value):
    """1.1226 -> '1,12 EUR' con la coma decimal espanola."""
    return ("%.2f" % value).replace(".", ",") + " €"


def pct(value, decimals=0):
    fmt = "%." + str(decimals) + "f"
    return (fmt % (value * 100)).replace(".", ",") + " %"


def dia(iso):
    meses = ["ene", "feb", "mar", "abr", "may", "jun",
             "jul", "ago", "sep", "oct", "nov", "dic"]
    y, m, d = iso.split("-")
    return "%d de %s" % (int(d), meses[int(m) - 1])


def build_alerts(last7, prev7, ads, adsets, delivery, l7_from, l7_to):
    alerts = []

    # 1. CPL de los ultimos 7 dias
    cpl7 = last7["cpl"]
    if cpl7 is None:
        alerts.append({
            "level": "amber", "key": "cpl",
            "title": "Sin leads en 7 días",
            "detail": "%s gastados y ningún lead atribuido entre el %s y el %s."
                      % (eur(last7["spend"]), dia(l7_from), dia(l7_to)),
        })
    elif cpl7 > CPL_RED:
        alerts.append({
            "level": "red", "key": "cpl",
            "title": "CPL de 7 días en %s" % eur(cpl7),
            "detail": "Por encima de %s, que es el doble del objetivo de %s."
                      % (eur(CPL_RED), eur(TARGET_CPL)),
        })
    elif cpl7 > CPL_AMBER:
        alerts.append({
            "level": "amber", "key": "cpl",
            "title": "CPL de 7 días en %s" % eur(cpl7),
            "detail": "Por encima de %s. El objetivo es %s."
                      % (eur(CPL_AMBER), eur(TARGET_CPL)),
        })
    else:
        alerts.append({
            "level": "green", "key": "cpl",
            "title": "CPL de 7 días en %s" % eur(cpl7),
            "detail": "Dentro del objetivo de %s." % eur(TARGET_CPL),
        })

    # 2. Fatiga creativa: frecuencia 7d > 3
    fatigued = [a for a in ads
                if a.get("frequency_7d") and a["frequency_7d"] > FREQ_AMBER]
    if fatigued:
        peor = max(fatigued, key=lambda a: a["frequency_7d"])
        alerts.append({
            "level": "amber", "key": "frecuencia",
            "title": "Frecuencia por encima de %.0f" % FREQ_AMBER,
            "detail": "%d anuncio(s) con señal de fatiga creativa. El más quemado: "
                      "%s, con %s."
                      % (len(fatigued), peor["ad_name"],
                         ("%.2f" % peor["frequency_7d"]).replace(".", ",")),
        })
    else:
        vistos = [a["frequency_7d"] for a in ads if a.get("frequency_7d")]
        alerts.append({
            "level": "green", "key": "frecuencia",
            "title": "Frecuencia bajo control",
            "detail": ("Máximo de %s en 7 días, con el límite en %.0f."
                       % (("%.2f" % max(vistos)).replace(".", ","), FREQ_AMBER))
                      if vistos else "Sin entrega suficiente para medirla.",
        })

    # 3. Caida del CTR respecto a la semana anterior
    ctr_now, ctr_before = last7["ctr"], prev7["ctr"]
    if ctr_now is None or not ctr_before:
        alerts.append({
            "level": "green", "key": "ctr",
            "title": "CTR sin comparativa",
            "detail": "No hay datos suficientes de la semana anterior.",
        })
    else:
        change = (ctr_now - ctr_before) / ctr_before
        detalle = ("Del %s al %s respecto a la semana anterior."
                   % (pct(ctr_before, 2), pct(ctr_now, 2)))
        if change < -CTR_DROP_AMBER:
            alerts.append({
                "level": "amber", "key": "ctr",
                "title": "El CTR cae un %s" % pct(abs(change)),
                "detail": detalle,
            })
        else:
            alerts.append({
                "level": "green", "key": "ctr",
                "title": "El CTR %s un %s" % ("sube" if change >= 0 else "baja",
                                              pct(abs(change))),
                "detail": detalle,
            })

    # 4. Aprendizaje limitado: < 50 conversiones/7d por conjunto
    flojos = [s for s in adsets if s.get("leads_7d", 0) < CONV_MIN_7D]
    if flojos:
        peor = min(flojos, key=lambda s: s.get("leads_7d", 0))
        alerts.append({
            "level": "amber", "key": "aprendizaje",
            "title": "Aprendizaje limitado",
            "detail": "%d conjunto(s) por debajo de %d conversiones en 7 días. "
                      "El más bajo es %s, con %d."
                      % (len(flojos), CONV_MIN_7D, peor["adset_name"],
                         peor.get("leads_7d", 0)),
        })
    else:
        alerts.append({
            "level": "green", "key": "aprendizaje",
            "title": "Fuera de aprendizaje limitado",
            "detail": "Todos los conjuntos superan las %d conversiones en 7 días."
                      % CONV_MIN_7D,
        })

    # 5. Concentracion de entrega en los ultimos 7 dias
    concentrados = []
    for block in delivery:
        for day in block["days"]:
            if l7_from <= day["date"] <= l7_to and day["concentrated"]:
                lider = max((s for s in day["shares"] if s["pct"] is not None),
                            key=lambda s: s["pct"])
                concentrados.append((day["date"], block["adset_name"], lider))
    if concentrados:
        ultimo = concentrados[-1]
        nombres = sorted({c[2]["ad_name"] for c in concentrados})
        alerts.append({
            "level": "red" if len(concentrados) >= 3 else "amber",
            "key": "entrega",
            "title": "Meta concentra la entrega",
            "detail": "%d de los últimos 7 días con un anuncio por encima del %s "
                      "del gasto de su conjunto. El último, el %s: «%s» se llevó "
                      "el %s. Los demás creativos se quedan sin datos."
                      % (len(concentrados), pct(CONCENTRATION_RED), dia(ultimo[0]),
                         ultimo[2]["ad_name"], pct(ultimo[2]["pct"])),
            "ads": nombres,
        })
    else:
        alerts.append({
            "level": "green", "key": "entrega",
            "title": "Entrega repartida",
            "detail": "Ningún anuncio superó el %s del gasto de su conjunto "
                      "en los últimos 7 días." % pct(CONCENTRATION_RED),
        })

    return alerts


# --------------------------------------------------------------------------

def main():
    dry_run = "--dry-run" in sys.argv

    api_key = os.environ.get("WINDSOR_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "ERROR: falta WINDSOR_API_KEY.\n"
            "  export WINDSOR_API_KEY=$(cat ~/.config/windsor/api_key)"
        )

    today = today_madrid()
    yday = today - timedelta(days=1)
    l7_from, l7_to = dstr(today - timedelta(days=7)), dstr(yday)
    p7_from, p7_to = dstr(today - timedelta(days=14)), dstr(today - timedelta(days=8))
    window = (today, yday, l7_from, l7_to, p7_from, p7_to)

    sys.stderr.write("Descargando %s -> %s...\n" % (START_DATE, dstr(today)))
    daily_rows = windsor_get(api_key, DAILY_FIELDS, START_DATE, dstr(today))
    if not daily_rows:
        raise SystemExit(
            "ERROR: cero filas para la campana %s. No se sobrescribe data.json."
            % CAMPAIGN_ID
        )
    sys.stderr.write("  %d filas diarias\n" % len(daily_rows))

    # Segunda llamada, agregada sobre la ventana de 7 dias: la frecuencia es un
    # promedio de Meta y no se puede reconstruir sumando o promediando los dias.
    last7_rows = windsor_get(api_key, WINDOW_FIELDS, l7_from, l7_to)
    sys.stderr.write("  ventana 7d: %d filas\n" % len(last7_rows))

    report = build(daily_rows, last7_rows, window)

    if dry_run:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return

    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    os.replace(tmp, OUT_PATH)  # atomico: nunca se queda un JSON a medias

    cpl7 = report["last7"]["cpl"]
    sys.stderr.write(
        "OK -> %s | CPL global %.4f | CPL 7d %s\n"
        % (OUT_PATH,
           report["totals"]["cpl"] or 0,
           ("%.4f" % cpl7) if cpl7 is not None else "n/d")
    )


if __name__ == "__main__":
    main()
