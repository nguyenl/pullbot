# Copyright (C) 2012 Lee Nguyen

# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:

# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# pullbot is a simple irc that notifies irc channels of new pull
# requests.
import sys
from twisted.words.protocols import irc
from twisted.internet import protocol, reactor, task
from twisted.internet.protocol import ReconnectingClientFactory
from urlparse import urljoin
from optparse import OptionParser
import requests
import simplejson
import logging
from datetime import datetime


# Default Configuration
NICKNAME = 'PullBot'
HOST =  'irc.fisa'
PORT = 6667
RECONNECT_DELAY = 60
CHANNELS = ("#test",)
QUERY_FREQUENCY = 300  # Seconds between github queries.
API_TOKEN = "" # The github API token to authenticate with.


# The github repos to watch. Each tuple contains the owner and repository name.
REPOS = (
    ('nguyenl', 'pullbot'),
    )


# Setup logging
logger = logging.getLogger('pullbot')
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)


class PullRequestNotifier(object):
    '''
    Checks Github for new Pull Requests.
    '''
    PULL_REQUESTS_URL = "https://api.github.com/repos/%(owner)s/%(repo)s/pulls?access_token=%(token)s"
    PULL_REQUESTS_COMMENTS_URL = "https://api.github.com/repos/%(owner)s/%(repo)s/pulls/%(number)s/comments?access_token=%(token)s"
    state = None
    state_file = "pullbot_state.json"

    # Load the static state.
    try:
        f = open(state_file, 'r')
        state = simplejson.load(f)
        f.close()
    except:
        logger.warning("Unable to load state file:", sys.exc_info()[0])
        # If loading the state fails.  Assume no previous state
        # and start fresh.
        state = {}

    def __init__(self, owner, repo, token):
        '''
        Initialize with the owner name, repository, and authentication token.
        '''
        self.owner = owner
        self.repo = repo
        self.token = token

    @staticmethod    
    def save_state():
        '''
        Save the state of the notifier. Saving state ensures that the
        notifier does re-notify pull requests that have already been
        notified.
        '''
        state_json = simplejson.dumps(PullRequestNotifier.state)
        f = open(PullRequestNotifier.state_file, 'w')
        f.write(state_json + "\n")
        f.close()

    @property
    def pull_requests_url(self):
        url_dict = {
            'owner': self.owner,
            'repo': self.repo,
            'token': self.token,
            }
        url = self.PULL_REQUESTS_URL % url_dict
        return url

    def get_pull_requests_comments_url(self, number):
        '''
        Return the API Url to retrieve the comments for the given pull request number.
        '''
        url_dict = {
            'owner': self.owner,
            'repo': self.repo,
            'token': self.token,
            'number': number,
            }
        url = self.PULL_REQUESTS_COMMENTS_URL % url_dict
        return url

    def get_comments(self, number):
        '''
        Query the Github API for the given Pull Request number for comments.
        '''
        comment_url = self.get_pull_requests_comments_url(number)
        r = requests.get(comment_url)
        logger.debug(r.text)
        comments = simplejson.loads(r.text)
        return comments

    def query(self):
        '''
        Query github for open pull requests.
        Returns the json provided by the API.
        '''
        logger.info("Querying Github")
        r = requests.get(self.pull_requests_url)
        logger.debug(r.text)
        pull_requests = simplejson.loads(r.text)
        if 'error' in pull_requests and pull_requests['error']:
             logger.error(r.text)
        project_name = "%s/%s" % (self.owner, self.repo)

        # Check if we've already notified on this pull request.
        project_state = PullRequestNotifier.state.setdefault(
            project_name,
            {"newest_request": 0,
             "newest_comment_id": 0,
             },
        )
        newest_request = project_state['newest_request']
        newest_comment_id = project_state['newest_comment_id']
        notifiable_requests = []
        notifiable_comments = []
        for pr in pull_requests:
            req_number = int(pr['number'])
            if req_number > newest_request:
                notifiable_requests.append(pr)
                project_state['newest_request'] = req_number
                PullRequestNotifier.save_state()

            # Check for new pull request comments
            comments = self.get_comments(req_number)
            latest_comment_in_query = 0
            for comment in comments:
                if comment['id'] > newest_comment_id:
                    if comment['id'] > latest_comment_in_query:
                        latest_comment_in_query = comment['id']
                    comment['number'] = req_number
                    notifiable_comments.append(comment)
                    project_state['newest_comment_id'] = comment['id']
                    PullRequestNotifier.save_state()
            if latest_comment_in_query > 0:
                project_state['newest_comment_id'] = latest_comment_in_query
                PullRequestNotifier.save_state()

        return notifiable_requests, notifiable_comments


class PullBot(irc.IRCClient):
    def _get_nickname(self):
        return self.factory.nickname
    nickname = property(_get_nickname)

    def connectionLost(self, reason):
        logger.error("Connection Lost")
        if self.lc:
            self.lc.stop()

    def signedOn(self):
        for channel in self.factory.channels:
            self.join(channel)
        logger.info("Signed on as %s." % (self.factory.nickname,))
        self.lc = task.LoopingCall(self.query)
        self.lc.start(QUERY_FREQUENCY)

    def joined(self, channel):
        logger.info("Joined %s." % (channel,))

    def query(self):
        for notifier in self.factory.notifiers:
            try:
                pull_requests, comments = notifier.query()
            except Exception as inst:
                logger.error(inst)
                continue

            for pr in pull_requests:
                message = ("\x035pull request #%(number)s:"
                           "\x032 %(html_url)s -\x033 %(title)s") % pr
                logger.info(message)
                for channel in self.factory.channels:
                    self.msg(channel, str(message))

            for comment in comments:
                url = comment['_links']['html']['href']
                comment['html_url'] = url
                message = ("\x035PR Comment #%(number)s:"
                           "\x032 %(html_url)s") % comment
                logger.info(message)
                for channel in self.factory.channels:
                    self.msg(channel, str(message))


class PullBotFactory(protocol.ReconnectingClientFactory):
    protocol = PullBot

    def __init__(self, channels, token, nickname='PullBot'):
        self.token = token
        self.channels = channels
        self.nickname = nickname
        self.maxDelay = RECONNECT_DELAY

        self.notifiers = []
        for repo in REPOS:
            self.notifiers.append(PullRequestNotifier(repo[0],
                                                      repo[1],
                                                      self.token))

    def clientConnectionLost(self, connector, reason):
        logger.error("Lost connection (%s), reconnecting." % (reason,))
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        logger.error("Could not connect: %s" % (reason,))


if __name__ == "__main__":
    usage = ("usage: %prog [options]"
             "\nSee pullbot.py for additional configuration values.")
    parser = OptionParser(usage)
    parser.add_option("-s", "--server", dest="server",
                      help="The IRC Server", metavar="SERVER", default=HOST)
    parser.add_option("-p", "--port", dest="port",
                      help="The Port", metavar="PORT", default=PORT)
    parser.add_option("-n", "--name", dest="nickname",
                      help="Bot Name", metavar="NAME", default=NICKNAME)
    parser.add_option("-c", "--channels", dest="channels",
                      help="Channels (comma-separated list)", metavar="CHAN",
                      default=CHANNELS)
    parser.add_option("-t", "--token", dest="token",
                      help="Github API Token", metavar="TOKEN",
                      default=API_TOKEN)
    (options, args) = parser.parse_args()

    pullbot = PullBotFactory(options.channels,
                             nickname=options.nickname,
                             token=options.token, )

    reactor.connectTCP(options.server, options.port, pullbot)

    reactor.run()
