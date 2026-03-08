import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mediap.settings')
django.setup()

from django.contrib.auth import get_user_model
User = get_user_model()

if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
    print('Superuser "admin" created with password "admin123"')
else:
    print('Superuser "admin" already exists')
