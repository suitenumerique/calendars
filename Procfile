web: bin/scalingo_run_web
worker: celery -A calendars.celery_app worker --task-events --beat -l INFO -c $DJANGO_CELERY_CONCURRENCY -Q celery,default
# postdeploy: source bin/export_pg_vars.sh && python manage.py migrate && SQL_DIR=/app/sabredav/sql bash sabredav/init-database.sh
