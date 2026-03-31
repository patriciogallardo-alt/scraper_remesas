"""
Flask web dashboard para el scraper de remesas.
"""
import asyncio
import os
import logging
import requests
import threading
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, send_file, request
from src.exporter import load_latest_run, export_to_excel, save_json
from src.orchestrator import run_all_scrapers

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = Flask(__name__)

# Global state for scraping status
scraping_status = {"running": False, "message": ""}

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def save_to_supabase(results):
    if not SUPABASE_URL or not SUPABASE_KEY:
        logging.warning("Supabase no configurado, omitiendo guardado en base de datos.")
        return False

    url = f"{SUPABASE_URL}/rest/v1/remittance_quotes"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    
    # Preparamos los datos
    payload = []
    for r in results:
        # Convert objects to dicts matching Supabase columns
        d = r.to_dict()
        payload.append({
            "timestamp_scrape": d.get("timestamp"),
            "agente": d.get("agente"),
            "metodo_dispersion": d.get("metodo_dispersion"),
            "categoria_recaudacion": d.get("categoria_recaudacion"),
            "categoria_dispersion": d.get("categoria_dispersion"),
            "pais_destino": d.get("pais_destino"),
            "moneda_origen": d.get("moneda_origen"),
            "moneda_destino": d.get("moneda_destino"),
            "monto_enviado": d.get("monto_enviado"),
            "monto_recibido": d.get("monto_recibido"),
            "tasa_de_cambio": d.get("tasa_de_cambio"),
            "tasa_cambio_normalizada": d.get("tasa_cambio_normalizada"),
            "tasa_cambio_final": d.get("tasa_cambio_final"),
            "fee_base": d.get("fee_base"),
            "fee_impuesto": d.get("fee_impuesto"),
            "total_cobrado": d.get("total_cobrado"),
            "metodo_recaudacion": d.get("metodo_recaudacion")
        })
        
    try:
        resp = requests.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        logging.info(f"Guardadas {len(payload)} cotizaciones en Supabase exitosamente.")
        return True
    except Exception as e:
        logging.error(f"Error guardando en Supabase: {str(e)}")
        if hasattr(e, 'response') and e.response:
            logging.error(f"Respuesta Supabase: {e.response.text}")
        return False

def fetch_latest_from_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
        
    url = f"{SUPABASE_URL}/rest/v1/remittance_quotes"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        # 1. Traer el timestamp más reciente
        ts_url = f"{url}?select=timestamp_scrape&order=timestamp_scrape.desc&limit=1"
        ts_resp = requests.get(ts_url, headers=headers, timeout=10)
        if not ts_resp.ok or not ts_resp.json():
            return None
            
        latest_ts = ts_resp.json()[0]["timestamp_scrape"]
        
        # 2. Traer todos los registros con ese timestamp
        data_url = f"{url}?timestamp_scrape=eq.{latest_ts}"
        data_headers = {**headers, "Range": "0-9999"}
        data_resp = requests.get(data_url, headers=data_headers, timeout=15)
        if not data_resp.ok:
            return None
            
        results = data_resp.json()
        
        # Mapear 'timestamp_scrape' a 'timestamp' para compatibilidad con el frontend
        for r in results:
            r["timestamp"] = r.pop("timestamp_scrape", "")
            
        return {
            "results": results,
            "metadata": {
                "timestamp": latest_ts,
                "total_quotes": len(results),
                "duration_seconds": "N/D (Nube)"
            }
        }
    except Exception as e:
        logging.error(f"Error cargando de Supabase: {e}")
        return None

