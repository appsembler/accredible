from django.core.management.base import BaseCommand, CommandError
from lms.djangoapps.certificates.models import certificate_status_for_student
from accredible_certificate.queue import CertificateGeneration
from django.contrib.auth.models import User
from optparse import make_option
from django.conf import settings
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from opaque_keys.edx.locations import SlashSeparatedCourseKey
from xmodule.course_module import CourseDescriptor
from xmodule.modulestore.django import modulestore
from lms.djangoapps.certificates.models import CertificateStatuses
from lms.djangoapps.certificates.models import GeneratedCertificate
import datetime
from pytz import UTC
import requests
import json


class Command(BaseCommand):
    help = """
    Find all students that need certificates for courses that have finished and
    put their cert requests on the accredible API.

    Other commands can be private: true or not?
    Per use need to think about it as when I completed that Edx Linux course
    now the certificate generated at that time so might be in use
    """

    def add_arguments(self, parser):
        parser.add_argument(
            '-c', '--course',
            metavar='COURSE_ID',
            dest='course',
            default=False,
            help='Grade and generate certificates '
            'for a specific course'),
        parser.add_argument(
            '-a', '--api_key',
            metavar='API_KEY',
            dest='api_key',
            default=None,
            help='API key for accredible Certificate, if don\'t have one'
            'Visit https://accredible.com/issuer/sign_up and get one')

    def handle(self, *args, **options):

        # Will only generate a certificate if the current
        # status is in the unavailable state, can be set
        # to something else with the force flag
        if options['course']:
            # try to parse out the course from the serialized form
            try:
                course = CourseKey.from_string(options['course'])
            except InvalidKeyError:
                print("Course id {} could not be parsed as a CourseKey; falling back to SSCK.from_dep_str".format(
                    options['course']))
                course = SlashSeparatedCourseKey.from_deprecated_string(
                    options['course'])
            course_id = course
        else:
            raise CommandError("You must specify a course")

        if options['api_key']:
            api_key = options['api_key']
        else:
            raise CommandError(
                "You must give a api_key, if don't have one visit: https://accredible.com/issuer/sign_up")
        user_emails = []
        r = requests.get("https://api.accredible.com/v1/credentials?achievement_id=" + course_id.to_deprecated_string(
        ) + "&&full_view=true", headers={'Authorization': 'Token token=' + api_key, 'Content-Type': 'application/json'})
        for certificate in r.json()["credentials"]:
            if certificate["approve"] == True:
                user_emails.append(certificate["recipient"]["email"])
        for certificate in GeneratedCertificate.objects.filter(course_id=course_id, status="generating"):
            if certificate.user.email in user_emails:
                certificate.status = "downloadable"
                certificate.save()
                print certificate.name
