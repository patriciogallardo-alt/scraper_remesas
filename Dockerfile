# Usa la imagen oficial de Playwright que contiene los binarios de los navegadores instalados
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

# Directorio de trabajo en el contenedor
WORKDIR /app

# Copia los requerimientos y los instala
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instala gunicorn para el servidor web en producción
RUN pip install gunicorn

# Instala dependencias adicionales de navegador si Playwright lo exige
RUN playwright install chromium

# Copia todo el proyecto
COPY . .

# Expone el puerto 10000 (puerto por defecto sugerido en Render o similares)
EXPOSE 10000

# Comando para ejecutar la aplicación, apuntando al archivo "app.py" dentro de "web/"
# "web.app:app" significa buscar en el módulo "web/app.py" la variable "app"
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--timeout", "600", "web.app:app"]
