# gunicorn_conf.py
# Production configuration for Gunicorn with UvicornWorker on Linux / Docker

bind = "0.0.0.0:8000"
workers = 4
worker_class = "uvicorn.workers.UvicornWorker"
keepalive = 120
timeout = 30
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
