"""What else the device considered, and what has been liked.

"It played the wrong thing and I cannot fix it without rephrasing" is the
commonest complaint about voice media. The candidate set the queue was chosen
from is right there in the player, and until ovos-media 2.2.0a1 nothing could
read it back. Switching to another candidate is deliberately not a new verb:
it is an ordinary play request with the chosen entry.

Both replies are `{"entries": [...]}`, read from `handle_disambiguation_query`
and `handle_likes_query` in the shipped player rather than from the spec.
"""
from ovos_utils.fakebus import FakeBus

from ovos_webui import media


def _answering(topic, data):
    bus = FakeBus()
    bus.on(topic, lambda m: bus.emit(m.response(data)))
    return bus


ENTRY = {"title": "A song", "artist": "Someone", "uri": "file:///a.mp3",
         "image": "http://x/i.png", "match_confidence": 90,
         "media_type": 2, "playback": 2}


class TestWhatElseMatched:
    def test_the_candidates_come_back_in_the_order_the_device_ranked_them(self):
        bus = _answering("ovos.common_play.disambiguation", {"entries": [
            dict(ENTRY, title="Best", match_confidence=90),
            dict(ENTRY, title="Second", match_confidence=60)]})
        result = media.candidates(bus)
        assert result["ok"] is True
        assert [c["title"] for c in result["entries"]] == ["Best", "Second"]

    def test_an_entry_without_a_uri_is_dropped(self):
        """Playing one is an ordinary play request carrying its uri, so an
        entry with nothing to play is a row that cannot do anything."""
        bus = _answering("ovos.common_play.disambiguation", {"entries": [
            dict(ENTRY, title="Playable"),
            {"title": "No uri", "match_confidence": 50}]})
        assert [c["title"] for c in media.candidates(bus)["entries"]] == ["Playable"]

    def test_nothing_requested_yet_is_an_empty_list_not_an_error(self):
        bus = _answering("ovos.common_play.disambiguation", {"entries": []})
        result = media.candidates(bus)
        assert result["ok"] is True
        assert result["entries"] == []

    def test_a_player_too_old_to_be_asked_says_so(self):
        """ovos-media before 2.2.0a1 binds neither query, and that is not the
        same as a device that considered nothing."""
        result = media.candidates(FakeBus())
        assert result["ok"] is False
        assert result["entries"] == []

    def test_playing_a_candidate_is_an_ordinary_play_request(self):
        """No new verb: the player already knows how to play an entry."""
        bus, seen = FakeBus(), []
        bus.on("ovos.common_play.play", lambda m: seen.append(m.data))
        assert media.play_entry(bus, ENTRY)["ok"] is True
        assert seen and seen[0]["media"]["uri"] == "file:///a.mp3"

    def test_an_entry_that_is_not_a_media_entry_never_reaches_the_bus(self):
        for bad in (None, "a song", {}, {"title": "no uri"}, []):
            bus, seen = FakeBus(), []
            bus.on("ovos.common_play.play", lambda m: seen.append(m.data))
            assert media.play_entry(bus, bad)["ok"] is False, bad
            assert seen == [], bad


