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
import re
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
                self.name=self.profile['name']
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
                    self._driver.set_window_size(800, 600)
                # or you can use Chrome(executable_path="/usr/bin/chromedriver")
                self._driver.set_page_load_timeout(10)
                self._driver.get("https://www.facebook.com")
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

    @staticmethod
    def perform_click(driver, elem):
        hover = ActionChains(driver).move_to_element(elem).click()
        hover.perform()
        
    @staticmethod
    def perform_hover(driver, elem):
        hover = ActionChains(driver).move_to_element(elem)
        hover.perform()

    def perform_xpaths(self, url, xpaths, additional_actions=None):
        '''
        Perform a set of xpath queries, in this case the 
        value returned is either a boolean (False) indicating
        that the process failed for some reason, or a list of values, with
        the list normally containing nothing useful.
        
        Default actions are: click (click on something) and hover (hover on something)
        if additional_actions is passed in (a dictionary) the default actions
        get augmented by the new ones.
        '''
        results = []
        actions={'click': self.perform_click,
                 'hover': self.perform_hover}
        if isinstance(additional_actions, (dict,)):
            actions.update(additional_actions)
        if url:
            self.load_page(url)
        for xpath_components in xpaths:
            if len(xpath_components) == 2:
                xpath, required=xpath_components
                action='click'
            elif len(xpath_components) == 3:
                xpath, required, action = xpath_components
            else:
                raise Exception('Invalid arguments to perform_xpaths {0}'.format(xpath_components))
            elem=self.driver.find_elements_by_xpath(xpath)
            if elem:
                elem=elem[0]
                if self.is_visible(elem):
                    results.append(actions[action](self.driver, elem))
            elif required:
                print "Failed xpath lookup ({0}) for URL {1} (aborting)".format(xpath, url)
                return False
            time.sleep(self.delay)
        self.deleted += 1
        if (self.deleted % 10) == 0:
            sys.stdout.write('*')
            sys.stdout.flush()
        return results

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
        xpaths=[("//*[contains(text(), 'Delete this photo')]",False,),
                ("//button[contains(@class, 'Confirm')]", True,),]
        return self.perform_xpaths(url, xpaths)


    def unlike_page(self, url):
        '''
        A simple function to use the Firefox UI to unlike a page that 
        had been liked.  This has the side effect of unfollowing as well.
        '''
        xpaths=[("//button[contains(@class,'PageLikedButton')]",False,'hover'),
                ("//*[contains(text(), 'Unlike')]", True,),]
        return self.perform_xpaths(url, xpaths)

    def delete_album(self, url):
        '''
        A simple function to use the Firefox UI to remove an album.
        '''
        xpaths=[("//a[contains(@class,'fbPhotoAlbumOptionsGear')]", True),
                ("//*[contains(text(), 'Delete Album')]",False,),
                ("//button[contains(@class, 'Confirm')]", True),]
        return self.perform_xpaths(url, xpaths)

    def untag_photo(self, url):
        '''
        A simple function to use the Firefox UI to remove an album.  Hover
        over the username and the click remove tag to remove the tag.
        '''
        xpaths=[("//a[contains(@class,'taggee') and contains(text(), '{0}')]".format(self.name), True,'hover'),
                ("//a[contains(text(), 'Remove Tag')]",True,),
                ("//button[contains(text(), 'Okay')]", False,),]
        return self.perform_xpaths(url, xpaths)
    
    def album_generator(self):
        albums = self.graphLookup("me", "albums")
        album_list=[]
        # Get a list of albums.  We make the list because sometimes we'll
        # delete entire albums as we go along, which might mess up the API results.
        while True:
            for album in albums['data']:
                yield album
            if not (albums.has_key('paging') and albums['paging'].has_key('next')):
                break
            albums=requests.get(albums['paging']['next']).json()
            
    def clean_albums(self, max_date, min_date):
        deleted_albums=0
        for album in self.album_generator():
            album["updated_time"] = dparser.parse(album["updated_time"])
            if (album['updated_time'] < max_date and
                (not min_date or album['updated_time'] > min_date)):
                self.delete_album(album['link'])
                deleted_albums+=1
        print "There were {0} album(s) with photos removed".format(deleted_albums)

            
    def photo_generator(self, max_date, min_date):
        '''
        A generator that iterates over all the photos and albums to return them
        all.  The albums (if any) are deleted as it goes along, unless it finds
        that the update timestamp makes it ineligible for deletion - in which
        case it just recurses through the photos therein
        '''
        
        # It's questionable as to whether this is still needed - since there's
        # a separate set of methods for deleting albums, and the pictures
        # should all come back from photos/uploaded if there are any.
