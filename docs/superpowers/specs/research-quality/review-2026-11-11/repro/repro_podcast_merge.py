"""Two different episodes that share show+title (e.g. the same show title on two feeds) collapse."""
import sys
sys.path.insert(0, "tests/footprint")
from test_podcast_search import wire, ok, pi_episode, KEYS
from clue_api.footprint.podcast_search import find_podcasts

a = pi_episode("Episode 12", "guest Ada", 1700000000, show="The Security Podcast", feed="https://feeds.one/a.xml")
b = pi_episode("Episode 12", "guest Bob", 1600000000, show="The Security Podcast", feed="https://feeds.two/b.xml")
b["enclosureUrl"] = "https://audio.two/ep12.mp3"
caller, _ = wire(ok({"results": []}), ok({"items": [a, b]}), ok({"feeds": [
    {"title": "The Security Podcast", "url": "https://feeds.one/a.xml"},
    {"title": "The Security Podcast", "url": "https://feeds.two/b.xml"}]}))
leads, gaps = find_podcasts(caller, KEYS, ["q"], exa_search=None)
for l in leads:
    print(l.kind, l.title, l.feed_url, l.audio_url, l.published_at, "|", l.description)