def fetch_range_from_supabase(days):
    """Fetch all records within the last N days from Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    if not days or int(days) <= 0:
        return fetch_latest_from_supabase()
        
    url = f"{SUPABASE_URL}/rest/v1/remittance_quotes"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    threshold_date = (datetime.utcnow() - timedelta(days=int(days))).isoformat()
    
    try:
        data_url = f"{url}?timestamp_scrape=gte.{threshold_date}&order=timestamp_scrape.desc"
        data_headers = {**headers, "Range": "0-9999"}
        data_resp = requests.get(data_url, headers=data_headers, timeout=30)
        if not data_resp.ok:
            return None
            
        results = data_resp.json()
        
        # Mapear 'timestamp_scrape' a 'timestamp'
        for r in results:
            r["timestamp"] = r.pop("timestamp_scrape", "")
            
        latest_ts = results[0]["timestamp"] if results else None
            
        return {
            "results": results,
            "metadata": {
                "timestamp": latest_ts,
                "total_quotes": len(results),
                "duration_seconds": f"Últimos {days} días"
            }
        }
    except Exception as e:
        logging.error(f"Error cargando rango de Supabase: {e}")
        return None

def fetch_history_from_supabase(country, days=7, currency=None, cat_rec=None, cat_disp=None, agents=None):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
        
    url = f"{SUPABASE_URL}/rest/v1/remittance_quotes"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    threshold_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
    
    query_url = f"{url}?select=timestamp_scrape,agente,tasa_cambio_final&pais_destino=eq.{country}"
    if currency:
        query_url += f"&moneda_destino=eq.{currency}"
    if cat_rec:
        query_url += f"&categoria_recaudacion=in.({','.join(cat_rec.split(','))})"
    if cat_disp:
        query_url += f"&categoria_dispersion=in.({','.join(cat_disp.split(','))})"
    if agents:
        query_url += f"&agente=in.({','.join(agents.split(','))})"
        
    query_url += f"&timestamp_scrape=gte.{threshold_date}&order=timestamp_scrape.asc"
    
    try:
        resp = requests.get(query_url, headers=headers, timeout=15)
        if not resp.ok:
            return []
        results = resp.json()
        
        # Mapear
        for r in results:
            r["timestamp"] = r.pop("timestamp_scrape", "")
        return results
    except Exception as e:
        logging.error(f"Error cargando historia de Supabase: {e}")
        return []


def fetch_total_count_from_supabase(days=0):
    """Get exact count of records from Supabase without downloading data."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return 0
    url = f"{SUPABASE_URL}/rest/v1/remittance_quotes"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "count=exact",
        "Range": "0-0"
    }
    try:
        query_url = f"{url}?select=id"
        if days and int(days) > 0:
            threshold_date = (datetime.utcnow() - timedelta(days=int(days))).isoformat()
            query_url += f"&timestamp_scrape=gte.{threshold_date}"
        resp = requests.get(query_url, headers=headers, timeout=10)
        # Supabase returns count in Content-Range header: "0-0/13626"
        content_range = resp.headers.get('Content-Range', '')
        if '/' in content_range:
            return int(content_range.split('/')[1])
        return len(resp.json()) if resp.ok else 0
    except Exception as e:
        logging.error(f"Error obteniendo count de Supabase: {e}")
        return 0


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/data")
def get_data():
    days = request.args.get('days', 0, type=int)
    
    if days > 0:
        total_count = fetch_total_count_from_supabase(days)
        supabase_data = fetch_range_from_supabase(days)
    else:
        supabase_data = fetch_latest_from_supabase()
        # For "latest quote" mode, count = number of results in the latest batch
        total_count = len(supabase_data.get("results", [])) if supabase_data else 0

    if supabase_data and supabase_data["results"]:
        supabase_data["metadata"]["total_count"] = total_count
        return jsonify(supabase_data)

    # Fallback al archivo local si falla
    run = load_latest_run()
    if not run:
        return jsonify({"results": [], "metadata": None})

    return jsonify({
        "results": [r.to_dict() for r in run.results],
        "metadata": {
            "timestamp": run.timestamp,
            "duration_seconds": run.duration_seconds,
            "total_quotes": run.total_quotes,
            "errors": run.errors,
        }
    })


