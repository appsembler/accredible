from setuptools import setup

setup(
    name='accredible_certificate',
    version='0.0.1',
    license='MIT',
    description='Reporting and data retrieval for Open edX',
    entry_points={
    'lms.djangoapp': [
        'accredible_certificate = accredible_certificate.apps:AccredibleConfig',
    ],
},
)