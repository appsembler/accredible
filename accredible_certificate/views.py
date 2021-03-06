"""URL handlers related to certificate handling by LMS"""
from dogapi import dog_stats_api
import json
import logging

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from capa.xqueue_interface import XQUEUE_METRIC_NAME
from lms.djangoapps.certificates.models import (
    certificate_status_for_student,
    CertificateStatuses,
    GeneratedCertificate
)
from accredible_certificate.queue import CertificateGeneration
from opaque_keys.edx.locations import SlashSeparatedCourseKey
from django.db import transaction
from django.conf import settings
from opaque_keys.edx.keys import CourseKey

from courseware.courses import (
    get_course,
)

logger = logging.getLogger(__name__)


@transaction.non_atomic_requests
@csrf_exempt
def request_certificate(request):
    """Request the on-demand creation of a certificate for some user, course.
    A request doesn't imply a guarantee that such a creation will take place.
    We intentionally use the same machinery as is used for doing certification
    at the end of a course run, so that we can be sure users get graded and
    then if and only if they pass, do they get a certificate issued.
    """
    if request.method == "POST":
        if request.user.is_authenticated():
            # Enter your api key here
            xqci = CertificateGeneration(
                api_key=settings.APPSEMBLER_FEATURES['ACCREDIBLE_API_KEY']
            )
            username = request.user.username
            student = User.objects.get(username=username)
            course_key = CourseKey.from_string(
                request.POST.get('course_id')
            )
            course = get_course(course_key)

            status = certificate_status_for_student(
                student,
                course_key)['status']
            if status in [CertificateStatuses.unavailable, CertificateStatuses.notpassing, CertificateStatuses.error]:
                logger.info(
                    'Grading and certification requested for user {} in course {} via /request_certificate call'.format(username, course_key))
                status = xqci.add_cert(student, course_key, course=course)
            # Check if the user already have certificate for this course
            if status == "downloadable":
                # If the user has better grade than the one he has already got, generate new certificate
                if GeneratedCertificate.objects.filter(user=student, course_id=course_key):
                    certificate = GeneratedCertificate.objects.get(user=student, course_id=course_key)
                    status = xqci.regen_cert(student, course_key, request.POST.get('course_id'), course=course)
            return HttpResponse(
                json.dumps(
                    {'add_status': status}
                ), content_type='application/json')
        return HttpResponse(
            json.dumps(
                {'add_status': 'ERRORANONYMOUSUSER'}
            ), content_type='application/json')


@csrf_exempt
# this method not needed as no xqueue server here
def update_certificate(request):
    """
    Will update GeneratedCertificate for a new certificate or
    modify an existing certificate entry.
    See models.py for a state diagram of certificate states
    This view should only ever be accessed by the xqueue server
    """

    status = CertificateStatuses
    if request.method == "POST":

        xqueue_body = json.loads(request.POST.get('xqueue_body'))
        xqueue_header = json.loads(request.POST.get('xqueue_header'))

        try:
            course_key = CourseKey.from_string(
                xqueue_body['course_id']
            )

            cert = GeneratedCertificate.objects.get(
                user__username=xqueue_body['username'],
                course_id=course_key,
                key=xqueue_header['lms_key'])

        except GeneratedCertificate.DoesNotExist:
            logger.critical('Unable to lookup certificate\n'
                            'xqueue_body: {0}\n'
                            'xqueue_header: {1}'.format(
                                xqueue_body, xqueue_header))

            return HttpResponse(json.dumps({
                'return_code': 1,
                'content': 'unable to lookup key'}),
                content_type='application/json')

        if 'error' in xqueue_body:
            cert.status = status.error
            if 'error_reason' in xqueue_body:
                '''
                Hopefully we will record a meaningful error
                here if something bad happened during the
                certificate generation process
                example:
                (aamorm BerkeleyX/CS169.1x/2012_Fall)
                <class 'simples3.bucket.S3Error'>:
                HTTP error (reason=error(32, 'Broken pipe'), filename=None) :
                certificate_agent.py:175
                '''
                cert.error_reason = xqueue_body['error_reason']
        else:
            if cert.status in [status.generating, status.regenerating]:
                cert.download_uuid = xqueue_body['download_uuid']
                cert.verify_uuid = xqueue_body['verify_uuid']
                cert.download_url = xqueue_body['url']
                cert.status = status.downloadable
            elif cert.status in [status.deleting]:
                cert.status = status.deleted
            else:
                logger.critical('Invalid state for cert update: {0}'.format(
                    cert.status))
                return HttpResponse(json.dumps({
                    'return_code': 1,
                    'content': 'invalid cert status'}),
                    content_type='application/json')

        dog_stats_api.increment(XQUEUE_METRIC_NAME, tags=[
            u'action:update_certificate',
            u'course_id:{}'.format(cert.course_id)
        ])

        cert.save()
        return HttpResponse(json.dumps({'return_code': 0}),
                            content_type='application/json')