#         for album in self.album_generator():
#             pictures=self.graphLookup(album['id'],"photos")
#             while True:
#                 for picture in pictures['data']:
#                     yield picture
#                 if not (pictures.has_key('paging') and pictures['paging'].has_key('next')):
#                     break
#                 pictures=requests.get(pictures['paging']['next']).json()
        # Note: we could use photos/uploaded to get just ours, but since this is
        # used by the clean tagged stuff also, we'll just use it all..
        pictures = self.graphLookup("me", "photos")
        while True:
            for picture in pictures['data']:
                yield picture
            if not (pictures.has_key('paging') and pictures['paging'].has_key('next')):
                break
            print "paging..."
            pictures=requests.get(pictures['paging']['next']).json()

    def page_likes_generator(self, max_date, min_date):
        '''
        A generator that iterates over all the page likes to return those pages
        that were liked.
        '''
        likes = self.graphLookup("me", "likes")
        page_likes=[]
        while True:
            for page_like in likes['data']:
                yield page_like
            if not (likes.has_key('paging') and likes['paging'].has_key('next')):
                break
            likes=requests.get(page_likes['paging']['next']).json()

    def clean_page_likes(self, max_date, min_date=None):
        '''
        Use the page_likes generator to get all the pages a user has liked,
        and then unlike them (based on the date range selected.)
        '''
        page_likes=[]
        for page_like in self.page_likes_generator(max_date, min_date):
            page_like["created_time"] = dparser.parse(page_like["created_time"])
            if (page_like['created_time'] < max_date and
                (not min_date or page_like['created_time'] > min_date)):
                page_likes.append(page_like)
                if (len(page_likes) % 10) == 0:
                    sys.stdout.write('L')
                    sys.stdout.flush()
        print "\nThere are {0} page's to be unliked".format(len(page_likes))
        for page_like in page_likes:
            url='https://facebook.com/{0}'.format(page_like['id'])
            self.unlike_page(url)
            
    def clean_tagged_photos(self, max_date, min_date=None):
        '''
        Use the photos generator to clean all photos that a user has been
        tagged in, including those that the user might own him/herself
        '''
        tagged_photos=[]
        for tagged_photo in self.photo_generator(max_date, min_date):
            tagged_photo["created_time"] = dparser.parse(tagged_photo["created_time"])
            if tagged_photo['from']['id'] != self.id: # Someone else's photo
                tagged_photos.append(tagged_photo)
            # Our photo where we are tagged in it..
            elif 'tags' in tagged_photo and 'data' in tagged_photo['tags']:
                for elem in tagged_photo['tags']['data']:
                    if elem['from']['id'] == self.id:
                        tagged_photos.append(tagged_photo)
                        break
            if (len(tagged_photos) % 10) == 0:
                sys.stdout.write('T')
                sys.stdout.flush()
        print "\nThere are {0} photos's to be untagged".format(len(tagged_photos))
        for tagged_photo in tagged_photos:
            self.untag_photo(tagged_photo['link'])

    def clean_photos(self, max_date, min_date=None):
        '''
        Use the photo generator to get a list of all photos in all albums,
        and then delete them. In this case the albums actually will get
        deleted by the generator (assuming they have been last updated
        before the delete range.)  This is much better, since deleting an
        album deletes all the photos inside it (as opposed to having to
        delete each one.)
        '''
        pictures=[]
        picture_types=set()
        self.clean_albums(max_date, min_date)
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
                ("//input[@name='user_likes']",False,),
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
                except:
                    continue
                if 'Log in' in self.driver.title:
                    xpaths=[("//button[contains(text(), 'Okay')]", True,)]
                    self.perform_xpaths(None, xpaths)
            self.driver.switch_to_window(main_window_handle)
        elem=self.driver.find_element_by_id("access_token")
        token=elem.get_attribute("value");
        self.delay=delay
        return token

    def get_pretty_user_id(self):
        '''
        Get the user_id of the facebook user - note that it's unclear 
        if this works for a user without a set userid for facebook (this
        is different than the users login name.)  If the user does not
        have a facebook userid, this might not work as expected ?
        '''
        additional_actions={'copy': lambda driver, elem: elem.get_attribute("href")}
        xpaths=[("//a[@class='fbxWelcomeBoxName']", True, 'copy')]
        pretty_user_id = self.perform_xpaths("https://www.facebook.com", xpaths,
                                             additional_actions)
        if pretty_user_id:
            return pretty_user_id[0].split("/")[3]

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

        print "\nFound {0} posts to be deleted".format(len(posts))

        pretty_user_id = self.get_pretty_user_id()

        for post in posts:
            if 'link' not in post.get('actions',[{}])[0]:
                continue
            url=post['actions'][0]['link']

            # Some users have "pretty" user IDs and Facebook seems to prefer their
            # use to numerical user IDs in post URLs
            if pretty_user_id:
                url = re.sub(r"/([0-9]+)/posts", "/%s/posts" % pretty_user_id, url)

            if post['type'] in ('link', 'status', 'photo', 'video'):
                self.delete_status(url)
            time.sleep(5)

    def load_page(self, url):
        count=0
        while count < 5:
            try:
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
    parser.add_option("--untag-photos",
                      action='store_true',
                      dest="clean_tagged_photos", default=False,
                      help="Untag Photos that a user is tagged in")
    parser.add_option("--posts",
                      action='store_true',
                      dest="clean_posts", default=False,
                      help="Remove Posts")
    parser.add_option("--page-likes",
                      action='store_true',
                      dest="clean_page_likes", default=False,
                      help="Unlike any liked pages")
    (options, args) = parser.parse_args()
    required_arguments=['max_date','username',]

    for arg in required_arguments:
        missing_args=[]
        if getattr(options, arg, None) is None:
            missing_args.append(arg)
    if missing_args:
        print "Missing argument(s) for {0}".format(', '.join(missing_args))
        parser.print_help()
        exit(0)

    if not max(options.clean_posts, options.clean_photos, options.clean_page_likes,
               options.clean_tagged_photos):
        print "Must specify at least one action (--photos, --posts, --untag-photos, --page-likes)!"
        parser.print_help()
        exit(0)

    while not options.password:
        options.password=getpass.getpass('Enter password for {0}: '.format(options.username))


    for f in ['max_date', 'min_date']:
        if getattr(options, f):
            setattr(options, f, dparser.parse(getattr(options,f )).replace(tzinfo=tzlocal.get_localzone()))
    fbc=FacebookCleaner(username=options.username, password=options.password)
    print dedent('''
        Sometimes the browser page fails to load, and things get stuck!

        To fix this, there are a couple things you can do:
            1.  If the FF window opens but no webpage is loaded you might need to upgrade
                Selenium. Update the version in requirements.txt and re-install the depdendencies.
            2.  After the FF window opens, make it narrower - so
                that the ads and messenger are not visible in your browser window.
            3.  If you notice it being "stuck" (i.e. the page is loading for a long time) press the
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
    if options.clean_tagged_photos:
        fbc.clean_tagged_photos(max_date=options.max_date,
                                min_date=options.min_date)
    if options.clean_page_likes:
        fbc.clean_page_likes(max_date=options.max_date,
                             min_date=options.min_date)
