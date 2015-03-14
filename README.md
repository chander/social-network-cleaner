# Social Network Cleaner

I built this tool because a popular social networking site didn't provide me a way to limit past posts beyond "Friends".  It also occurred to me that there's little reason for my old statuses, etc. to really be out there (aside from perhaps their value to marketers, etc.)

The tool uses an API to access/retrieve a list of items tied to the users account, and then it uses selenium to automate the process of deleting items.  It tries to do this in a controlled manner that goes at a realtively slow pace - turns out that it still gets blocked from time to time, so when the tool starts to get "Page not found" errors it will simply stop for a couple of hours and then try again.  It could take days to clean a busy accounts posts.

Right now it only works on a limited subset of stuff - if it encounters anything that doesn't match what it expects, it just keeps going.  The long term plan would be to augment it to also handle other things (like removing old photos.)

This script is written in Python, so it's not necessarily for the faint of heart.

## Basic Installation

1.  Download and install Python.
2.  Download and install [the virtualenv tool for Python](https://virtualenv.pypa.io/en/latest/)
 * On Debian / Ubuntu: `sudo apt-get install python-virtualenv`
 * On Window you might need to Google for instructions.
3.  Clone this repository: `git clone git@github.com:chander/social-network-cleaner.git` ([Or just download and extract the Zip](https://github.com/chander/social-network-cleaner/archive/master.zip).)
4.  Navigate to the source directory: `cd social-network-cleaner`
5.  Create a virtual environment: `virtualenv venv`
6.  Start the venv: `source venv/bin/activate`
7.  Install the required Python dependencies: `pip install -r requirements.txt`
8.  Run the tool: `python cleaner.py --help`

For example, to remove all posts prior to 2014-06-01 from a users account you can use this command:

     python cleaner.py -u <fb username> -e 2014-06-01 --posts

If you feel like enhancing things, I welcome pull requests - feel free to log issues as well (though I have a job, so I'm not sure how quick I'll be able to address things.)

