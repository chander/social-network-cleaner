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
import datetime
import tzlocal
import requests
import sys
import pytz
import pprint
import time
import traceback
from threading import Timer
from collections import defaultdict
import re
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
import selenium.webdriver.support.expected_conditions as EC
import selenium.webdriver.support.ui as ui
from bs4 import BeautifulSoup
import logging
rootHandler = logging.getLogger()
handler = logging.StreamHandler(sys.stdout)
rootHandler.addHandler(handler)

logger = logging.getLogger(__name__)


class FacebookCleaner(object):

    def __init__(self, username, password):
        self.login = False
        self.username = username
        self.password = password
        self.printer = pprint.PrettyPrinter(indent=4)
        self.nfcount = 0
        self.nfcount_cycles = 0
        self.deleted = 0
        self.delay = 1

    @property
    def graph(self):
        '''
        Intialize the graph stuff on the first attempt, or if the token is more
        than 3300 seconds old (since I think they expire after ~ 1 hour, and we need
        likely no more than 5 minutes to query the API in a single request set.)
        '''
        if (not getattr(self, '_graph', None)) or self.token_expires < time.time():
            token = self.get_api_token()
            self.token_expires = time.time() + 3300
            self._graph = facebook.GraphAPI(access_token=token)
            try:
                self.profile = self._graph.get_object('me')
                self.id = self.profile['id']
                self.name = self.profile['name']
            except facebook.GraphAPIError, e:
                logger.error(
                    "Failure to access Graph API with token - error: %s", e)
                logger.error(
                    "Perhaps you need to get a new one here: https://developers.facebook.com/tools/explorer/")
                sys.exit(1)
        return self._graph

    @property
    def driver(self):
        '''
        Load the browser and driver when it's first requested/used, rather than
        when the object is initialized.
        '''
        attempts = 0
        while not self.login:
            try:
                if not getattr(self, '_driver', None):
                    self._driver = webdriver.Firefox()
                    self._driver.set_window_size(800, 600)
                # or you can use
                # Chrome(executable_path="/usr/bin/chromedriver")
                self._driver.set_page_load_timeout(10)
                self._driver.get("https://www.facebook.com")
                assert "Facebook" in self._driver.title
                elem = self._driver.find_element_by_id("email")
                elem.send_keys(self.username)
                elem = self._driver.find_element_by_id("pass")
                elem.send_keys(self.password)
                elem.send_keys(Keys.RETURN)
                self.login = True
                time.sleep(5)
            except:
                attempts += 1
                if attempts > 5:
                    logger.error(
                        'Login failed - perhaps facebook is slow?!\n')
                    sys.exit(2)

        return self._driver

    def graphLookup(self, *args, **kwargs):
        try:
            return self.graph.get_connections(*args, **kwargs)
        except facebook.GraphAPIError, e:
            logger.error("Failure to access Graph API: %s", e)
            logger.error(
                "This might be because your deletes took too long - get a new one and restart this tool?")
            logger.error(
                "Perhaps you need to get a new one here: https://developers.facebook.com/tools/explorer/")
            sys.exit(1)

    def __del__(self):
        if hasattr(self, '_driver'):
            self._driver.close()

    # return True if element is visible within 2 seconds, otherwise False
    def is_visible(self, elem, timeout=2):
        time.sleep(.5)
        return True
        try:
            ui.WebDriverWait(self.driver, timeout).until(
                EC.visibility_of(elem))
            return True
        except TimeoutException:
            return False

    def navigateHomePage(self):
        '''
        A simple function to navigate to the users page from the main page.
        This goes to the activity log page, and then keeps scrolling down until
        the entire activity log has been loaded.
        '''
        username = self.get_user_id()
        logger.info(
            "Loading the entire activity log in the browser - this can take awhile!")
        url = 'https://www.facebook.com/'.format(username)
        xpaths = [("//a[@title='Profile']", True,), ]
        result = self.perform_xpaths(url, xpaths)
        # Keep scrolling to the bottom until there's nothing left...
        current_height = False
        height = True
        while height != current_height:
            current_height = self.driver.execute_script(
                'return document.body.scrollHeight;')
            self._driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);")
            for i in range(30):
                height = self.driver.execute_script(
                    'return document.body.scrollHeight;')
                if height != current_height:
                    break
                time.sleep(.5)
            time.sleep(2)
            height = self.driver.execute_script(
                'return document.body.scrollHeight;')
        return result

    def navigateActivityLog(self):
        '''
        A simple function to navigate to the activity log from the main page.
        This goes to the activity log page, and then keeps scrolling down until
        the entire activity log has been loaded.
        '''
        logger.info(
            "Loading the entire activity log in the browser - this can take awhile!")
        url = 'https://www.facebook.com/'
        xpaths = [("//*[contains(text(), 'Account Settings')]", True,),
                  ("//div[contains(text(), 'Activity Log')]", True,), ]
        result = self.perform_xpaths(url, xpaths)
        # Keep scrolling to the bottom until there's nothing left...
        current_height = False
        height = True
        while height != current_height:
            current_height = self.driver.execute_script(
                'return document.body.scrollHeight;')
            self._driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);")
            for i in range(30):
                height = self.driver.execute_script(
                    'return document.body.scrollHeight;')
                if height != current_height:
                    break
                time.sleep(.5)
            time.sleep(2)
            height = self.driver.execute_script(
                'return document.body.scrollHeight;')
        return result

    @staticmethod
    def perform_click(driver, elem):
        hover = ActionChains(driver).move_to_element(elem).click()
        try:
            hover.perform()
        except Exception, e:
            if 'HTMLSpanElement' not in str(e):
                logger.debug("Failed click: %s", e)

    @staticmethod
    def perform_hover(driver, elem):
        hover = ActionChains(driver).move_to_element(elem)
        try:
            hover.perform()
        except Exception, e:
            if 'HTMLSpanElement' not in str(e):
                logger.debug("Failed hover: %s", e)

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
        actions = {'click': self.perform_click,
                   'hover': self.perform_hover}
        if isinstance(additional_actions, (dict,)):
            actions.update(additional_actions)
        if url:
            self.load_page(url)
        for xpath_components in xpaths:
            if len(xpath_components) == 2:
                xpath, required = xpath_components
                action = 'click'
            elif len(xpath_components) == 3:
                xpath, required, action = xpath_components
            else:
                raise Exception(
                    'Invalid arguments to perform_xpaths {0}'.format(xpath_components))

            # Transform lower-case into translate function as it is not included with
            # xpath 1.0 (It's useful for performing case-insensitive matching.)
            xpath = re.sub(r"lower-case\((.+?)\),",
                           r"translate(\1, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),",
                           xpath)

            elem = self.driver.find_elements_by_xpath(xpath)
            if elem:
                elem = elem[0]
                if self.is_visible(elem):
                    results.append(actions[action](self.driver, elem))
            elif required:
                logger.debug(
                    "Failed xpath lookup (%s) for URL %s (aborting)", xpath, url)
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
        xpaths = [("//*[@aria-label='Story options']", True,),
                  ("//*[contains(text(), 'More options')]", False,),
                  ("//span[contains(text(), 'Delete')]", True,),
                  ("//button[contains(text(), 'Delete Post')]", True,), ]
        return self.perform_xpaths(url, xpaths)

    def delete_photo(self, url):
        '''
        A simple function to use the Firefox UI to remove a photo.
        '''
        xpaths = [("//*[contains(text(), 'Delete this photo')]", False,),
                  ("//button[contains(@class, 'Confirm')]", True,), ]
        return self.perform_xpaths(url, xpaths)

    def unlike_page(self, url):
        '''
        A simple function to use the Firefox UI to unlike a page that
        had been liked.  This has the side effect of unfollowing as well.
        '''
        xpaths = [("//button[contains(@class,'PageLikedButton')]", False, 'hover'),
                  ("//*[contains(text(), 'Unlike')]", True,), ]
        return self.perform_xpaths(url, xpaths)

    def delete_album(self, url):
        '''
        A simple function to use the Firefox UI to remove an album.
        '''
        xpaths = [("//a[contains(@class,'fbPhotoAlbumOptionsGear')]", True),
                  ("//*[contains(text(), 'Delete Album')]", False,),
                  ("//button[contains(@class, 'Confirm')]", True), ]
        return self.perform_xpaths(url, xpaths)

    def untag_photo(self, url):
        '''
        A simple function to use the Firefox UI to remove an album.  Hover
        over the username and the click remove tag to remove the tag.
        '''
        xpaths = [("//a[contains(@class,'taggee') and contains(text(), '{0}')]".format(self.name), True, 'hover'),
                  ("//a[contains(lower-case(text()), 'remove tag')]", True,),
                  ("//button[contains(@class, 'Confirm')]", False,), ]
        return self.perform_xpaths(url, xpaths)

    def album_generator(self):
        albums = self.graphLookup("me", "albums")
        album_list = []
        # Get a list of albums.  We make the list because sometimes we'll
        # delete entire albums as we go along, which might mess up the API
        # results.
        while True:
            for album in albums['data']:
                yield album
            if not (albums.has_key('paging') and albums['paging'].has_key('next')):
                break
            albums = requests.get(albums['paging']['next']).json()

    def clean_albums(self, max_date, min_date):
        deleted_albums = 0
        for album in self.album_generator():
            album["updated_time"] = dparser.parse(album["updated_time"])
            if (album['updated_time'] < max_date and
                    (not min_date or album['updated_time'] > min_date)):
                self.delete_album(album['link'])
                deleted_albums += 1
        logger.info(
            "There were %s album(s) with photos removed", deleted_albums)

    def photo_generator(self, max_date, min_date):
        '''
        A generator that iterates over all the photos and albums to return them
        all.  The albums (if any) are deleted as it goes along, unless it finds
        that the update timestamp makes it ineligible for deletion - in which
        case it just recurses through the photos therein
        '''
        # Note: we could use photos/uploaded to get just ours, but since this is
        # used by the clean tagged stuff also, we'll just use it all..
        pictures = self.graphLookup("me", "photos")
        while True:
            for picture in pictures['data']:
                yield picture
            if not (pictures.has_key('paging') and pictures['paging'].has_key('next')):
                break
            logger.debug("paging...")
            pictures = requests.get(pictures['paging']['next']).json()

    def page_likes_generator(self, max_date, min_date):
        '''
        A generator that iterates over all the page likes to return those pages
        that were liked.
        '''
        likes = self.graphLookup("me", "likes")
        page_likes = []
        while True:
            for page_like in likes['data']:
                yield page_like
            if not (likes.has_key('paging') and likes['paging'].has_key('next')):
                break
            likes = requests.get(page_likes['paging']['next']).json()

    def purgeActivity(self, max_date, min_date):
        '''
        Go through the activity log and remove things...
        '''
        post_purge_items = ('tagged_in', 'tagged_at')
        post_purge = []
        for item_date, items in self.getOrderedActivity():
            if (item_date > max_date or
                    (min_date and item_date < min_date)):
                continue
            for item_type, item in items:
                if item_type in post_purge_items:
                    logger.debug(
                        'Adding item of type %s (on %s) to post_purge list',
                        item_type, item_date)
                    post_purge.append(item)
                else:
                    logger.debug(
                        "Purging item type of %s, on %s", item_type, item_date)
                    self.purgeElement(item, post_purge_items)
        # Now the post_purge_items contains those things that need to be unliked
        # or untagged
        # print post_purge

    def purgeElement(self, item, post_purge=[]):
        '''
        Locate an edit button of an item, click it, and then perform
        the appropriate purge action.  This is specifically geared towards
        the activity log...
        '''
        item_bs = BeautifulSoup(item.get_attribute('innerHTML'))
        # Locate all the id tags in the parents.
        parents = [i.get('id')
                   for i in item_bs.find_all(lambda tag: tag.has_attr('id'))]
        # Build an Xpath query to locate any item with an ownerid that's in the
        # parent..
        xpath_string = ' | '.join("//*[contains(@data-ownerid, '{0}')]".format(parent_id)
                                  for parent_id in parents)
        try:
            edit = item.find_elements_by_xpath(
                ".//a[contains(@role,'button')]")[-1]
        except:
            return
        self.perform_click(self.driver, edit)
        time.sleep(1)
        elements = self.driver.find_elements_by_xpath(xpath_string)
        # We need to delete things from the most effective to least effective
        # so we start with delete, if that's not there then unlike, and if
        # that's not there then hide from timeline.  In each case we loop through
        # all the elements to look for the one we need, if we find it that's where we
        # stop.
        xpath_pairs = [('delete', ".//span[contains(text(), 'Delete')]",),
                       ('unlike', ".//span[contains(text(), 'Unlike')]",),
                       ('unvote',
                        ".//span[contains(text(), 'Unvote')]",),
                       #                        ('hidden from timeline',
                       #                         ".//span[contains(text(), 'Hidden from Timeline')]",),
                       ]
        delete_xpaths = [("//span[contains(lower-case(text()), 'delete')]",
                          False,),
                         ("//button[contains(lower-case(text()), 'delete post')]",
                          False,),
                         ("//button[contains(lower-case(text()), 'confirm')]",
                          False,),
                         ]
        for keyword, xpathq in xpath_pairs:
            for elem in elements:
                elem2 = None
                bs = BeautifulSoup(elem.get_attribute('innerHTML'))
                if keyword in bs.text.lower():
                    elem2 = elem.find_elements_by_xpath(xpathq)
                if elem2:
                    time.sleep(1)
                    self.perform_click(self.driver, elem2[0])
                    result = self.perform_xpaths(None, delete_xpaths)
                    return result

    def cleanWall(self, max_date, min_date):
        '''
        Navigate to load the whole home page, then go and clean it up
        '''
        self.navigateHomePage()
        # Find the parent div for stories
        xpath_q = "//div[@data-time]"
        child_q = ".//a[@aria-label='Story options']"

        final_xpaths = [".//li[@role='presentation']//*[contains(text(), 'Remove tag')]",
                        ".//li[@role='presentation']//*[contains(text(), 'Remove Tag')]",
                        ".//li[@role='presentation']//*[contains(text(), 'Delete')]",
                        ".//li[@role='presentation']//*[contains(text(), 'Hide from timeline')]",
                        ".//li[@role='presentation']//*[contains(text(), 'Hide from Timeline')]",
                        ]
        delete_xpaths = [("//span[contains(lower-case(text()), 'delete')]",
                          False,),
                         ("//button[contains(lower-case(text()), 'delete post')]",
                          False,),
                         ("//button[contains(lower-case(text()), 'confirm')]",
                          False,),
                         ("//button[contains(lower-case(text()), 'okay')]",
                          False,),
                         ]
        for item in self.driver.find_elements_by_xpath(xpath_q):
            try:
                item_date = datetime.datetime.fromtimestamp(
                    int(item.get_attribute('data-time')), pytz.utc)
                if (item_date > max_date or
                        (min_date and item_date < min_date)):
                    continue
                edit = item.find_elements_by_xpath(child_q)
                if edit:
                    self.perform_click(self.driver, edit[0])
                time.sleep(1)
                elems = [e for xpathq in final_xpaths
                         for e in self.driver.find_elements_by_xpath(
                             xpathq) if e.is_displayed()]
                for elem in elems:
                    self.perform_click(self.driver, elem)
                    time.sleep(3)
                    result = self.perform_xpaths(
                        None, delete_xpaths)
                    break

            except Exception, e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.exception('Failed attempt to delete story')

    def getOrderedActivity(self):
        self.navigateActivityLog()
        bborders = self.driver.find_elements_by_xpath(
            "//*[contains(@class,'bottomborder')] | //div[contains(@class, '_iqq')]")
        bborders.reverse()
        bborders_copy = bborders[:]
        item_dates = defaultdict(list)
        id_list = []
        months = [datetime.date(2015, i, 1).strftime(
            '%B').lower() for i in range(1, 13)]
        year_re = re.compile('({0})\s+(\d{{4}})'.format('|'.join(months),),
                             flags=re.IGNORECASE)

        this_year = datetime.datetime.now().date().strftime('%Y')
        # Get tody and yesterday.
        today = datetime.datetime.now().date().strftime('%B %d')
        yesterday = (
            datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%B %d')
        all_items = []
        for pos, item in enumerate(bborders):
            innerdata = item.get_attribute('innerHTML')
            soup = BeautifulSoup(innerdata)
            text = soup.text.encode('ascii', 'ignore').decode('ascii')
            year_match = year_re.match(text)
            skip = False
            # We found  year, so save that set of stuff.
            if year_match:
                logger.debug(u"{0}: Got Year {1}".format(pos,
                                                         year_match.group(2)))
                if item_dates:
                    for mon_day, day_items in item_dates.iteritems():
                        item_date = dparser.parse('{0}, {1}'.format(
                            mon_day, year_match.group(2))).replace(tzinfo=tzlocal.get_localzone())
#                         all_items.append((item_date, day_items,))
                        # Now yield this set of stuff as a set of objects that includes
                        # the actual date of the post
                        logger.debug(
                            'Returning %s items for %s', len(day_items), item_date)
                        yield item_date, day_items
                else:
                    logger.debug("No item dates??!")
                item_dates = defaultdict(list)
                # A year entry is always followed by a date entry, so there
                # really should be no entries in id_list when we find a year..
                if len(id_list) != 0:
                    logger.debug("WTF! Id_list contains %s", id_list)
                    id_list = []
                continue
            else:
                for m in months:
                    if innerdata.lower().startswith(m):
                        logger.debug("Got Date %s", innerdata)
                        if innerdata.lower() == 'today':
                            innerdata = today
                        if innerdata.lower() == 'yesterday':
                            innerdata = yesterday
                        if id_list:
                            # innerdata is a month and day
                            item_dates[innerdata].extend(id_list)
                        id_list = []
                        skip = True
                        break
                if skip:
                    continue
                if text.startswith('You commented on'):
                    act_type = 'comment'
                elif text.startswith('You were mentioned'):
                    act_type = 'mentioned'
                elif 'updated' in text and 'status' in text:
                    logger.debug('Ignoring status update')
                    continue
                elif 'added a new photo' in text:
                    logger.debug('Ignoring added photo')
                    continue
                elif 'wrote on yourtimeline' in text:
                    act_type = 'wrote_on_me'
                elif 'wrote on' in text:
                    act_type = 'wrote_on'
                elif 'shared alink' in text or 'shared a link' in text:
                    act_type = 'shared_link'
                elif 'likes alink' in text or 'likes a link' in text:
                    act_type = 'liked_link'
                elif 'tagged in' in text:
                    act_type = 'tagged_in'
                elif 'tagged at' in text:
                    act_type = 'tagged_at'
                elif 'became friends' in text:
                    act_type = 'friend'
                elif 'Happy Birthday' in text:
                    act_type = 'birthday'
                elif 'friend request' in text:
                    act_type = 'friend_request'
                elif 'worked on' in text:
                    act_type = 'worked_on'
                elif text.startswith('You like'):
                    act_type = 'like'
                elif 'posted in' in text:
                    act_type = 'posted_in'
                elif 'replied to your' in text and 'comment' in text:
                    act_type = 'replied_commend'
                else:
                    act_type = 'unknown'
                    logger.debug('UNKNOWN: {0}'.format(text))
                id_list.append((act_type, item,))

        return

    def clean_page_likes(self, max_date, min_date=None):
        '''
        Use the page_likes generator to get all the pages a user has liked,
        and then unlike them (based on the date range selected.)
        '''
        page_likes = []
        for page_like in self.page_likes_generator(max_date, min_date):
            page_like["created_time"] = dparser.parse(
                page_like["created_time"])
            if (page_like['created_time'] < max_date and
                    (not min_date or page_like['created_time'] > min_date)):
                page_likes.append(page_like)
                if (len(page_likes) % 10) == 0:
                    sys.stdout.write('L')
                    sys.stdout.flush()
        logger.info(
            "There are {0} page's to be unliked".format(len(page_likes)))
        for page_like in page_likes:
            url = 'https://facebook.com/{0}'.format(page_like['id'])
            self.unlike_page(url)

    def clean_tagged_photos(self, max_date, min_date=None):
        '''
        Use the photos generator to clean all photos that a user has been
        tagged in, including those that the user might own him/herself
        '''
        tagged_photos = []
        for tagged_photo in self.photo_generator(max_date, min_date):
            tagged_photo["created_time"] = dparser.parse(
                tagged_photo["created_time"])
            if tagged_photo['from']['id'] != self.id:  # Someone else's photo
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
        logger.info(
            "There are {0} photos's to be untagged".format(len(tagged_photos)))
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
        pictures = []
        picture_types = set()
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
        logger.info(
            "There are {0} pictures to be deleted".format(len(pictures)))
        for picture in pictures:
            if 'link' in picture:
                url = picture['link']
            else:
                continue
            self.delete_photo(url)

    def get_api_token(self):
        main_window_handle = self.driver.window_handles[0]
        delay = self.delay
        self.delay = 5
        url = 'https://developers.facebook.com/tools/explorer/'
        xpaths = [("//*[@id='get_access_token']", True,),
                  ("//a[contains(text(), 'Clear')]", True,),
                  ("//input[@name='user_status']", False,),
                  ("//input[@name='user_relationship']", False,),
                  ("//input[@name='user_photos']", False,),
                  ("//input[@name='user_videos']", False,),
                  ("//input[@name='user_interests']", False,),
                  ("//input[@name='user_friends']", False,),
                  ("//input[@name='user_events']", False,),
                  ("//input[@name='user_likes']", False,),
                  ("//*[@data-group='extended']", True,),
                  ("//input[@name='read_stream']", False,),
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
                    xpaths = [("//button[contains(text(), 'Okay')]", True,)]
                    self.perform_xpaths(None, xpaths)
            self.driver.switch_to_window(main_window_handle)
        elem = self.driver.find_element_by_id("access_token")
        token = elem.get_attribute("value")
        self.delay = delay
        return token

    def get_user_id(self):
        '''
        Get the user_id of the Facebook user, the pretty one the user selected
        if it exists, otherwise the numerical ID.
        '''
        additional_actions = {
            'copy': lambda driver, elem: elem.get_attribute("href")}
        xpaths = [("//a[@class='fbxWelcomeBoxName']", True, 'copy')]
        user_id = self.perform_xpaths("https://www.facebook.com", xpaths,
                                      additional_actions)
        if user_id:
            return user_id[0].split("/")[3]

    def clean_posts(self, max_date, min_date=None):
        '''
        Iterate over the posts for an account and delete them if possible,
        note that many posts aren't deleteable for various reasons, so in those
        cases you'll just get a link to the post and an error message (which you'll
        need to deal with on your own.)
        '''
        feed = self.graphLookup("me", "feed")  # requires read_stream
        posts = []
        post_types = set()
        # Get all the posts via the graph API
        while True:
            # Perform some action on each post in the collection we receive from
            # Facebook.
            for post in feed['data']:
                # Attempt to make a request to the next page of data, if it
                # exists.

                post["created_time"] = dparser.parse(post["created_time"])
                post_types.add(post['type'])
                if (post['created_time'] < max_date and
                        (not min_date or post['created_time'] > min_date)):
                    if post['from']['id'] != self.id:
                        continue
                    if post['type'] not in ('status', 'link', 'photo', 'video',):
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

        logger.info("Found {0} posts to be deleted".format(len(posts)))

        user_id = self.get_user_id()

        for post in posts:
            if 'link' not in post.get('actions', [{}])[0]:
                continue
            url = post['actions'][0]['link']

            # Some users have "pretty" user IDs and Facebook seems to prefer their
            # use to numerical user IDs in post URLs
            if user_id:
                url = re.sub(r"/([0-9]+)/posts", "/%s/posts" % user_id, url)

            if post['type'] in ('link', 'status', 'photo', 'video'):
                self.delete_status(url)
            time.sleep(5)

    def load_page(self, url):
        count = 0
        while count < 5:
            try:
                self.driver.get(url)
                time.sleep(5)
                if "Page Not Found" in self.driver.title:
                    self.nfcount += 1
                    if self.nfcount < 10:
                        time.sleep(2)
                        continue
                    else:
                        logger.info(
                            "Too many failed requests, sleeping for 2 hours")
                        time.sleep(60 * 60 * 2)
                        self.nfcount_cycles += 1
                        self.nfcount = 0
                        if self.nfcount_cycles > 10:
                            print "Exiting - too many failures"
                            sys.exit(0)
                        continue
                break
            except:
                time.sleep(3)
                count += 1
            else:
                logger.info("Failed to load {0}".format(url))
                continue


if __name__ == '__main__':
    description = '''
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
    parser.add_option("--purge-activity",
                      action='store_true',
                      dest="purge_activity", default=False,
                      help="Purge (almost) everything, including others comments, tagged photos, unliking, etc. using the activity log (do this last!)")
    parser.add_option("--clean-wall",
                      action='store_true',
                      dest="clean_wall", default=False,
                      help="Delete stuff from the wall.")
    parser.add_option("--page-likes",
                      action='store_true',
                      dest="clean_page_likes", default=False,
                      help="Unlike any liked pages")
    parser.add_option("--debug",
                      action='store_true',
                      dest="debug", default=False,
                      help="Enable debug output.")
    (options, args) = parser.parse_args()
    required_arguments = ['max_date', 'username', ]

    if options.debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    for arg in required_arguments:
        missing_args = []
        if getattr(options, arg, None) is None:
            missing_args.append(arg)
    if missing_args:
        print "Missing argument(s) for {0}".format(', '.join(missing_args))
        parser.print_help()
        exit(0)

    if not max(options.clean_posts, options.clean_photos, options.clean_page_likes,
               options.clean_tagged_photos, options.purge_activity, options.clean_wall):
        print ("Must specify at least one action (--photos, --posts, " +
               "--untag-photos, --page-likes, --clean-wall, --purge-activity)!")
        parser.print_help()
        exit(0)

    while not options.password:
        options.password = getpass.getpass(
            'Enter password for {0}: '.format(options.username))

    for f in ['max_date', 'min_date']:
        if getattr(options, f):
            setattr(options, f, dparser.parse(getattr(options, f)).replace(
                tzinfo=tzlocal.get_localzone()))
    fbc = FacebookCleaner(username=options.username, password=options.password)
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

    answer = raw_input(
        'This tool could remove portions of, or all of, your facebook account - are you sure you wish to continue (yes/N)? ')
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
    if options.purge_activity:
        fbc.purgeActivity(max_date=options.max_date, min_date=options.min_date)
    if options.clean_wall:
        fbc.cleanWall(max_date=options.max_date, min_date=options.min_date)
