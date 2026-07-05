import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "faso_isp_manager.settings")

application = get_wsgi_application()
