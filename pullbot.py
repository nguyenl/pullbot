import sys
from twisted.words.protocols import irc
from twisted.internet import protocol, reactor


NICKNAME = 'PullBot'
HOST = 'irc.fisa.halc'
PORT = 6667


class PullBot(irc.IRCClient):
    def _get_nickname(self):
        return self.factory.nickname
    nickname = property(_get_nickname)

    def signedOn(self):
        self.join(self.factory.channel)
        print "Signed on as %s." % (self.nickname,)

    def joined(self, channel):
        print "Joined %s." % (channel,)


class PullBotFactory(protocol.ClientFactory):
    protocol = PullBot

    def __init__(self, channel, nickname='PullBot'):
        self.channel = channel
        self.nickname = nickname

    def clientConnectionLost(self, connector, reason):
        print "Lost connection (%s), reconnecting." % (reason,)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print "Could not connect: %s" % (reason,)


if __name__ == "__main__":
    chan = sys.argv[1]
    reactor.connectTCP(HOST, PORT, PullBotFactory('#' + chan,
                                                  nickname=NICKNAME))
    reactor.run()
