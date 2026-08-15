#!/usr/bin/env python3
"""
Prueba build() contra datos reales de la campana, sin tocar la API.

    python3 tests/test_build.py            # comprueba
    python3 tests/test_build.py --write    # ademas escribe docs/data.json

Los numeros esperados salen de sumar a mano el fixture. Si build() cambia y
estos numeros dejan de cuadrar, algo se ha roto.
"""

import json
import os
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fetch_data  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixture_2026-08-15.json")

fails = []
total_checks = 0


def check(label, got, want, tol=0.005):
    global total_checks
    total_checks += 1
    ok = (got == want) if isinstance(want, (str, type(None), bool)) \
        else (got is not None and abs(got - want) <= tol)
    print("  %-46s %-22s %s" % (
        label, got if not isinstance(got, float) else round(got, 4),
        "OK" if ok else "FALLA (esperado %s)" % want))
    if not ok:
        fails.append(label)


def main():
    with open(FIXTURE, encoding="utf-8") as handle:
        fx = json.load(handle)

    today = date.fromisoformat(fx["today"])
    yday = today - timedelta(days=1)
    window = (
        today, yday,
        (today - timedelta(days=7)).isoformat(), yday.isoformat(),
        (today - timedelta(days=14)).isoformat(),
        (today - timedelta(days=8)).isoformat(),
    )

    rep = fetch_data.build(fx["daily"], fx["last7"], window)

    print("\nTOTALES DEL PERIODO")
    check("gasto total", rep["totals"]["spend"], 263.96)
    check("leads totales", rep["totals"]["leads"], 184)
    check("CPL global (referencia de Victoria: 1,43)",
          rep["totals"]["cpl"], 1.4346, tol=0.001)

    print("\nVENTANA DE 7 DIAS (08-08 a 08-14)")
    check("desde", rep["windows"]["last7"]["from"], "2026-08-08")
    check("hasta", rep["windows"]["last7"]["to"], "2026-08-14")
    check("gasto 7d", rep["last7"]["spend"], 96.54)
    check("leads 7d", rep["last7"]["leads"], 86)
    check("CPL 7d", rep["last7"]["cpl"], 1.1226, tol=0.001)
    check("CPL semana anterior", rep["prev7"]["cpl"], 1.7163, tol=0.001)

    print("\nAYER (08-14)")
    check("gasto de ayer", rep["yesterday"]["spend"], 20.62)
    check("leads de ayer", rep["yesterday"]["leads"], 23)
    check("CPL de ayer", rep["yesterday"]["cpl"], 0.8965, tol=0.001)

    print("\nDIVISIONES POR CERO")
    d0806 = next(d for d in rep["daily"] if d["date"] == "2026-08-06")
    check("06-ago: 1 lead con 0 gasto en A1 -> CPL del dia calculable",
          d0806["cpl"] is not None, True)
    d0813 = next(d for d in rep["daily"] if d["date"] == "2026-08-13")
    check("13-ago: 0,01 EUR y 0 leads -> CPL None, no infinito",
          d0813["cpl"], None)
    a1 = next(a for a in rep["ads"] if "Por dentro" in a["ad_name"])
    check("A1 'Por dentro': 2 leads, gasto 6,63", a1["spend"], 6.63)
    check("A1 CPL", a1["cpl"], 3.315, tol=0.01)

    print("\nFRECUENCIA REAL DE 7 DIAS (de la llamada agregada)")
    temario = next(a for a in rep["ads"] if "Temario" in a["ad_name"])
    orden = next(a for a in rep["ads"] if "Orden" in a["ad_name"])
    check("Temario frecuencia 7d", temario["frequency_7d"], 1.30, tol=0.01)
    check("Orden frecuencia 7d", orden["frequency_7d"], 1.56, tol=0.01)
    check("A1 sin entrega en 7d -> sin frecuencia",
          a1["frequency_7d"], None)

    print("\nORDEN DE LAS TABLAS (CPL ascendente)")
    cpls = [a["cpl"] for a in rep["ads"]]
    check("anuncios ordenados por CPL", cpls == sorted(
        cpls, key=lambda c: (c is None, c if c is not None else 0)), True)
    check("el mas barato es 'Orden'", "Orden" in rep["ads"][0]["ad_name"], True)

    print("\nREPARTO DE ENTREGA")
    block = rep["delivery"][0]
    dias = {d["date"]: d for d in block["days"]}
    check("07-ago: Temario se lo lleva todo", dias["2026-08-07"]["top_pct"], 1.0)
    check("07-ago marcado en rojo", dias["2026-08-07"]["concentrated"], True)
    check("31-jul: reparto entre 3 -> sin marcar",
          dias["2026-07-31"]["concentrated"], False)
    check("31-jul: cuota mayor 59%", dias["2026-07-31"]["top_pct"], 0.5896, tol=0.001)
    check("10-ago: Orden 99,7% -> marcado",
          dias["2026-08-10"]["concentrated"], True)
    check("14-ago: 69/31 -> sin marcar",
          dias["2026-08-14"]["concentrated"], False)
    # 13-ago tuvo 0,01 EUR: el 100% es matematico, no es concentracion real.
    check("13-ago: 0,01 EUR -> NO se marca pese al 100%",
          dias["2026-08-13"]["concentrated"], False)
    check("13-ago: marcado como gasto insignificante",
          dias["2026-08-13"]["negligible"], True)
    check("13-ago: su cuota sigue siendo 100%", dias["2026-08-13"]["top_pct"], 1.0)
    conc = [d["date"] for d in block["days"] if d["concentrated"]]
    print("     dias concentrados: %s" % ", ".join(conc))

    print("\nSEMAFORO")
    for al in rep["alerts"]:
        print("  [%-5s] %-34s %s" % (al["level"], al["title"], al["detail"][:70]))
    niveles = {a["key"]: a["level"] for a in rep["alerts"]}
    check("CPL en verde (1,12 < 2,00)", niveles["cpl"], "green")
    check("frecuencia en verde (1,56 < 4)", niveles["frecuencia"], "green")
    check("CTR en verde (sube)", niveles["ctr"], "green")
    check("aprendizaje en verde (86 >= 50)", niveles["aprendizaje"], "green")
    check("entrega marcada (hubo concentracion en 7d)",
          niveles["entrega"] in ("amber", "red"), True)

    print("\nCOHERENCIA")
    suma_ads = round(sum(a["spend"] for a in rep["ads"]), 2)
    check("gasto por anuncio = gasto total", suma_ads, 263.96)
    suma_dias = round(sum(d["spend"] for d in rep["daily"]), 2)
    check("gasto por dia = gasto total", suma_dias, 263.96)
    leads_ads = sum(a["leads"] for a in rep["ads"])
    check("leads por anuncio = leads totales", leads_ads, 184)

    if "--write" in sys.argv:
        out = os.path.join(ROOT, "docs", "data.json")
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(rep, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        print("\nEscrito %s" % out)

    print("\n%s" % ("TODO OK (%d comprobaciones)" % total_checks if not fails
                    else "FALLAN %d de %d: %s"
                         % (len(fails), total_checks, ", ".join(fails))))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
