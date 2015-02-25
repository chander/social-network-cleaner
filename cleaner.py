#!/usr/bin/env python
'''
Facebook Profile Cleaner
Copyright (c) 2015, Chander Ganesan <chander@otg-nc.com>

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of Chander Ganesan nor the
      names of its contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
'''

from optparse import OptionParser
from textwrap import dedent
import facebook
import getpass
import dateutil.tz
import dateutil.parser as dparser
import datetime
import requests
import sys
import pprint
import time
import traceback
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
import selenium.webdriver.support.expected_conditions as EC
import selenium.webdriver.support.ui as ui



class FacebookCleaner(object):
    def __init__(self, token, username, password):
        self.graph=facebook.GraphAPI(access_token=token)
        self.profile = self.graph.get_object('me')
        self.id=self.profile['id']
        localtz = dateutil.tz.tzlocal()
        self.tzoffset=localtz.utcoffset(datetime.datetime.now(localtz))
        
        self.driver = webdriver.Firefox()
        # or you can use Chrome(executable_path="/usr/bin/chromedriver")
        self.driver.set_page_load_timeout(5)
        self.driver.get("http://www.facebook.com")
        assert "Facebook" in self.driver.title
        elem = self.driver.find_element_by_id("email")
        elem.send_keys(username)
        elem = self.driver.find_element_by_id("pass")
        elem.send_keys(password)
        elem.send_keys(Keys.RETURN)
        self.printer=pprint.PrettyPrinter(indent=4)
              
    def __del__(self):
        self.driver.close()
          
          
    # return True if element is visible within 2 seconds, otherwise False
    def is_visible(self, elem, timeout=2):
        time.sleep(.5)
        return True
        try:
            ui.WebDriverWait(self.driver, timeout).until(EC.visibility_of(elem))
            return True
        except TimeoutException:
            return False
    
    def delete_status(self):
        xpaths=["//*[@aria-label='Story options']",
                "//span[contains(text(), 'Delete')]",
                "//button[contains(text(), 'Delete Post')]"]
        for xpath in xpaths:
            elem=self.driver.find_elements_by_xpath(xpath)
            if elem:
                elem=elem[0]
                if self.is_visible(elem):
                    hover = ActionChains(self.driver).move_to_element(elem).click()
                    hover.perform()
            else:
                print "Failed xpath lookup ({0})".format(xpath)
                return False
            time.sleep(1)
        return True
          
    def clean_posts(self, max_date, min_date=None):
        count=0
        deleted=0
        feed = self.graph.get_connections("me", "feed") # requires read_stream
        posts=[]
        # Get all the posts via the graph API
        while True:
            try:
                # Perform some action on each post in the collection we receive from
                # Facebook.
                for post in feed['data']:
                    # Attempt to make a request to the next page of data, if it exists.
                    
                    post["created_time"] = datetime.datetime.strptime(post["created_time"], 
                                                                      "%Y-%m-%dT%H:%M:%S+0000") + self.tzoffset
                    
                    if (post['created_time'] < max_date and 
                        (not min_date or post['created_time'] > min_date)):   
                        #print "Deleting item from feed {0}".format(post["created_time"])
                        if post['from']['id'] != self.id:
                            continue
                        if post['type'] not in ('status', 'link'):
                            continue
                        if 'are now friends.' in post.get('story', ''):
                            # This is a new friend added post.
                            continue
                        posts.append(post)
                        if (len(posts) % 10) == 0:
                            sys.stdout.write('.')
                            sys.stdout.flush()
                feed = requests.get(feed['paging']['next']).json()
            except KeyError:
                # When there are no more pages (['paging']['next']), break from the
                # loop and end the script.
                break
        print "\\Found {0} posts to be deleted".format(len(posts))
        nfcount=0
        nfcount_cycles=0
        for post in posts:
            if (deleted % 10) == 0:
                sys.stdout.write('*')
            sys.stdout.flush()
            timer=0
            try:
                url=post['actions'][0]['link']
            except KeyError:
                print "Failed to get link from post!"
                self.printer.pprint(post)
                continue
            try:
                while count < 5:
                    try:
                        self.driver.get(url)
                        break
                    except:
                        time.sleep(3)
                        count += 1
                else:
                    print "Failed to load {0}".format(url)
                    continue
                if "Page Not Found" in self.driver.title:
                    nfcount+=1
                    if nfcount < 10:
                        continue
                    else:
                        print "Too many failed requests, sleeping for 2 hours"
                        time.sleep(60*60*2)
                        nfcount_cycles += 1
                        nfcount=0
                        if nfcount_cycles > 10:
                            print "Exiting - too many failures"
                            sys.exit(0)
                        continue
                time.sleep(2)
                if self.delete_status():
                    deleted += 1
                else: # print the failed entry...
                    self.printer.pprint(post)
            except Exception,e:
                traceback.print_exc()
            time.sleep(5)       
    
if __name__ == '__main__':
    description='''
    A tool to (permanently?) remove items from a users facebook history.
    
    This script uses the Facebook Graph API to retrieve data for a user
    account, and then remove each item that falls within a provided time range.
    
    Originally, this was developed to allow a fast and easy way to purge 
    Facebook history from your account - it's especially useful when you have
    past data that is visible to people that you don't want/need it to be 
    visible to (such as all friends except those within a group.)  Though
    it could be argued that it's also easy to modify this script to simply 
    change the permissions on all past posts recursively.
    '''
    
    parser = OptionParser(description=dedent(description).strip())
    parser.add_option("-s", "--min-date", dest="min_date",
                      help="The earliest at which to start deleting items (start date)",
                      default=None)
    parser.add_option("-e", "--max_date",
                      dest="max_date", default=None,
                      help="The date of the most recent item to delete (inclusive) (end_date)")
    parser.add_option("-t", "--token",
                      dest="token", default=None,
                      help="Your facebook Graph API token (get it here: https://developers.facebook.com/tools/explorer/)")
    parser.add_option("-u", "--username",
                      dest="username", default=None,
                      help="Your facebook username")
    parser.add_option("-p", "--password",
                      dest="password", default=None,
                      help="Your facebook password")

    (options, args) = parser.parse_args()
    required_arguments=['token','max_date','username','password']
    if not options.password:
        options.password=getpass.getpass('Enter password for {0}: '.format(options.username))
    for arg in required_arguments:
        missing_args=[]
        if getattr(options, arg, None) is None:
            missing_args.append(arg)
    if missing_args:
        print "Missing argument(s) for {0}".format(', '.join(missing_args))
        parser.print_help()
        exit(0)
    fbc=FacebookCleaner(token=options.token,
                        username=options.username, password=options.password)
    for f in ['max_date', 'min_date']:
        if getattr(options, f):
            setattr(options, f, dparser.parse(getattr(options,f )))
    
    fbc.clean_posts(max_date=options.max_date,
                    min_date=options.min_date)
    
    
