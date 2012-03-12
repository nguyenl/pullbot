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


# Default Configuration
NICKNAME = 'PullBot'
HOST =  'irc.fisa'
PORT = 6667
RECONNECT_DELAY = 60
CHANNELS = ("#cfps",)
QUERY_FREQUENCY = 300  # Seconds between github queries.
USERNAME = "nguyenl"
API_TOKEN = "" # The github API token to authenticate with.


# The github repos to watch. Each tuple contains the owner and repository name.
REPOS = (
    ('nguyenl', 'pullbot'),
    )


class PullRequestNotifier:
    '''
    Checks Github for new Pull Requests.
    '''
    gh_url = "https://www.github.com/api/v2/json/pulls/"
    state = None
    state_file = "pullbot_state.json"

    # Load the static state.
    try:
        f = open(state_file, 'r')
        state = simplejson.load(f)
        f.close()
    except:
        print "Unable to load state file:", sys.exc_info()[0]
        # If loading the state fails.  Assume no previous state
        # and start fresh.
        state = {}

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

    def __init__(self, name, repo, username, token):
        '''
        Initialize with the given name, repository, username and password.
        '''
        self.name = name
        self.repo = repo
        self.username = username
        self.token = token
        self.url = urljoin(self.gh_url, name)
        self.url = urljoin(self.url + "/", repo)
        self.url = urljoin(self.url + "/", "open")
        
    def query(self):
        '''
        Query github for open pull requests.
        Returns the json provided by the API.
        '''
        r = requests.get(self.url, auth=(self.username + "/token", self.token))
        pull_requests = simplejson.loads(r.text)
        if 'error' in pull_requests and pull_requests['error']:
            print r.text
        project_name = "%s/%s" % (self.name, self.repo)

        # Check if we've already notified on this pull request.
        project_state = PullRequestNotifier.state.setdefault(
            project_name, {"oldest_request": 0})
        oldest_request = project_state['oldest_request']
        notifiable_requests = []
        for pr in pull_requests['pulls']:
            req_number = int(pr['number'])
            if  req_number > oldest_request:
                notifiable_requests.append(pr)
                project_state['oldest_request'] = req_number
                PullRequestNotifier.save_state()
        return notifiable_requests


class PullBot(irc.IRCClient):
    def _get_nickname(self):
        return self.factory.nickname
    nickname = property(_get_nickname)

    def connectionLost(self, reason):
        print "Connection Lost"
        if self.lc:
            self.lc.stop()

    def signedOn(self):
        for channel in self.factory.channels:
            self.join(channel)
        print "Signed on as %s." % (self.factory.nickname,)
        self.lc = task.LoopingCall(self.query)
        self.lc.start(QUERY_FREQUENCY)

    def joined(self, channel):
        print "Joined %s." % (channel,)

    def query(self):
        for notifier in self.factory.notifiers:
            try:
                pull_requests = notifier.query()
            except Exception as inst:
                print inst
                continue
            for pr in pull_requests:
                message = ("\x035pull request #%(number)s:"
                           "\x032 %(html_url)s -\x033 %(title)s") % pr
                for channel in self.factory.channels:
                    self.msg(channel, str(message))


class PullBotFactory(protocol.ReconnectingClientFactory):
    protocol = PullBot

    def __init__(self, channels, username, token, nickname='PullBot'):
        self.username = username
        self.token = token
        self.channels = channels
        self.nickname = nickname
        self.maxDelay = RECONNECT_DELAY

        self.notifiers = []
        for repo in REPOS:
            self.notifiers.append(PullRequestNotifier(repo[0],
                                                      repo[1],
                                                      self.username,
                                                      self.token))

    def clientConnectionLost(self, connector, reason):
        print "Lost connection (%s), reconnecting." % (reason,)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print "Could not connect: %s" % (reason,)


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
    parser.add_option("-u", "--username", dest="username",
                      help="Github Username", metavar="USERNAME",
                      default=USERNAME)
    parser.add_option("-t", "--token", dest="token",
                      help="Github API Token", metavar="TOKEN",
                      default=API_TOKEN)
    (options, args) = parser.parse_args()

    pullbot = PullBotFactory(options.channels,
                             nickname=options.nickname,
                             username=options.username,
                             token=options.token, )

    reactor.connectTCP(options.server, options.port, pullbot)

    reactor.run()
