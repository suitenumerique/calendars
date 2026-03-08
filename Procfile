web: bin/scalingo_run_web
worker: python worker.py -c $WORKER_CONCURRENCY
postdeploy: source bin/export_pg_vars.sh && python manage.py migrate && SQL_DIR=/app/sabredav/sql bash sabredav/init-database.sh
