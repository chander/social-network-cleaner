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
DISCLAIMED. IN NO EVENT SHALL CHANDER GANESAN BE LIABLE FOR ANY
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
import dateutil.parser as dparser
import tzlocal
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
    def __init__(self, username, password):
        self.login=False
        self.username=username
        self.password=password
        self.printer=pprint.PrettyPrinter(indent=4)
        self.nfcount=0
        self.nfcount_cycles=0
        self.deleted=0
        self.delay=1


    @property
    def graph(self):
        '''
        Intialize the graph stuff on the first attempt, or if the token is more
        than 3300 seconds old (since I think they expire after ~ 1 hour, and we need
        likely no more than 5 minutes to query the API in a single request set.)
        '''
        if (not getattr(self, '_graph', None)) or self.token_expires < time.time():
            token=self.get_api_token()
            self.token_expires=time.time()+3300
            self._graph=facebook.GraphAPI(access_token=token)
            try:
                self.profile = self._graph.get_object('me')
                self.id=self.profile['id']
            except facebook.GraphAPIError, e:
                print >>sys.stderr, "Failure to access Graph API with token - error: {0}".format(e)
                print >>sys.stderr, "Perhaps you need to get a new one here: https://developers.facebook.com/tools/explorer/"
                sys.exit(1)
        return self._graph

    @property
    def driver(self):
        '''
        Load the browser and driver when it's first requested/used, rather than
        when the object is initialized.
        '''
        attempts=0
        while not self.login:
            try:
                if not getattr(self, '_driver', None):
                    self._driver = webdriver.Firefox()
                # or you can use Chrome(executable_path="/usr/bin/chromedriver")
                self._driver.set_page_load_timeout(10)
                self._driver.get("http://www.facebook.com")
                assert "Facebook" in self._driver.title
                elem = self._driver.find_element_by_id("email")
                elem.send_keys(self.username)
                elem = self._driver.find_element_by_id("pass")
                elem.send_keys(self.password)
                elem.send_keys(Keys.RETURN)
                self.login=True
                time.sleep(5)
            except:
                attempts += 1
                if attempts > 5:
                    sys.stderr.write('Login failed - perhaps facebook is slow?!\n')
                    sys.exit(2)

        return self._driver

    def graphLookup(self, *args, **kwargs):
        try:
            return self.graph.get_connections(*args, **kwargs)
        except facebook.GraphAPIError, e:
            print >> sys.stderr, "Failure to access Graph API: {0}".format(e)
            print >> sys.stderr, "This might be because your deletes took too long - get a new one and restart this tool?"
            print >> sys.stderr, "Perhaps you need to get a new one here: https://developers.facebook.com/tools/explorer/"
            sys.exit(1)

    def __del__(self):
        if hasattr(self, '_driver'):
            self._driver.close()

    # return True if element is visible within 2 seconds, otherwise False
    def is_visible(self, elem, timeout=2):
        time.sleep(.5)
        return True
        try:
            ui.WebDriverWait(self.driver, timeout).until(EC.visibility_of(elem))
            return True
        except TimeoutException:
            return False

    def perform_xpaths(self, url, xpaths):
        '''
        Perform a set of xpath queries
        '''
        if url:
            self.load_page(url)
        for xpath, required in xpaths:
#             print "Trying {0} on {1}".format(url, xpath)
            elem=self.driver.find_elements_by_xpath(xpath)
            if elem:
                elem=elem[0]
                if self.is_visible(elem):
                    hover = ActionChains(self.driver).move_to_element(elem).click()
#                     timer=Timer(5, lambda: self.driver.quit())
#                     timer.start()
                    hover.perform()
