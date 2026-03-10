"""
Flask web dashboard para el scraper de remesas.
"""
import asyncio
import os
import logging
from flask import Flask, render_template, jsonify, send_file
from src.exporter import load_latest_run, export_to_excel, save_json
from src.orchestrator import run_all_scrapers
from src.config import DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = Flask(__name__)

# Global state for scraping status
scraping_status = {"running": False, "message": ""}


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/data")
def get_data():
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


@app.route("/api/scrape", methods=["POST"])
def trigger_scrape():
    if scraping_status["running"]:
        return jsonify({"status": "busy", "message": "Scraping ya en ejecución"}), 409

    scraping_status["running"] = True
    scraping_status["message"] = "Ejecutando scrapers..."

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        scrape_run = loop.run_until_complete(run_all_scrapers())
        loop.close()

        if scrape_run.results:
            save_json(scrape_run)
            export_to_excel(scrape_run)

        scraping_status["message"] = (
            f"Completado: {scrape_run.total_quotes} cotizaciones "
            f"en {scrape_run.duration_seconds}s"
        )
        return jsonify({
            "status": "ok",
            "total_quotes": scrape_run.total_quotes,
            "duration": scrape_run.duration_seconds,
            "errors": scrape_run.errors,
        })
    except Exception as e:
        scraping_status["message"] = f"Error: {str(e)}"
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        scraping_status["running"] = False


@app.route("/api/status")
def get_status():
    return jsonify(scraping_status)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
