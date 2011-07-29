#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright 2008 Ryan Cox ( ryan.a.cox@gmail.com ) All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

'''A wrapper library for Tumblr's public web API: http://www.tumblr.com/api'''

__author__ = 'ryan.a.cox@gmail.com'
__version__ = '0.1'

from httplib import HTTPConnection
from urllib2 import Request, urlopen, URLError, HTTPError
from urllib import urlencode, quote
from poster.encode import multipart_encode
from poster.streaminghttp import register_openers

import base64
import json
import logging
import re

GENERATOR = 'python-tumblr'
PAGESIZE = 50


class TumblrError(Exception):
    ''' General Tumblr error '''
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg

class TumblrAuthError(TumblrError):
    ''' Wraps a 403 result '''
    pass

class TumblrRequestError(TumblrError):
    ''' Wraps a 400 result '''
    pass

class TumblrIterator:
    def __init__(self, name, start, max, type):
        self.name = name
        self.start = start
        self.max = max
        self.type = type
        self.results = None
        self.index = 0

    def __iter__(self):
        return self

    def next(self):
        if not self.results or (self.index == len(self.results['posts'])):
            self.start += self.index
            self.index = 0
            url = "http://%s.tumblr.com/api/read/json?start=%s&num=%s" % (self.name,self.start, PAGESIZE)
            if self.type:
                url += "&type=" + self.type
            response = urlopen(url)
            page = response.read()
            m = re.match("^.*?({.*}).*$", page,re.DOTALL | re.MULTILINE | re.UNICODE)
            self.results = json.loads(m.group(1))

        if (self.index >= self.max) or len(self.results['posts']) == 0:
            raise StopIteration

        self.index += 1
        return self.results['posts'][self.index-1]

