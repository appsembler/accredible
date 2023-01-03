from lms.djangoapps.certificates.models import GeneratedCertificate
from lms.djangoapps.certificates.models import certificate_status_for_student
from lms.djangoapps.certificates.models import CertificateStatuses as status
from lms.djangoapps.certificates.models import CertificateWhitelist

from courseware import courses
from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from django.test.client import RequestFactory
from capa.xqueue_interface import XQueueInterface
from capa.xqueue_interface import make_xheader, make_hashkey
from django.conf import settings
from requests.auth import HTTPBasicAuth
from student.models import UserProfile, CourseEnrollment
from lms.djangoapps.verify_student.models import (
    SoftwareSecurePhotoVerification
)
import json
import random
import logging
import lxml.html
from lxml.etree import XMLSyntaxError, ParserError
import requests
from xmodule.modulestore.django import modulestore
from util.db import outer_atomic
from django.db import transaction

logger = logging.getLogger(__name__)


class CertificateGeneration(object):
    """
    AccredibleCertificate generates an
    accredible certificates for students

    See certificates/models.py for valid state transitions,
    summary of methods:

       add_cert:   Add a new certificate.  Puts a single
                   request on the queue for the student/course.
                   Once the certificate is generated a post
                   will be made to the update_certificate
                   view which will save the certificate
                   download URL.

       regen_cert: Regenerate an existing certificate.
                   For a user that already has a certificate
                   this will delete the existing one and
                   generate a new cert.


       del_cert:   Delete an existing certificate
                   For a user that already has a certificate
                   this will delete his cert.

    """

    def __init__(self, request=None, api_key=None):

        # Get basic auth (username/password) for
        # xqueue connection if it's in the settings
        if request is None:
            factory = RequestFactory()
            self.request = factory.get('/')
        else:
            self.request = request

        self.whitelist = CertificateWhitelist.objects.all()
        self.restricted = UserProfile.objects.filter(allow_certificate=False)
        self.api_key = api_key

    @transaction.non_atomic_requests
    def add_cert(
            self,
            student,
            course_id,
            defined_status="downloadable",
            course=None,
            forced_grade=None,
            template_file=None,
            title='None'):
        """
        Request a new certificate for a student.

        Arguments:
          student   - User.object
          course_id - courseenrollment.course_id (CourseKey)
          forced_grade - a string indicating a grade parameter to pass with
                         the certificate request. If this is given, grading
                         will be skipped.

        Will change the certificate status to 'generating' or 'downloadable'.

        Certificate must be in the 'unavailable', 'error',
        'deleted' or 'generating' state.

        If a student has a passing grade or is in the whitelist
        table for the course a request will be made for a new cert.

        If a student has allow_certificate set to False in the
        userprofile table the status will change to 'restricted'

        If a student does not have a passing grade the status
        will change to status.notpassing

        Returns the student's status
        """

        VALID_STATUSES = [
            status.generating,
            status.unavailable,
            status.deleted,
            status.error,
            status.notpassing
        ]

        cert_status = certificate_status_for_student(
            student,
            course_id)['status']

        new_status = cert_status

        if cert_status in VALID_STATUSES:
            '''
            rade the student
            re-use the course passed in optionally
            so we don't have to re-fetch everything
            for every student
            '''
            if course is None:
                course = courses.get_course_by_id(course_id)

            profile = UserProfile.objects.get(user=student)
            profile_name = profile.name
            # Needed
            self.request.user = student
            self.request.session = {}
            course_name = course.display_name or course_id.to_deprecated_string()
            description = ''
            for section_key in ['short_description', 'description', 'overview']:
                loc = loc = course.location.replace(
                    category='about',
                    name=section_key
                )
                try:
                    if modulestore().get_item(loc).data:
                        description = modulestore().get_item(loc).data
                        break
                except:
                    print("this course don't have " + str(section_key))

            if not description:
                description = "course_description"
            is_whitelisted = self.whitelist.filter(
                user=student,
                course_id=course_id,
                whitelist=True).exists()

            grade = CourseGradeFactory().read(student, course)
            enrollment_mode, __ = CourseEnrollment.enrollment_mode_for_user(
                student, course_id
            )
            mode_is_verified = (
                enrollment_mode == GeneratedCertificate.MODES.verified
            )
            cert_mode = GeneratedCertificate.MODES.honor
            if forced_grade:
                grade = forced_grade

            cert, __ = GeneratedCertificate.objects.get_or_create(
                user=student,
                course_id=course_id
            )

            cert.mode = cert_mode
            cert.user = student
            cert.grade = grade.percent
            cert.course_id = course_id
            cert.name = profile_name

            # Strip HTML from grade range label
            # convert percent to points as an integer
            grade_contents = int(grade.percent * 100)

            if is_whitelisted or grade_contents is not None:

                # check to see whether the student is on the
                # the embargoed country restricted list
                # otherwise, put a new certificate request
                # on the queue
                print grade_contents
                if self.restricted.filter(user=student).exists():
                    new_status = status.restricted
                    cert.status = new_status
                    cert.save()
                else:
                    contents = {
                        'action': 'create',
                        'username': student.username,
                        'course_id': course_id.to_deprecated_string(),
                        'course_name': course_name,
                        'name': profile_name,
                        'grade': grade_contents
                    }

                    if defined_status == "generating":
                        approve = False
                    else:
                        approve = True

                    # check to see if this is a BETA course
                    course_name = course_name.strip()
                    if course_name.startswith("BETA") or course_name.startswith("Beta") or course_name.startswith("beta"):
                        course_name = course_name[4:].strip()
                    grade_into_string = grade.letter_grade
                    payload = {
                        "credential":
                        {
                            "name": course_name,
                            "group_name": course_name,
                            "description": description,
                            "achievement_id": contents['course_id'],
                            "course_link": "/courses/" + contents['course_id'] + "/about",
                            "approve": approve,
                            "template_name": contents['course_id'],
                            "grade": contents['grade'],
                            "recipient": {
                                "name": contents['name'],
                                "email": student.email
                            }
                        }
                    }

                    payload = json.dumps(payload)

                    r = requests.post('https://api.accredible.com/v1/credentials', payload, headers={
                                      'Authorization': 'Token token=' + self.api_key, 'Content-Type': 'application/json'})
                    if r.status_code == 200:
                        json_response = r.json()
                        cert.status = defined_status
                        cert.key = json_response["credential"]["id"]
                        if 'private' in json_response:
                            cert.download_url = "https://www.credential.net/" + \
                                str(json_response["credential"]["id"]) + \
                                "?key" + str(json_response["private_key"])
                        else:
                            cert.download_url = "https://www.credential.net/" + \
                                str(cert.key)
                        cert.save()
                    else:
                        new_status = "errors"
            else:
                cert_status = status.notpassing
                cert.status = cert_status
                cert.save()

        return new_status

    @transaction.non_atomic_requests
    def regen_cert(self, student, course_id, course_key, course=None):
        """
        Regenrate a certificate for a user if the grade is better than
        the current one
        """
        # 1. Check if the user already has a certificate for the course
        try:
            generated_certificate = GeneratedCertificate.objects.get(
                user=student,
                course_id=course_id
            )
        except GeneratedCertificate.DoesNotExist:
            generated_certificate = None
            return generated_certificate
        # 2. Find the issued certificate
        try:
            headers = {
                'Authorization': 'Token token=' + self.api_key,
                'Content-Type': 'application/json'
            }
            values = {
                "recipient": {
                "email": student.email
                }
            }
            values = json.dumps(values)
            cert_response = requests.post(
                'https://api.accredible.com/v1/credentials/search',
                headers=headers,
                data=values
                )
            for credential in cert_response.json()["credentials"]:
                if course_key in credential["course_link"]:
                    existing_certificate = credential
                    break
        except Exception as e:
            return None
        # 2. Find the current grade and get the new grade
        new_grade = CourseGradeFactory().read(student, course)
        if existing_certificate:
            current_grade = float(existing_certificate["grade"])
        # 3. if new grade > current grade, regenrate the certificate 
        if new_grade.percent * 100 > current_grade:
            # Regenerate the certificate
            values = {
                    "credential": {
                        "approve": True,
                        "grade": new_grade.percent * 100,
                    }
                }
            headers = {
                'Authorization': 'Token token=' + self.api_key,
                'Content-Type': 'application/json'
            }
            payload = json.dumps(values)
            update_response = requests.put(
                'https://api.accredible.com/v1/credentials/' + str(existing_certificate["id"]),
                headers=headers,
                data=payload
            )
            if update_response.status_code == 200:
                return True
            else:
                return False
