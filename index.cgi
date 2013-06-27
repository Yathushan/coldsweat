#!/usr/bin/env python
"""
Boostrap file for CGI environments
"""

# -----------------------------------------------
# Set media base URL, no trailing slash please
# -----------------------------------------------

# If you have istalled Coldsweat under a dir, e.g. coldsweat
STATIC_URL = '/coldsweat/static'

# If you have installed Coldsweat on site root
#STATIC_URL = '/static'

# If you want to serve static stuff from a different server
#STATIC_URL = 'http://media.example.com/static'

from wsgiref.handlers import CGIHandler
from coldsweat.app import ColdsweatApp, ExceptionMiddleware

app = ExceptionMiddleware(ColdsweatApp(STATIC_URL))     

if __name__ == '__main__':
    CGIHandler().run(app)


