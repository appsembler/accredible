from django.conf.urls import url
from views import request_certificate


urlpatterns = [
    url(r'^request_certificate$', request_certificate, name='request_certificate')
]
