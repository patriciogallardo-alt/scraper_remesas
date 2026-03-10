"""Verify exchange rates are now correct."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with open('data/remesas_20260310_095127.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"{'País':<12} {'Mon':<5} {'Recibido':>12} {'Tasa (1 dest = X CLP)':>22} {'Verificación':>14}")
print("-" * 72)

seen = set()
for r in data['results']:
    key = f"{r['pais_destino']}_{r['moneda_destino']}"
    if key in seen:
        continue
    seen.add(key)
    
    recv = r['monto_recibido']
    calc_rate = r['monto_enviado'] / recv if recv > 0 else 0
    saved_rate = r['tasa_de_cambio']
    match = "✓" if abs(saved_rate - calc_rate) < 1 else "✗"
    
    print(f"{r['pais_destino']:<12} {r['moneda_destino']:<5} {recv:>12.2f} {saved_rate:>22.4f} {match:>14}")