@app.route("/api/data/download")
def download_excel():
    run = load_latest_run()
    if not run or not run.results:
        return jsonify({"error": "No hay datos disponibles"}), 404

    filepath = export_to_excel(run, filename="remesas_descarga.xlsx")
    return send_file(
        filepath,
        as_attachment=True,
        download_name="remesas.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def background_scrape(is_manual=False, amount=None):
    global scraping_status
    if not is_manual:
        if scraping_status.get("running", False):
            logging.info("Scraping ya en ejecución, saltando tarea programada.")
            return
        scraping_status["running"] = True
        
    try:
        if amount is not None:
            logging.info(f"Scraping manual con monto personalizado: {amount} CLP")
            
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # Pass amount cleanly through the orchestrator. If None, it automatically falls back to config.SEND_AMOUNT_CLP
        scrape_run = loop.run_until_complete(run_all_scrapers(amount=amount))
        loop.close()

        if scrape_run.results:
            save_json(scrape_run)
            export_to_excel(scrape_run)
            save_to_supabase(scrape_run.results)

        scraping_status["message"] = f"Completado exitosamente: {scrape_run.total_quotes} cotizaciones"
    except Exception as e:
        scraping_status["message"] = f"Error: {str(e)}"
        logging.error(f"Background scrape failed: {e}")
    finally:
        scraping_status["running"] = False

# ===== Configuración de Cron (Chile) =====
_scheduler_started = False
_scheduler_lock = threading.Lock()

def init_scheduler():
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            logging.info("Scheduler ya fue iniciado, omitiendo.")
            return
        _scheduler_started = True
    
    try:
        santiago_tz = pytz.timezone('America/Santiago')
        scheduler = BackgroundScheduler(timezone=santiago_tz)
        
        # Horarios acordados: 09:00, 11:00, 13:00, 16:00, 18:00, 20:00
        scheduler.add_job(
            func=background_scrape,
            trigger="cron",
            hour="9,11,13,16,18,20",
            minute="0",
            id="scraper_diario",
            replace_existing=True
        )
        
        scheduler.start()
        
        # Log all registered jobs for verification
        jobs = scheduler.get_jobs()
        logging.info(f"APScheduler iniciado exitosamente con {len(jobs)} trabajo(s) registrado(s).")
        for job in jobs:
            logging.info(f"  Job: {job.id} | Próxima ejecución: {job.next_run_time}")
    except Exception as e:
        logging.error(f"Error al iniciar APScheduler: {e}")
        _scheduler_started = False

# Iniciar el scheduler:
# - En Gunicorn: WERKZEUG_RUN_MAIN no existe, se inicia al importar el módulo
# - En Flask dev: Solo se inicia en el proceso child (donde WERKZEUG_RUN_MAIN='true')
#   para evitar doble ejecución con el reloader
is_gunicorn = "gunicorn" in os.environ.get("SERVER_SOFTWARE", "")
is_flask_main = os.environ.get("WERKZEUG_RUN_MAIN") == "true"

if is_gunicorn or is_flask_main or not os.environ.get("WERKZEUG_RUN_MAIN"):
    init_scheduler()


@app.route("/api/history")
def get_history():
    country = request.args.get("country")
    if not country:
        return jsonify([])
    days = request.args.get("days", default=7, type=int)
    currency = request.args.get("currency")
    cat_rec = request.args.get("catRec")
    cat_disp = request.args.get("catDisp")
    agents = request.args.get("agent")
    
    data = fetch_history_from_supabase(country, days, currency, cat_rec, cat_disp, agents)
    return jsonify(data)

@app.route("/api/scrape", methods=["POST"])
def trigger_scrape():
    if scraping_status["running"]:
        return jsonify({"status": "busy", "message": "Scraping ya en ejecución"}), 409

    # Read optional custom amount from request body
    amount = None
    if request.is_json and request.json:
        amount = request.json.get("amount")

    scraping_status["running"] = True
    amount_label = f" (monto: {int(amount):,} CLP)" if amount else ""
    scraping_status["message"] = f"Ejecutando scrapers en segundo plano{amount_label}..."

    thread = threading.Thread(target=background_scrape, args=(True, amount))
    thread.daemon = True
    thread.start()

    return jsonify({
        "status": "started",
        "message": f"Scraping iniciado en segundo plano{amount_label}. Los datos se actualizarán automáticamente en ~5 minutos."
    })


@app.route("/api/status")
def get_status():
    return jsonify(scraping_status)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