#                     timer.cancel()
            elif required:
                print "Failed xpath lookup ({0}) for URL {1} (aborting)".format(xpath, url)
                return False
            time.sleep(self.delay)
        self.deleted += 1
        if (self.deleted % 10) == 0:
            sys.stdout.write('*')
            sys.stdout.flush()
        return True

    def delete_status(self, url):
        '''
        A simple function to use the Firefox UI to remove a status entry.
        '''
        xpaths=[("//*[@aria-label='Story options']", True,),
                ("//*[contains(text(), 'More options')]",False,),
                ("//span[contains(text(), 'Delete')]",True,),
                ("//button[contains(text(), 'Delete Post')]", True,),]
        return self.perform_xpaths(url, xpaths)

    def delete_photo(self, url):
        '''
        A simple function to use the Firefox UI to remove a photo.
        '''
        xpaths=[("//*[contains(text(), 'Delete This Photo')]",False,),
                ("//button[contains(text(), 'Confirm')]", True,),]
        return self.perform_xpaths(url, xpaths)

    def delete_album(self, url):
        '''
        A simple function to use the Firefox UI to remove an album.
        '''
        xpaths=[("//a[contains(@class,'fbPhotoAlbumOptionsGear')]", True),
                ("//*[contains(text(), 'Delete Album')]",False,),
                ("//button[contains(text(), 'Delete Album')]", True,),]
        return self.perform_xpaths(url, xpaths)

    def photo_generator(self, max_date, min_date):
        '''
        A generator that iterates over all the photos and albums to return them
        all.  The albums (if any) are deleted as it goes along, unless it finds
        that the update timestamp makes it ineligible for deletion - in which
        case it just recurses through the photos therein
        '''
        albums = self.graphLookup("me", "albums")
        album_list=[]
        # Get a list of albums.  We make the list because sometimes we'll
        # delete entire albums as we go along, which might mess up the API results.
        while True:
            for album in albums['data']:
                if album['from']['id'] != self.id:
                    continue
                album_list.append(album)
            if not (albums.has_key('paging') and albums['paging'].has_key('next')):
                break
            albums=requests.get(albums['paging']['next']).json()

        delete_albums=0
        for album in album_list:
            album["updated_time"] = dparser.parse(album["updated_time"])
            if (album['updated_time'] < max_date and
                (not min_date or album['updated_time'] > min_date)):

                if self.delete_album(album['link']): # skip the photos if we deleted the album
                    continue
                delete_albums+=1
            pictures=self.graphLookup(album['id'],"photos")
            while True:
                for picture in pictures['data']:
                    yield picture
                if not (pictures.has_key('paging') and pictures['paging'].has_key('next')):
                    break
                pictures=requests.get(pictures['paging']['next']).json()

        print "There were {0} album(s) with photos to be removed".format(delete_albums)
        pictures = self.graphLookup("me", "photos")
        while True:
            for picture in pictures['data']:
                yield picture
            if not (pictures.has_key('paging') and pictures['paging'].has_key('next')):
                break
            pictures=requests.get(pictures['paging']['next']).json()

    def clean_photos(self, max_date, min_date=None):
        '''
        Use the photo generator to get a list of all photos in all albums,
        and then delete them. In this case the albums actually will get
        deleted by the generator (assuming they have been last updated
        before the delete range.)  This is much better, since deleting an
        album deletes all the photos inside it (as opposed to having to
        delete each one.)
        '''
        photo_feed = self.graphLookup("me", "photos") # requires read_stream
        pictures=[]
        picture_types=set()
        for picture in self.photo_generator(max_date, min_date):
            picture["created_time"] = dparser.parse(picture["created_time"])
            if (picture['created_time'] < max_date and
                (not min_date or picture['created_time'] > min_date)):
                if picture['from']['id'] != self.id:
                    continue
                pictures.append(picture)
                if (len(pictures) % 10) == 0:
                    sys.stdout.write('.')
                    sys.stdout.flush()
        print "\nThere are {0} pictures to be deleted".format(len(pictures))
        for picture in pictures:
            if 'link' in picture:
                url=picture['link']
            else:
                continue
            self.delete_photo(url)

    def get_api_token(self):
        main_window_handle=self.driver.window_handles[0]
        delay=self.delay
        self.delay=5
        url='https://developers.facebook.com/tools/explorer/'
        xpaths=[("//*[@id='get_access_token']", True,),
                ("//a[contains(text(), 'Clear')]", True,),
                ("//input[@name='user_status']",False,),
                ("//input[@name='user_relationship']",False,),
                ("//input[@name='user_photos']",False,),
                ("//input[@name='user_videos']",False,),
                ("//input[@name='user_interests']",False,),
                ("//input[@name='user_friends']",False,),
                ("//input[@name='user_events']",False,),
                ("//*[@data-group='extended']",True,),
                ("//input[@name='read_stream']",False,),
                ("//button[contains(text(), 'Get Access Token')]", True,)
                ]
        self.perform_xpaths(url, xpaths)
        time.sleep(3)
        if len(self.driver.window_handles) > 1:
            for handle in self.driver.window_handles:
                try:
                    self.driver.switch_to_window(handle)
                except: continue
