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
from threading import Timer
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
        self.username=username
        self.password=password
        
        self.printer=pprint.PrettyPrinter(indent=4)
        self.nfcount=0
        self.nfcount_cycles=0
              
              
    @property
    def driver(self):
        '''
        Load the browser and driver when it's first requested/used, rather than
        when the object is initialized.
        '''
        if not hasattr(self, '_driver'):
            self._driver = webdriver.Firefox()
            # or you can use Chrome(executable_path="/usr/bin/chromedriver")
            self._driver.set_page_load_timeout(5)
            self._driver.get("http://www.facebook.com")
            assert "Facebook" in self._driver.title
            elem = self._driver.find_element_by_id("email")
            elem.send_keys(self.username)
            elem = self._driver.find_element_by_id("pass")
            elem.send_keys(self.password)
            elem.send_keys(Keys.RETURN)
            time.sleep(5)
        return self._driver
    
    
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
        '''
        A simple function to use the Firefox UI to remove a status entry,
        note that this only works if the status is actually a post (as opposed to,
        for example, a photo upload status.)
        '''
        xpaths=[("//*[@aria-label='Story options']", True,),
                ("//*[contains(text(), 'More options')]",False,),
                ("//span[contains(text(), 'Delete')]",True,),
                ("//button[contains(text(), 'Delete Post')]", True,),]
        return self.perform_xpaths(xpaths)
            
    def perform_xpaths(self, xpaths):
        '''
        Perform a set of xpath queries
        '''
        for xpath, required in xpaths:
            elem=self.driver.find_elements_by_xpath(xpath)
            if elem:
                elem=elem[0]
                if self.is_visible(elem):
                    hover = ActionChains(self.driver).move_to_element(elem).click()
                    timer=Timer(5, lambda: self.driver.quit())
                    timer.start()
                    hover.perform()
                    timer.cancel()
            elif required:
                print "Failed xpath lookup ({0})".format(xpath)
                return False
            time.sleep(1)
        return True

    def delete_photo(self):
        '''
        A simple function to use the Firefox UI to remove a status entry,
        note that this only works if the status is actually a post (as opposed to,
        for example, a photo upload status.)
        '''
        xpaths=[("//*[contains(text(), 'Delete This Photo')]",False,),
                ("//button[contains(text(), 'Confirm')]", True,),]
        return self.perform_xpaths(xpaths)
    
    def delete_album(self):
        '''
        A simple function to use the Firefox UI to remove a status entry,
        note that this only works if the status is actually a post (as opposed to,
        for example, a photo upload status.)
        '''
        xpaths=[("//a[contains(@class,'fbPhotoAlbumOptionsGear')]", True),
                ("//*[contains(text(), 'Delete Album')]",False,),
                ("//button[contains(text(), 'Delete Album')]", True,),]
        return self.perform_xpaths(xpaths)


    def photo_generator(self, max_date, min_date):
        '''
        A generator that iterates over all the photos and albums to return them
        all.  The assumption here is that you already deleted all the albums, so
        the album stuff doesn't really do anything (since the albums are gone)
        '''
        albums = self.graph.get_connections("me", "albums")
        album_count=0
        album_list=[]
        while True:
            for album in albums['data']:
                if album['from']['id'] != self.id:
                    continue
                album_list.append(album)
            if albums['paging'].has_key('next'):
                albums=requests.get(albums['paging']['next']).json()
            else:
                break
            
        for album in album_list:
            album["updated_time"] = datetime.datetime.strptime(album["updated_time"], 
                                                               "%Y-%m-%dT%H:%M:%S+0000") + self.tzoffset
            if (album['updated_time'] < max_date and 
                (not min_date or album['updated_time'] > min_date)):
                self.load_page(album['link'])
                if self.delete_album(): # skip the photos if we deleted the album
                    continue
            pictures=self.graph.get_connections(album['id'],"photos")
            while True:
                try:
                    for picture in pictures['data']:
                        yield picture
                    pictures=requests.get(pictures['paging']['next']).json()
                except KeyError:
                    break
           
        print "There were {0} albums with photos to be removed".format(album_count)
        pictures = self.graph.get_connections("me", "photos")    
        while True:
            for picture in pictures['data']:
                yield picture
            if pictures['paging'].has_key('next'):
                pictures=requests.get(pictures['paging']['next']).json()
            else:
                break       
          
    def clean_photos(self, max_date, min_date=None):
        count=0
        deleted=0
        photo_feed = self.graph.get_connections("me", "photos") # requires read_stream
        pictures=[]
        picture_types=set()
        for picture in self.photo_generator(max_date, min_date):
            picture["created_time"] = datetime.datetime.strptime(picture["created_time"], 
                                                                 "%Y-%m-%dT%H:%M:%S+0000") + self.tzoffset
            if (picture['created_time'] < max_date and 
                (not min_date or picture['created_time'] > min_date)):   
                if picture['from']['id'] != self.id:
                    continue
                pictures.append(picture)
                if (len(pictures) % 10) == 0:
                    sys.stdout.write('.')
                    sys.stdout.flush()
        print "There are {0} pictures to be deleted".format(len(pictures))
        for picture in pictures:
            if (deleted % 10) == 0:
                sys.stdout.write('*')
            sys.stdout.flush()
            try:
                url=picture['link']
            except KeyError:
                print "Failed to get link from post!"
                self.printer.pprint(picture)
                continue
            self.load_page(url)
            if self.delete_photo():
                deleted +=1 
            else: 
                print '{0} failed to delete'.format(url)
            
    def clean_posts(self, max_date, min_date=None):
        count=0
        deleted=0
        feed = self.graph.get_connections("me", "feed") # requires read_stream
        posts=[]
        post_types=set()
        # Get all the posts via the graph API
        while True:
            try:
                # Perform some action on each post in the collection we receive from
                # Facebook.
                for post in feed['data']:
                    # Attempt to make a request to the next page of data, if it exists.
                    
                    post["created_time"] = datetime.datetime.strptime(post["created_time"], 
                                                                      "%Y-%m-%dT%H:%M:%S+0000") + self.tzoffset
                    
                    post_types.add(post['type'])
                    if (post['created_time'] < max_date and 
                        (not min_date or post['created_time'] > min_date)):   
                        #print "Deleting item from feed {0}".format(post["created_time"])
                        if post['from']['id'] != self.id:
                            continue
                        if post['type'] not in ('status', 'link','photo', 'video',):
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
        print "Found items of type {0}".format(', '.join(post_types))
        print "\\Found {0} posts to be deleted".format(len(posts))
       
        for post in posts:
            if (deleted % 10) == 0:
                sys.stdout.write('*')
            sys.stdout.flush()
            try:
                url=post['actions'][0]['link']
            except KeyError:
                print "Failed to get link from post!"
                self.printer.pprint(post)
                continue
            try:
                self.load_page(url)
                if post['type'] in ('link', 'status', 'photo', 'video'):
                    if self.delete_status():
                        deleted += 1
                else: # print the failed entry...
                    self.printer.pprint(post)
            except Exception,e:
                traceback.print_exc()
            time.sleep(5)       
    
    def load_page(self, url):
        count=0
        while count < 5:
            try:
                print "Loading URL {0}".format(url)
                self.driver.get(url)
                time.sleep(5)
                break
            except:
                time.sleep(3)
                count += 1
            else:
                print "Failed to load {0}".format(url)
                continue
            if "Page Not Found" in self.driver.title:
                self.nfcount+=1
                if self.nfcount < 10:
                    time.sleep(2)
                    continue
                else:
                    print "Too many failed requests, sleeping for 2 hours"
                    time.sleep(60*60*2)
                    self.nfcount_cycles += 1
                    self.nfcount=0
                    if self.nfcount_cycles > 10:
                        print "Exiting - too many failures"
                        sys.exit(0)
                    continue
            
    
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
    parser.add_option("--photos",
                      action='store_true',
                      dest="clean_photos", default=False,
                      help="Remove Photos")
    parser.add_option("--posts",
                      action='store_true',
                      dest="clean_posts", default=False,
                      help="Remove Posts")

    (options, args) = parser.parse_args()
    required_arguments=['token','max_date','username',]
    
    for arg in required_arguments:
        missing_args=[]
        if getattr(options, arg, None) is None:
            missing_args.append(arg)
    while not options.password:
        options.password=getpass.getpass('Enter password for {0}: '.format(options.username))
    if missing_args:
        print "Missing argument(s) for {0}".format(', '.join(missing_args))
        parser.print_help()
        exit(0)
    
    for f in ['max_date', 'min_date']:
        if getattr(options, f):
            setattr(options, f, dparser.parse(getattr(options,f )))
    if max(options.clean_posts, options.clean_photos):       
        fbc=FacebookCleaner(token=options.token,
                            username=options.username, password=options.password)
    if options.clean_posts:
        
        fbc.clean_posts(max_date=options.max_date,
                        min_date=options.min_date)
    if options.clean_photos:
        fbc.clean_photos(max_date=options.max_date,
                         min_date=options.min_date)
    
