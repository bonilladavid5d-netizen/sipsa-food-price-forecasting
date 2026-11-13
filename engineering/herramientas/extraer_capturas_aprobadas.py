"""Construye config/capturas_aprobadas.json: referencia verificable de los metadatos de captura.

Lee, sin extraer, los ZIP congelados de fuentes y su MANIFIESTO_ENTREGA.sha256 interno. Para cada
JSON lateral exige que su SHA-256 coincida con el manifiesto del ZIP y que describa el mismo XLSX
aprobado en config/fuentes_congeladas.json. Registra el SHA-256 del JSON y su `retrieved_at`
literal: esa fecha es la única fuente de `first_seen_at`. No inventa ni corrige fechas.
Uso: python herramientas/extraer_capturas_aprobadas.py ZIP_2018_2021 ZIP_2022_2025
"""
import hashlib, json, sys, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sha = lambda b: hashlib.sha256(b).hexdigest()
fuentes = json.loads((ROOT / "config/fuentes_congeladas.json").read_text())
por_ruta = {f["local_path"]: f for f in fuentes}
capturas, zips = [], []
for zp in map(Path, sys.argv[1:3]):
    zb = zp.read_bytes()
    with zipfile.ZipFile(zp) as z:
        man_bytes = z.read("MANIFIESTO_ENTREGA.sha256")
        man = {l.split("  ", 1)[1]: l.split("  ", 1)[0] for l in man_bytes.decode().splitlines() if l.strip()}
        zips.append({"zip": zp.name, "zip_sha256": sha(zb), "manifiesto_sha256": sha(man_bytes)})
        for name, h in sorted(man.items()):
            if not name.endswith(".json"):
                continue
            data = z.read(name)
            assert sha(data) == h, f"JSON distinto de su manifiesto: {name}"
            meta = json.loads(data)
            xlsx = name[:-5] + ".xlsx"
            f = por_ruta[xlsx]
            assert meta["sha256"] == f["sha256"] == man[xlsx], f"El JSON no describe el XLSX aprobado: {name}"
            capturas.append({"local_path": xlsx, "sidecar_path": name, "sidecar_sha256": h, "sidecar_bytes": len(data),
                             "source_sha256": f["sha256"], "retrieved_at": meta["retrieved_at"],
                             "historical_release_at": meta.get("historical_release_at"), "zip": zp.name})
assert len(capturas) == len(fuentes) == 17, len(capturas)
out = {"version": "capturas-v1",
       "descripcion": "Metadatos de captura aprobados. first_seen_at = retrieved_at literal del JSON lateral verificado contra el manifiesto del ZIP congelado.",
       "origen": zips, "capturas": sorted(capturas, key=lambda c: c["local_path"])}
(ROOT / "config/capturas_aprobadas.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print("OK", len(capturas), "capturas;", min(c["retrieved_at"] for c in capturas), "..", max(c["retrieved_at"] for c in capturas))
