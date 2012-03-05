import sys
from twisted.words.protocols import irc
from twisted.internet import protocol, reactor, task
from twisted.internet.protocol import ReconnectingClientFactory
from urlparse import urljoin
from optparse import OptionParser
import requests


# Default Configuration
NICKNAME = 'PullBot'
HOST =  'irc.fisa'
PORT = 6667
RECONNECT_DELAY = 60
CHANNELS = ("#botwars",)
QUERY_FREQUENCY = 60  # Seconds between github queries.
USERNAME = "nguyenl"
API_TOKEN = "d0eb99b8104a6f1bf3c6f0d1f90dce47" # The github API token to authenticate with.


# The github repos to watch. Each tuple contains the owner and repository name.
REPOS = (
    ('navcanada', 'cfps'),
    )


class PullRequestNotifier:
    '''
    Checks Github for new Pull Requests and notifies any objects that
    are interested.
    '''
    gh_url = "https://www.github.com/api/v2/json/pulls/"

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
        
    def query(self, state="open"):
        '''
        Query github for opened pull requests.
        '''
        query_url = urljoin(self.url + "/", state)
        r = requests.get(query_url, auth=(self.username + "/token", self.token))
        print r.text


class PullBot(irc.IRCClient):
    def _get_nickname(self):
        return self.factory.nickname
    nickname = property(_get_nickname)

    def connectionLost(self, reason):
        print "Connection Lost"
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
        print "Query Made"

class PullBotFactory(protocol.ReconnectingClientFactory):
    protocol = PullBot

    def __init__(self, channels, username, token, nickname='PullBot'):
        self.username = username
        self.token = token
        self.channels = channels
        self.nickname = nickname
        self.maxDelay = RECONNECT_DELAY

    def clientConnectionLost(self, connector, reason):
        print "Lost connection (%s), reconnecting." % (reason,)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print "Could not connect: %s" % (reason,)


if __name__ == "__main__":
    prn = PullRequestNotifier("navcanada", "cfps", "nguyenl", "d0eb99b8104a6f1bf3c6f0d1f90dce47")
    prn.query()
    exit()
    
    usage = ("usage: %prog [options] GITHUB_USERNAME GITHUB_PASSWORD"
             "\nSee pullbot.py for additional configuration values.")
    parser = OptionParser(usage)
    parser.add_option("-s", "--server", dest="server",
                      help="The IRC Server", metavar="SERVER", default=HOST)
    parser.add_option("-p", "--port", dest="port",
                      help="The Port", metavar="PORT", default=PORT)
    parser.add_option("-n", "--name", dest="nickname",
                      help="Bot Name", metavar="NAME", default=NICKNAME)
    parser.add_option("-c", "--channels", dest="channels",
                      help="Channels (comma-separated list)", metavar="CHAN", default=CHANNELS)
    parser.add_option("-u", "--username", dest="username",
                      help="Github Username", metavar="USERNAME", default=USERNAME)
    parser.add_option("-t", "--token", dest="token",
                      help="Github API Token", metavar="TOKEN", default=API_TOKEN)
    (options, args) = parser.parse_args()

    chan = sys.argv[1]
    pullbot = PullBotFactory(options.channels,
                             nickname=options.nickname,
                             username=options.username,
                             github_token=options.token,
                             )

    reactor.connectTCP(options.server,
                       options.port,
                       pullbot)
    reactor.run()
