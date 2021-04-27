from django.conf.urls import url
from views import request_certificate
from views import update_certificate


urlpatterns = [
    url(r'^request_certificate$', request_certificate, name='request_certificate'),
    url(r'^update_certificate$', update_certificate, name='update_certificate')
]
