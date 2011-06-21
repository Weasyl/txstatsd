import re
import time
import logging

from twisted.python import log


SPACES = re.compile("\s+")
SLASHES = re.compile("\/+")
NON_ALNUM = re.compile("[^a-zA-Z_\-0-9\.]")
RATE = re.compile("^@([\d\.]+)")
COUNTERS_MESSAGE = (
    "stats.%(key)s %(value)s %(timestamp)s\n"
    "stats_counts.%(key)s %(count)s %(timestamp)s\n")
TIMERS_MESSAGE = (
    "stats.timers.%(key)s.mean %(mean)s %(timestamp)s\n"
    "stats.timers.%(key)s.upper %(upper)s %(timestamp)s\n"
    "stats.timers.%(key)s.upper_%(percent)s %(threshold_upper)s %(timestamp)s\n"
    "stats.timers.%(key)s.lower %(lower)s %(timestamp)s\n"
    "stats.timers.%(key)s.count %(count)s %(timestamp)s\n")


def normalize_key(key):
    """
    Normalize a key that might contain spaces, forward-slashes and other
    special characters into something that is acceptable by graphite.
    """
    key = SPACES.sub("_", key)
    key = SLASHES.sub("-", key)
    key = NON_ALNUM.sub("", key)
    return key


class MessageProcessor(object):

    def __init__(self, time_function=time.time):
        self.time_function = time_function
        self.timers = {}
        self.counters = {}

    def fail(self, message):
        """Log and discard malformed message."""
        log.msg("Bad line: %r" % message, logLevel=logging.DEBUG)

    def process(self, message):
        """
        Process a single entry, adding it to either C{counters} or C{timers}
        depending on which kind of message it is.
        """
        if not ":" in message:
            return self.fail(message)

        key, data = message.strip().split(":", 1)
        if not "|" in data:
            return self.fail(message)

        fields = data.split("|")
        if len(fields) < 2 or len(fields) > 3 :
            return self.fail(message)

        try:
            value = int(fields[0])
        except (TypeError, ValueError):
            return self.fail(message)

        key = normalize_key(key)

        if fields[1] == "c":
            rate = 1
            if len(fields) == 3:
                match = RATE.match(fields[2])
                if match is None:
                    return self.fail(message)
                rate = match.group(1)
            if key not in self.counters:
                self.counters[key] = 0
            self.counters[key] += value * (1 / float(rate))
        elif fields[1] == "ms":
            if key not in self.timers:
                self.timers[key] = []
            self.timers[key].append(value)
        else:
            return self.fail(message)

    def flush(self, interval=10000, percent=90):
        """
        Flush all queued stats, computing a normalized count based on
        C{interval} and mean timings based on C{threshold}.
        """
        messages = []
        num_stats = 0
        interval = interval / 1000
        timestamp = int(self.time_function())

        for key, count in self.counters.iteritems():
            self.counters[key] = 0

            value = count / interval
            messages.append(COUNTERS_MESSAGE % {
                "key": key,
                "value": value,
                "count": count,
                "timestamp": timestamp})
            num_stats += 1

        threshold_value = ((100 - percent) / 100.0)
        for key, timers in self.timers.iteritems():
            count = len(timers)
            if count > 0:
                self.timers[key] = []

                timers.sort()
                lower = timers[0]
                upper = timers[-1]
                count = len(timers)

                mean = lower
                threshold_upper = upper

                if count > 1:
                    index = count - int(round(threshold_value * count))
                    timers = timers[:index]
                    threshold_upper = timers[-1]
                    mean = sum(timers) / index

                num_stats += 1

                messages.append(TIMERS_MESSAGE % {
                    "key": key,
                    "mean": mean,
                    "upper": upper,
                    "percent": percent,
                    "threshold_upper": threshold_upper,
                    "lower": lower,
                    "count": count,
                    "timestamp": timestamp})

        messages.append("statsd.numStats %s %s" % (num_stats, timestamp))
        return messages
