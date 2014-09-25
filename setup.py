#!/usr/bin/env python

from setuptools import setup

version = "0.1"

REQUIREMENTS = [i.strip() for i in open("requirements.txt").readlines()]

setup(
  name="blinktrade_edentiti",
  version=version,
  author="Rodrigo Souza",
  packages = [
    "blinktrade_edentiti",
    ],
  entry_points = { 'console_scripts':
                     [
                       'blinktrade_edentiti = blinktrade_edentiti.edentiti:main'
                     ]
  },
  install_requires=REQUIREMENTS,
  author_email='r@blinktrade.com',
  url='https://github.com/blinktrade/blinktrade_edentiti',
  license='http://www.gnu.org/copyleft/gpl.html',
  description='Edentiti identity provider integration'
)