class TestWhatThePlayerWillAccept:
    """The filter mirrors `ovos_media.bus.schemas._is_valid_media`, and every
    candidate from an extractor-backed provider -- youtube, spotify, tunein --
    arrives with no `uri` at all. A uri-only filter would silently hide
    exactly the candidates most people get, with the suite still green.
    """

    STREAM = {"title": "From a provider", "extractor_id": "youtube",
              "stream": "https://example.invalid/watch", "match_confidence": 80}

    def test_an_extractor_entry_with_a_stream_is_offered(self):
        bus = _answering("ovos.common_play.disambiguation",
                         {"entries": [self.STREAM]})
        assert [e["title"] for e in media.candidates(bus)["entries"]] == \
            ["From a provider"]

    def test_an_extractor_entry_without_a_stream_is_not(self):
        bus = _answering("ovos.common_play.disambiguation",
                         {"entries": [dict(self.STREAM, stream="")]})
        assert media.candidates(bus)["entries"] == []

    def test_a_playlist_entry_is_offered(self):
        bus = _answering("ovos.common_play.disambiguation", {"entries": [
            {"title": "An album", "playlist": [dict(ENTRY)]}]})
        assert [e["title"] for e in media.candidates(bus)["entries"]] == ["An album"]

    def test_an_empty_playlist_is_not(self):
        bus = _answering("ovos.common_play.disambiguation", {"entries": [
            {"title": "Nothing in it", "playlist": []},
            {"title": "Not a list", "playlist": "a, b"}]})
        assert media.candidates(bus)["entries"] == []

    def test_a_playlist_beats_a_malformed_uri(self):
        """The player's precedence: a truthy playlist decides the shape and
        `uri` is never consulted, so refusing on the uri would hide a row the
        player would happily play."""
        bus = _answering("ovos.common_play.disambiguation", {"entries": [
            {"title": "Album", "playlist": [dict(ENTRY)], "uri": 12345}]})
        assert [e["title"] for e in media.candidates(bus)["entries"]] == ["Album"]

    def test_a_uri_that_is_not_a_string_is_refused(self):
        for bad in (12345, [], {}, ""):
            bus = _answering("ovos.common_play.disambiguation",
                             {"entries": [{"title": "Bad", "uri": bad}]})
            assert media.candidates(bus)["entries"] == [], bad

    def test_each_shape_can_be_played(self):
        for entry in (self.STREAM, {"title": "Album", "playlist": [dict(ENTRY)]},
                      ENTRY):
            bus, seen = FakeBus(), []
            bus.on("ovos.common_play.play", lambda m: seen.append(m.data))
            assert media.play_entry(bus, entry)["ok"] is True, entry
            assert seen, entry


class TestWhatHasBeenLiked:
    def test_the_liked_entries_come_back(self):
        bus = _answering("ovos.common_play.likes",
                         {"entries": [dict(ENTRY, title="Liked")]})
        result = media.likes(bus)
        assert result["ok"] is True
        assert [e["title"] for e in result["entries"]] == ["Liked"]

    def test_nothing_liked_yet_is_an_empty_list(self):
        bus = _answering("ovos.common_play.likes", {"entries": []})
        assert media.likes(bus) == {"ok": True, "entries": []}

    def test_a_player_too_old_to_be_asked_says_so(self):
        result = media.likes(FakeBus())
        assert result["ok"] is False


class TestPickingKeepsTheRest:
    """A play request's `disambiguation` is the whole candidate set for that
    request, and the player replaces what it holds with it. Sending only the
    picked entry tells the device that one entry was everything it found, and
    the next pick has nothing to choose from.
    """

    OTHERS = [dict(ENTRY, title="First", uri="file:///1.mp3"),
              dict(ENTRY, title="Second", uri="file:///2.mp3"),
              dict(ENTRY, title="Third", uri="file:///3.mp3")]

    def _sent(self, entry, among):
        bus, seen = FakeBus(), []
        bus.on("ovos.common_play.play", lambda m: seen.append(m.data))
        assert media.play_entry(bus, entry, among)["ok"] is True
        return seen[0]

    def test_the_whole_set_travels_with_the_pick(self):
        data = self._sent(self.OTHERS[1], self.OTHERS)
        assert data["media"]["title"] == "Second"
        assert [e["title"] for e in data["disambiguation"]] == \
            ["First", "Second", "Third"], data["disambiguation"]

    def test_a_pick_from_nowhere_still_plays(self):
        """Nothing to preserve, so nothing is claimed: `disambiguation`
        defaults to the played entry inside the player anyway."""
        data = self._sent(ENTRY, [])
        assert "disambiguation" not in data

    def test_an_entry_missing_from_its_own_set_is_added_to_it(self):
        data = self._sent(ENTRY, self.OTHERS)
        assert data["disambiguation"][0]["uri"] == ENTRY["uri"]
        assert len(data["disambiguation"]) == 4

    def test_an_unplayable_neighbour_is_not_carried_along(self):
        """The set the device keeps must not gain a row it would refuse."""
        data = self._sent(self.OTHERS[0],
                          self.OTHERS + [{"title": "No uri"}])
        assert all(e.get("uri") for e in data["disambiguation"])
        assert len(data["disambiguation"]) == 3