#                 print "move to handle ... {0}".format(self.driver.title)
                if 'Log in' in self.driver.title:
#                     print "Found page with title {0}".format(self.driver.title)
                    xpaths=[("//button[contains(text(), 'Okay')]", True,)]
                    self.perform_xpaths(None, xpaths)
            self.driver.switch_to_window(main_window_handle)
        elem=self.driver.find_element_by_id("access_token")
        token=elem.get_attribute("value");
#         print token
        self.delay=delay
        return token

    def clean_posts(self, max_date, min_date=None):
        '''
        Iterate over the posts for an account and delete them if possible,
        note that many posts aren't deleteable for various reasons, so in those
        cases you'll just get a link to the post and an error message (which you'll
        need to deal with on your own.)
        '''
        feed = self.graphLookup("me", "feed") # requires read_stream
        posts=[]
        post_types=set()
        # Get all the posts via the graph API
        while True:
            # Perform some action on each post in the collection we receive from
            # Facebook.
            for post in feed['data']:
                # Attempt to make a request to the next page of data, if it exists.

                post["created_time"] = dparser.parse(post["created_time"])
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
            if not (feed.has_key('paging') and feed['paging'].has_key('next')):
                break
            feed = requests.get(feed['paging']['next']).json()

#         print "Found items of type {0}".format(', '.join(post_types))
        print "\nFound {0} posts to be deleted".format(len(posts))

        for post in posts:
            if 'link' not in post.get('actions',[{}])[0]:
                continue
            url=post['actions'][0]['link']
            if post['type'] in ('link', 'status', 'photo', 'video'):
                self.delete_status(url)
            time.sleep(5)

    def load_page(self, url):
        count=0
        while count < 5:
            try:
#                 print "Loading URL {0}".format(url)
                self.driver.get(url)
                time.sleep(5)
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
                break
            except:
                time.sleep(3)
                count += 1
            else:
                print "Failed to load {0}".format(url)
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
    required_arguments=['max_date','username',]

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
            setattr(options, f, dparser.parse(getattr(options,f )).replace(tzinfo=tzlocal.get_localzone()))
    if max(options.clean_posts, options.clean_photos):
        fbc=FacebookCleaner(username=options.username, password=options.password)
    print dedent('''
        Sometimes the browser page fails to load, and things get stuck!

        To fix this, there are a couple things you can do:
            1.  After the FF window opens, make it narrower - so
                that the ads and messenger are not visible in your browser window.
            2.  If you notice it being "stuck" (i.e. the page is loading for a long time) press the
                browser's "stop" button, then wait a few seconds and things should continue
                normally.

        Sorry, but unfortunately Selenium doesn't have a component that lets the script hit "stop",
        so it's a manual thing.

        Note: If you close the browser window, things will likely stop working.
              Leave it open and watch the magic!

        DANGER DANGER DANGER DANGER DANGER DANGER DANGER DANGER DANGER DANGER

        YOUR FACEBOOK DATA COULD BE DELETED - PRESS CONTROL-C TO ABORT THIS
        PROCESS NOW, IF YOU DON'T WANT THAT TO HAPPEN!!!!

        DANGER DANGER DANGER DANGER DANGER DANGER DANGER DANGER DANGER DANGER
    ''')

    answer=raw_input('This tool could remove portions of, or all of, your facebook account - are you sure you wish to continue (yes/N)? ')
    if answer.lower().strip() != 'yes':
        print "Please enter 'yes' to run this!"
        sys.exit(3)
    if options.clean_posts:
        fbc.clean_posts(max_date=options.max_date,
                        min_date=options.min_date)
    if options.clean_photos:
        fbc.clean_photos(max_date=options.max_date,
                         min_date=options.min_date)