class Api:
    def __init__(self, name, email=None, password=None, private=None, date=None, tags=None, format=None):
        self.name = name
        self.is_authenticated = False
        self.email = email
        self.password = password
        self.private = private
        self.date = date
        self.tags = tags
        self.format = format

    def auth_check(self):
        if self.is_authenticated:
            return
        url = 'http://www.tumblr.com/api/write'
        values = {
                'action': 'authenticate',
                'generator' : GENERATOR,
                'email': self.email,
                'password' : self.password,
                'private' : self.private,
                'group': self.name,
                'date': self.date,
                'tags': self.tags,
                'format': self.format
                }

        data = urlencode(values)
        req = Request(url, data)
        try:
            response = urlopen(req)
            page = response.read()
            self.url = page
            self.is_authenticated = True
            return
        except HTTPError, e:
            if 403 == e.code:
                return e.code
                
            if 400 == e.code:
                raise TumblrRequestError(str(e))
        except Exception, e:
            raise TumblrError(str(e))

    def dashboard(self):
        self.domain = 'http://www.tumblr.com'
        self.url = self.domain + '/login'
        self.params = urlencode({'email':self.email, 'password': self.password})
        self.headers = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
        self.response = self._getcookie(self.domain, self.url, self.headers, self.params)

        self.cookie = self._cookie(self.response)

        self.response = self._getcookie(self.domain, self.url, self.headers, self.params, self.cookie)
        self.url_iphone = 'http://www.tumblr.com/iphone'
        self.data = self._getcookie(self.domain, self.url_iphone, self.headers, self.params, self.cookie)
        return self.data.read()

    def _cookie(self, response):
        self.cookie = response.getheader('set-cookie')

        self.pfu = self.cookie[self.cookie.find('pfu'):self.cookie.find(' ')]
        self.pfp = self.cookie[self.cookie.find('pfp'):]
        self.pfp = self.pfp[:self.pfp.find(' ')]
        self.pfe = self.cookie[self.cookie.find('pfe'):]
        self.pfe = self.pfe[:self.pfe.find(' ')]
        self.cookie = self.pfu + self.pfp + self.pfe

        return self.cookie


    def _getcookie(self, domain, url, headers, params = None, cookie = None):
        self.session = HTTPConnection(domain, '80')
        if cookie:
            headers['Cookie'] = cookie
        self.session.request('POST',url, params, headers)

        self.response = self.session.getresponse()
        return self.response

    def write_regular(self, title=None, body=None, **args):
        if title:
            args['title'] = title
        if body:
            args['body'] = body
        args = self._fixnames(args)
        if not 'title' in args and not 'body' in args:
            raise TumblrError("Must supply either body or title argument")

        self.auth_check()
        args['type'] = 'regular'
        return self._write(args)

    def write_photo(self, source=None, data=None, caption=None, click=None, **args):
        if source:
            args['source'] = source
        else:
            args['data'] = open(data, "rb")

        args['caption'] = caption
        args['click-through-url'] = click

        args = self._fixnames(args)
        if 'source' in args and 'data' in args:
            raise TumblrError("Must  NOT supply both source and data arguments")

        if not 'source' in args and not 'data' in args:
            raise TumblrError("Must supply source or data argument")

        self.auth_check()
        args['type'] = 'photo'
        return self._write(args)

    def write_quote(self, quote=None, source=None, **args):
        if quote:
            args['quote'] = quote
            args['source'] = source
        args = self._fixnames(args)
        if not 'quote' in args:
            raise TumblrError("Must supply quote arguments")

        self.auth_check()
        args['type'] = 'quote'
        return self._write(args)

    def write_link(self, name=None, url=None, description=None, **args):
        if url:
            args['name'] = name
            args['url'] = url
            args['description'] = description
        args = self._fixnames(args)
        if not 'url' in args:
            raise TumblrError("Must supply url argument")

        self.auth_check()
        args['type'] = 'link'
        return self._write(args)

    def write_conversation(self, title=None, conversation=None, **args):
        if conversation:
            args['title'] = title
            args['conversation'] = conversation
        args = self._fixnames(args)
        if not 'conversation' in args:
            raise TumblrError("Must supply conversation argument")

        self.auth_check()
        args['type'] = 'conversation'
        return self._write(args)

    def write_audio(self, data=None, source=None, caption=None, **args):
		if source:
            args['externally-hosted-url'] = source
            args['data'] = data
        else:
            args['data'] = open(data)

        if not 'data' in args:
            raise TumblrError("Must supply data argument")

        args['caption'] = caption
        args = self._fixnames(args)

        self.auth_check()
        args['type'] = 'audio'
        return self._write(args)

    def write_video(self, embed=None, data=None, title=None, caption=None, **args):
        if data:
            args['data'] = open(data)
            args['title'] = title
            args['caption'] = caption
        elif embed:
            args['embed'] = embed
            args['title']= title
            args['caption'] = caption
        elif 'embed' in args and 'data' in args:
            raise TumblrError("Must  NOT supply both embed and data arguments")
        else:    
            raise TumblrError("Must supply embed or data argument")

        args = self._fixnames(args)

        self.auth_check()
        args['type'] = 'video'
        return self._write(args)

    def _fixnames(self, args):
        for key in args:
            if '_' in key:
                value = args[key]
                del args[key]
                args[key.replace('_', '-')] = value
        return args

    def _write(self, params, headers=None):
        self.auth_check()
        url = 'http://www.tumblr.com/api/write'
        register_openers()
        params['email'] = self.email
        params['password'] = self.password
        params['private'] = self.private
        params['generator'] = GENERATOR
        params['group'] = self.name
        params['date'] = self.date
        params['tags'] = self.tags
        params['format'] = self.format

        if not params['date']:
            params['date'] = 'now'

        params = dict((k,v) for k,v in params.iteritems() if v)

        logging.debug(params)

        if not 'data' in params:
            data = urlencode(params)
        else:
            data, headers = multipart_encode(params)

        if headers:
            req = Request(url, data, headers)
        else:
            req = Request(url, data)
        
        newid = None
        try:
            f = urlopen(req)
	    readdata= f.read()
            logging.debug(readdata)
	    return readdata #This works for py 2.6 and higher
        except HTTPError, e:
	    #raise TumblrError(e.read())
	    #this branch taken for py 2.5, urllib's HTTP error facilities work differently
            if e.msg == "Created":
              return e.read()
            else:
              # raise TumblrError(e.read()) - Preventing script from actually raising errors allows the error codes to get passed back from the function
              return e.read()

    def read(self, id=None, start=0,max=2**31-1,type=None):
        if id:
            url = "http://%s.tumblr.com/api/read/json?id=%s" % (self.name,id)
            response = urlopen(url)
            page = response.read()
            m = re.match("^.*?({.*}).*$", page,re.DOTALL | re.MULTILINE | re.UNICODE)
            results = json.loads(m.group(1))
            if len(results['posts']) == 0:
                return None

            return results['posts'][0]
        else:
            return TumblrIterator(self.name,start,max,type)

if __name__ == "__main__":
    pass
