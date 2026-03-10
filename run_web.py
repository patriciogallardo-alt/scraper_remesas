"""
Script para levantar el dashboard web.
Uso: python run_web.py
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web.app import app

if __name__ == "__main__":
    print("=" * 50)
    print("  Dashboard de Remesas")
    print("  http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, port=5000, host="0.0.0.0")
