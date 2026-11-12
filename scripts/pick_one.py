#!/usr/bin/env -S uv run --script --env-file ${HOME}/utilities/animeList.env
# /// script
# requires-python = ">=3.8"
# dependencies = ["prompt_toolkit"]
# ///
"""
Anime picker backed by a Trello board.

  picker.py                        type choices (autocompletes from the board), blank line to roll
  picker.py "Frieren" "One Piece"  seed choices from the command line
  picker.py --dry-run              roll normally but don't write anything to Trello
  picker.py --again (-a)           roll again with the same choices as last time
  picker.py --refresh-eps          re-fetch episode length / count from AniList (normally cached)

Needs TRELLO_KEY and TRELLO_TOKEN in the environment.
Autocomplete: with `pip install prompt_toolkit` suggestions pop up as you type;
without it, press Tab to complete (readline).

Stats live in a comment on each card starting with "PY:". Slop / Lslop stats live in
"PY:Slop" / "PY:Lslop" comments on the Slop Count card. You can hand-edit the numbers
in those comments (e.g. fix ep_len or total_eps) and the script will use your edits.
"""

import time, random, argparse, os, sys, json, re, datetime, tempfile, getpass
import urllib.request, urllib.parse, urllib.error

# ================================ CONFIG ================================
BOARD_ID = os.environ.get("TRELLO_BOARD", "688ffb0448f639e7f0dd2ea3")   # Anime Watch List

# Weight of each normal choice:
#   weight   = votes * (BASE_WEIGHT + momentum + progress) * reroll_boost
#   momentum = MOMENTUM_WEIGHT * (1 + d + d^2 + ... + d^(s-1))     s = times submitted since it last won
#              -> pity that builds with every miss and levels off at MOMENTUM_WEIGHT / (1 - d)
#   progress = PROGRESS_WEIGHT * (2 * FINISH_SCALE / (FINISH_SCALE + minutes_left) - 1)
#              minutes_left = (total_eps - watched) * ep_len
#              -> little time left (nearly done, or short episodes) = up to +PROGRESS_WEIGHT
#              -> lots of time left (just started, long show)     = down to -PROGRESS_WEIGHT
#              -> exactly FINISH_SCALE minutes left = 0; 0 if total_eps is unknown
# Weight never drops below MIN_WEIGHT, so every choice keeps some chance.
BASE_WEIGHT      = 1.0
MOMENTUM_WEIGHT  = 0.5    # pity added by the first miss
MOMENTUM_DECAY   = 0.8    # d, between 0 and 1. Max pity = 0.5 / (1 - 0.8) = 2.5
PROGRESS_WEIGHT  = 0.75   # biggest boost (nearly done) and biggest penalty (barely started)
FINISH_SCALE     = 120.0  # minutes left where the progress term is neutral (~5 episodes of 24 min)
MIN_WEIGHT       = 0.25
DEFAULT_EP_LEN   = 24.0   # used when the episode length is unknown

FAIR_ODDS = ["One Piece"] # in every roll with 1 vote, +1 per extra submission; chance = its votes / total votes
ALIASES = {"one peice": "One Piece"}   # typed / default-file spellings that mean a board card

ROLL_AGAIN_CHANCE     = 0.25   # chance "roll again" wins once 3 finalists remain (needs 3+ choices)
FINALIST_REROLL_BOOST = 2.0    # finalists' weight multiplier on the reroll

# Slop: a choice you vote for. If it wins, it picks a card from these lists (list name: weight).
SLOP_NAME   = "Slop"
LSLOP_NAME  = "Lslop"
SLOP_LISTS  = {"One Episode": 1, "Three Episodes": 3}
LSLOP_LISTS = {"One Episode": 1, "Three Episodes": 3, "Logan's Harem": 1}
DATA_LIST   = "Trello Data Storing"   # cards here are never offered as choices
DATA_CARD   = "Slop Count"            # Slop / Lslop / category stats are stored on this card

# Categories: every Trello list can be voted for as "List: <name>". If it wins, it picks a random
# card from that list. These lists are never offered (matching ignores case, emoji and punctuation).
CATEGORY_PREFIX = "List: "

# Tags (stub): "tag:<anything>" can be entered as a choice but doesn't roll yet. Reading tags from
# the board isn't built; tagSuggestions() is where those completions would come from.
TAG_PREFIX = "tag:"
EXCLUDED_CATEGORIES = ["Finished", "Gave up -> solo watch", "Trello Data Storing"]

# Episodes credited to the winner (you're asked; this is the default if you just hit Enter)
EPISODES_BY_LIST = {"One Episode": 1, "Three Episodes": 3, "Logan's Harem": 1}
DEFAULT_EPISODES = 1
ASK_EPISODES     = True

LOOKUP_ANILIST = True     # fill in ep_len / total_eps from AniList the first time a card is seen (then cached)

# MyAnimeList: watched / total_eps come from this user's public list when a card matches a MAL entry.
# A card matches by mal_id in its PY: comment, a myanimelist.net/anime/<id> link in its description,
# or a title equal to the MAL title (English or romaji, ignoring case and punctuation). If none of
# those match, you're asked for the MAL link once and it's saved as mal_id ("n" saves mal_id=none,
# which stops the question; edit the comment to change it). "" turns MAL off.
MAL_USER = os.environ.get("MAL_USER", "hello_1995")
# If MAL shows a show as finished, or at JUST_STARTED_EPS episodes or fewer, the MAL count may not be
# where the group is (e.g. watched solo). Then the card's own count is used, and when the show wins
# you're asked what episode you're on.
JUST_STARTED_EPS = 1
SHOW_ODDS      = True
SENTINEL       = "PY:"
ROLL_PAUSE, RESULT_PAUSE, REROLL_PAUSE = 0.6, 2, 3
PROFILE_DIR = os.path.join(os.path.expanduser("~"), "utilities", "profiles")
REPEAT_KEY = "."   # type this at an option prompt to repeat the previous option
LAST_CHOICES_FILE = os.path.join(tempfile.gettempdir(), "pick_one_last_%s.json" % getpass.getuser())   # for --again (/tmp on Linux)
FALLBACK_LOSER_MESSAGES = ["is out.", "has been eliminated.", "didn't make it."]
# ========================================================================

API = "https://api.trello.com/1/"
KEY, TOKEN = os.environ.get("TRELLO_KEY"), os.environ.get("TRELLO_TOKEN")
ONLINE = bool(KEY and TOKEN)
DRY_RUN = False
REFRESH_EPS = False
ME = None
ANIME_FIELDS = ["watched", "total_eps", "ep_len", "submitted_since_roll", "wins", "last_rolled", "mal_id"]
SLOP_FIELDS = ["wins", "submitted_since_roll", "watched", "last_rolled"]


# ------------------------------- Trello ---------------------------------

def trello(method, path, **params):
    params.update(key=KEY, token=TOKEN)
    url = API + path + "?" + urllib.parse.urlencode(params)
    data = b"" if method in ("POST", "PUT") else None
    req = urllib.request.Request(url, data=data, method=method)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)

class Board:
    def __init__(self):
        self.cards = []          # {"id", "name", "list"}
        self.byName = {}
        self.dataCard = None
        self.comments = {}       # card id -> {tag: (action id, stats)}
        self.categories = []     # list names that can be voted for as "List: <name>"

def loadBoard():
    global ONLINE, ME
    board = Board()
    if not ONLINE:
        print("TRELLO_KEY / TRELLO_TOKEN not set: running offline (no autocomplete, nothing saved).")
        return board
    try:
        ME = trello("GET", "members/me", fields="id")["id"]
        lists = {l["id"]: l["name"] for l in trello("GET", "boards/%s/lists" % BOARD_ID, fields="name")}
        cards = trello("GET", "boards/%s/cards" % BOARD_ID, fields="name,idList,desc")
    except Exception as e:
        print("Couldn't reach Trello (%s): running offline (no autocomplete, nothing saved)." % e)
        ONLINE = False
        return board
    excluded = {normName(n) for n in EXCLUDED_CATEGORIES}
    board.categories = [n for n in lists.values() if normName(n) not in excluded and normName(n)]
    for c in cards:
        card = {"id": c["id"], "name": c["name"].strip(), "list": lists.get(c["idList"], ""), "desc": c.get("desc", "")}
        if card["list"].lower() == DATA_LIST.lower():
            if card["name"].lower() == DATA_CARD.lower():
                board.dataCard = card
            continue
        board.cards.append(card)
        board.byName.setdefault(card["name"].lower(), card)
    if board.dataCard is None:
        print('Note: no "%s" card in "%s", so Slop stats won\'t be saved.' % (DATA_CARD, DATA_LIST))
    return board

def parseStats(text):
    stats = {}
    for k, v in re.findall(r"(\w+)\s*=\s*([^|\n]+)", text):
        v = v.strip()
        try:
            stats[k] = float(v) if "." in v else int(v)
        except ValueError:
            stats[k] = v
    return stats

def pyComments(board, cardId):
    """Our newest PY: comment on a card, per tag ('' for anime, 'Slop', 'Lslop')."""
    if cardId not in board.comments:
        found = {}
        for a in trello("GET", "cards/%s/actions" % cardId, filter="commentCard", limit=1000):
            text = a.get("data", {}).get("text", "")
            m = re.match(re.escape(SENTINEL) + r"(\S*)", text)
            if m and a.get("idMemberCreator") == ME and m.group(1) not in found:
                found[m.group(1)] = (a["id"], parseStats(text))
        board.comments[cardId] = found
    return board.comments[cardId]

def fmt(v):
    if v is None:
        return "?"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)

def formatStats(choice):
    fields = SLOP_FIELDS if choice.kind == "slop" else ANIME_FIELDS
    body = " | ".join("%s=%s" % (k, fmt(choice.stats.get(k))) for k in fields)
    return "%s%s %s\n(auto-updated by picker.py)" % (SENTINEL, choice.tag, body)

def saveStats(choice):
    if not choice.card:
        return False
    text = formatStats(choice)
    if DRY_RUN or not ONLINE:
        print("  [dry run] %s: %s" % (choice.card["name"], text.splitlines()[0]))
        return False
    if choice.actionId:
        trello("PUT", "actions/%s" % choice.actionId, text=text)
    else:
        choice.actionId = trello("POST", "cards/%s/actions/comments" % choice.card["id"], text=text)["id"]
    return True


# ------------------------------- AniList --------------------------------

def anilistLookup(title, malId=None):
    """(ep_len, total_eps, matched title); (None, None, None) if no match; None on network error."""
    if malId:
        query = "query($m:Int){Media(idMal:$m,type:ANIME){episodes duration title{english romaji}}}"
        variables = {"m": int(malId)}
    else:
        query = "query($s:String){Media(search:$s,type:ANIME){episodes duration title{english romaji}}}"
        variables = {"s": title}
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request("https://graphql.anilist.co", data=body,
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          "User-Agent": "Mozilla/5.0 (picker.py)"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            media = json.load(resp)["data"]["Media"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return (None, None, None)
        print("  AniList error: HTTP %s %s" % (e.code, e.reason))
        return None
    except Exception as e:
        print("  AniList error: %s" % e)
        return None
    if not media:
        return (None, None, None)
    return media.get("duration"), media.get("episodes"), media["title"].get("english") or media["title"].get("romaji")


# ----------------------------- MyAnimeList ------------------------------

def normTitle(s):
    return re.sub(r"[\W_]+", "", str(s if s is not None else "").lower())   # MAL sends titles like 86 as numbers

def malFetchPage(offset):
    url = "https://myanimelist.net/animelist/%s/load.json?status=7&offset=%d" % (urllib.parse.quote(MAL_USER), offset)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (picker.py)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)

_mal = None
def malList():
    """Whole MAL list (all statuses), loaded once per run: {"byId": {...}, "byTitle": {...}}."""
    global _mal
    if _mal is None:
        _mal = {"byId": {}, "byTitle": {}}
        if MAL_USER:
            try:
                offset = 0
                while True:
                    items = malFetchPage(offset)
                    for it in items:
                        _mal["byId"][int(it["anime_id"])] = it
                        for t in (it.get("anime_title"), it.get("anime_title_eng")):
                            if normTitle(t):
                                _mal["byTitle"].setdefault(normTitle(t), it)
                    if len(items) < 300:
                        break
                    offset += len(items)
                _mal["ok"] = True
                print("  MyAnimeList: loaded %d entries for %s" % (len(_mal["byId"]), MAL_USER))
            except Exception as e:
                print("  couldn't load MyAnimeList for %s (%s), using saved episode counts" % (MAL_USER, e))
    return _mal

def parseMalLink(text):
    m = re.search(r"myanimelist\.net/anime/(\d+)", text or "")
    return int(m.group(1)) if m else None

def askMalLink(choice):
    """Ask for the show's MAL link. Returns an id, "none" (never ask again), or None (skip this time)."""
    while True:
        raw = input('  "%s" isn\'t matched on MyAnimeList. Paste its MAL link '
                    '(Enter = skip, n = never ask): ' % choice.name).strip()
        if not raw:
            return None
        if raw.lower() in ("n", "no", "none", "never"):
            return "none"
        malId = parseMalLink(raw) or (int(raw) if raw.isdigit() else None)
        if malId:
            return malId
        print("  That isn't a link like https://myanimelist.net/anime/52991/Sousou_no_Frieren, try again.")

def malEntry(choice):
    """Find the card's MAL entry. Asks for a link if nothing matches; stores the id in its stats."""
    mal = malList()
    st = choice.stats
    malId = num(st, "mal_id") or parseMalLink((choice.card or {}).get("desc", ""))
    if malId is not None:
        st["mal_id"] = int(malId)
        return mal["byId"].get(int(malId))
    entry = mal["byTitle"].get(normTitle(choice.name))
    if entry or not mal.get("ok") or str(st.get("mal_id", "")).lower() == "none":
        return entry
    answer = askMalLink(choice)
    if answer == "none":
        st["mal_id"] = "none"
    elif answer:
        st["mal_id"] = answer
        choice.newMalId = True          # re-look-up episode length by this id
        if answer not in mal["byId"]:
            print("  (saved, but it isn't on %s's list yet, so episodes come from the card)" % MAL_USER)
        return mal["byId"].get(answer)
    return None


# ------------------------------- Choices --------------------------------

def num(stats, key, default=None):
    v = stats.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else default

class Choice:
    def __init__(self, name, kind, card=None, tag=""):
        self.name, self.kind, self.card, self.tag = name, kind, card, tag   # kind: anime | slop | unknown
        self.votes = 0
        self.stats = {}
        self.actionId = None
        self.fair = name.lower() in {f.lower() for f in FAIR_ODDS}
        self.weight = self.momentum = self.progress = 0.0
        self.p = 0.0
        self.fromMal = False
        self.malEdge = None      # MAL's count when it shows finished / just started
        self.newMalId = False    # MAL link was just entered at the prompt
        self.lists = {}          # for slop / category choices: list name -> weight

def loadStats(choice, board):
    if choice.card and ONLINE:
        try:
            entry = pyComments(board, choice.card["id"]).get(choice.tag)
            if entry:
                choice.actionId, choice.stats = entry[0], dict(entry[1])
        except Exception as e:
            print("  couldn't read stats for %s (%s), using defaults" % (choice.name, e))
    st = choice.stats
    for k in ("watched", "submitted_since_roll", "wins"):
        if num(st, k) is None:
            st[k] = 0
    if choice.kind == "anime":
        entry = malEntry(choice) if MAL_USER else None
        if entry:
            st["mal_id"] = int(entry["anime_id"])
            if entry.get("anime_num_episodes"):
                st["total_eps"] = int(entry["anime_num_episodes"])
            malWatched = int(entry.get("num_watched_episodes") or 0)
            total = num(st, "total_eps")
            if malWatched <= JUST_STARTED_EPS or (total and malWatched >= total):
                choice.malEdge = malWatched      # finished / just started on MAL: ask when it wins
            else:
                choice.fromMal = True
                st["watched"] = malWatched
        # ep_len / total_eps are cached in the card's PY: comment. AniList is only asked when a card
        # has never been looked up (or the last lookup hit a network error), or with --refresh-eps.
        # "?" means "looked up, not found / still airing" and is cached too.
        fields = ("ep_len", "total_eps")
        cached = all(k in st and st[k] != "retry" for k in fields)
        if LOOKUP_ANILIST and (REFRESH_EPS or choice.newMalId or not cached):
            info = anilistLookup(choice.name, num(st, "mal_id"))
            if info is None:
                for k in fields:
                    if num(st, k) is None:
                        st[k] = "retry"
                print('  AniList unreachable for "%s", will try again next run' % choice.name)
            else:
                for k, v in zip(fields, info[:2]):
                    if REFRESH_EPS or choice.newMalId or num(st, k) is None:
                        st[k] = v
                if info[2]:
                    print('  AniList: "%s" -> "%s", %s eps x %s min' % (choice.name, info[2], fmt(info[1]), fmt(info[0])))
                else:
                    print('  AniList: no match for "%s" (edit ep_len / total_eps in its PY: comment)' % choice.name)
        if entry and entry.get("anime_num_episodes"):      # MAL's episode count beats AniList's
            st["total_eps"] = int(entry["anime_num_episodes"])
        for k in fields:
            st.setdefault(k, None)
        st.setdefault("mal_id", None)
    computeWeight(choice)

def computeWeight(choice):
    st = choice.stats
    s = max(num(st, "submitted_since_roll", 0), 0)
    d = MOMENTUM_DECAY
    choice.momentum = MOMENTUM_WEIGHT * (s if d >= 1 else (1 - d ** s) / (1 - d))
    choice.progress = 0.0
    total, watched = num(st, "total_eps"), num(st, "watched", 0)
    if choice.kind == "anime" and total and total > 0:
        epLen = num(st, "ep_len") or DEFAULT_EP_LEN
        minutesLeft = max(total - watched, 0) * epLen
        choice.progress = PROGRESS_WEIGHT * (2 * FINISH_SCALE / (FINISH_SCALE + minutesLeft) - 1)
    choice.weight = max(BASE_WEIGHT + choice.momentum + choice.progress, MIN_WEIGHT)

def normName(s):
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))

def slopPool(board, lists):
    weights = {k.lower(): w for k, w in lists.items()}
    return [(c, weights[c["list"].lower()]) for c in board.cards if c["list"].lower() in weights]

def buildChoices(entries, board):
    choices, byName = [], {}
    for name in entries:
        if name not in byName:
            if name in (SLOP_NAME, LSLOP_NAME):
                ch = Choice(name, "slop", board.dataCard, tag=name)
                ch.lists = LSLOP_LISTS if name == LSLOP_NAME else SLOP_LISTS
            elif name.startswith(CATEGORY_PREFIX):
                listName = name[len(CATEGORY_PREFIX):]
                ch = Choice(name, "slop", board.dataCard, tag="List:" + re.sub(r"\s+", "_", listName))
                ch.lists = {listName: 1}
            elif name.lower() in board.byName:
                ch = Choice(name, "anime", board.byName[name.lower()])
            else:
                ch = Choice(name, "unknown")
            byName[name] = ch
            choices.append(ch)
        byName[name].votes += 1
    kept = []
    for ch in choices:
        if ch.kind == "slop" and not slopPool(board, ch.lists):
            print("%s dropped: no cards in it." % ch.name)
            continue
        kept.append(ch)
    return kept

def computeOdds(choices, boosts):
    N = sum(c.votes for c in choices)
    fair = [c for c in choices if c.fair]
    rest = [c for c in choices if not c.fair]
    fairVotes = sum(c.votes for c in fair)
    fairShare = (fairVotes / N) if rest else 1.0
    for c in fair:
        c.p = fairShare * c.votes / fairVotes
    W = sum(c.votes * c.weight * boosts.get(c.name, 1.0) for c in rest)
    for c in rest:
        c.p = (1 - fairShare) * c.votes * c.weight * boosts.get(c.name, 1.0) / W
    return N

def showOdds(choices, N, boosts):
    print("Odds:")
    width = max(len(c.name) for c in choices)
    for c in sorted(choices, key=lambda c: -c.p):
        if c.fair:
            detail = "fixed at %d in %d votes" % (c.votes, N)
        elif c.kind == "unknown":
            detail = "not on the board"
        else:
            parts = []
            if c.votes > 1:
                parts.append("%d votes" % c.votes)
            parts.append("passed over %s" % fmt(num(c.stats, "submitted_since_roll", 0)))
            if c.kind == "anime":
                parts.append("%s/%s eps" % (fmt(num(c.stats, "watched", 0)), fmt(num(c.stats, "total_eps"))))
            if c.name in boosts:
                parts.append("finalist x%g" % boosts[c.name])
            detail = ", ".join(parts)
        print("  %-*s %5.1f%%   %s" % (width, c.name, 100 * c.p, detail))
    print()


# -------------------------------- Input ---------------------------------

def isTag(name):
    return name.lower().startswith(TAG_PREFIX)

def tagSuggestions(text):
    """Completions for "tag:..." input. Stub: tags aren't read from the board yet."""
    return []

def makePrompter(names):
    """Returns (ask function, description of the autocomplete mode in use)."""
    if not sys.stdin.isatty():
        return input, "off (input isn't a terminal)"
    try:
        from prompt_toolkit import prompt as ptPrompt
        from prompt_toolkit.completion import Completer, Completion, WordCompleter
        words = WordCompleter(names, ignore_case=True, sentence=True, match_middle=True)

        class PickerCompleter(Completer):
            def get_completions(self, document, event):
                text = document.text_before_cursor
                if isTag(text):
                    for t in tagSuggestions(text):
                        yield Completion(t, start_position=-len(text))
                else:
                    yield from words.get_completions(document, event)
        completer = PickerCompleter()
        state = {"broken": False}

        def ask(msg):
            if not state["broken"]:
                try:
                    return ptPrompt(msg.replace("\t", "    "), completer=completer, complete_while_typing=True)
                except (KeyboardInterrupt, EOFError):
                    raise
                except Exception as e:      # e.g. Git Bash / mintty on Windows isn't a real console
                    state["broken"] = True
                    print("\n(autocomplete doesn't work in this terminal: %s. Try Command Prompt, "
                          "PowerShell or Windows Terminal. Partial names still work.)" % type(e).__name__)
            return input(msg)
        return ask, "suggestions pop up as you type"
    except ImportError:
        pass
    try:
        import readline
    except ImportError:
        return input, ("off: prompt_toolkit isn't installed. Run with `uv run picker.py` "
                       "or `pip install prompt_toolkit`")

    def complete(text, state):
        if isTag(text):
            opts = tagSuggestions(text)
            return opts[state] if state < len(opts) else None
        t = text.lower()
        opts = [n for n in names if n.lower().startswith(t)]
        if not opts:
            sub = [n for n in names if t and t in n.lower()]
            opts = sub if len(sub) == 1 else []
        return opts[state] if state < len(opts) else None

    readline.set_completer_delims("")
    readline.set_completer(complete)
    if "libedit" in (readline.__doc__ or ""):
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")
    return input, "press Tab to complete"

def interpret(raw, index, confirm=True):
    """Turn typed text into a board name. Returns None if it should be skipped."""
    t = raw.strip()
    if not t:
        return None
    if isTag(t):
        rest = t[len(TAG_PREFIX):].strip()
        if not rest:
            print("\t  (type something after %s)" % TAG_PREFIX)
            return None
        return TAG_PREFIX + rest
    # One Piece (any capitalization) and its aliases (one peice) always become the same single entry
    aliases = {k.lower(): v for k, v in ALIASES.items()}
    aliases.update({f.lower(): f for f in FAIR_ODDS})
    if t.lower() in aliases:
        t = aliases[t.lower()]
        return index.get(t.lower(), t)
    low = t.lower()
    if low in index:
        return index[low]
    hits = [n for k, n in index.items() if k.startswith(low)] or [n for k, n in index.items() if low in k]
    if len(hits) == 1:
        if not confirm:
            return hits[0]
        ans = input('\t  "%s"? [Y/n] ' % hits[0]).strip().lower()
        if ans in ("", "y", "yes"):
            return hits[0]
    elif len(hits) > 1:
        hits = sorted(hits, key=str.lower)
        for k, h in enumerate(hits[:9]):
            print("\t  %d) %s" % (k + 1, h))
        if len(hits) > 9:
            print("\t  ... and %d more, type more of the name to narrow it down" % (len(hits) - 9))
        ans = input("\t  pick a number (Enter to skip): ").strip()
        if ans.isdigit() and 1 <= int(ans) <= min(len(hits), 9):
            return hits[int(ans) - 1]
        return None
    if ONLINE and confirm:
        print("\t  (not on the Trello board: it can win, but nothing gets saved for it)")
    return t

def getChoices(entries, ask, index):
    print("Enter your choices (autocomplete from the board, \"%s\" repeats the last one, blank line to roll):" % REPEAT_KEY)
    defaultsPath = os.path.join(PROFILE_DIR, "defaultChoices.txt")
    if os.path.exists(defaultsPath):
        for line in getMessages(defaultsPath):
            name = interpret(line, index, confirm=False)
            if name and name.lower() not in {f.lower() for f in FAIR_ODDS}:   # already auto-added
                entries.append(name)
    for i, choice in enumerate(entries):
        print("    option %2d: %s" % (i + 1, choice))
    while True:
        raw = ask("    option %2d: " % (len(entries) + 1))
        if raw.strip() == "":
            if len([e for e in entries if not isTag(e)]) >= 2:
                return entries
            print("Try again")
            print(entries)
            continue
        if raw.strip() == REPEAT_KEY:
            if entries:
                entries.append(entries[-1])
                print("\t  -> %s again" % entries[-1])
            continue
        name = interpret(raw, index)
        if name:
            entries.append(name)


# -------------------------------- Rolling -------------------------------

def getMessages(filename):
    with open(filename, 'r') as f:
        return [line.strip() for line in f]

_loserMessages = []
def nextLoserMessage():
    global _loserMessages
    if not _loserMessages:
        try:
            _loserMessages = [m for m in getMessages(os.path.join(PROFILE_DIR, "loserMessages.txt")) if m]
        except OSError:
            pass
        _loserMessages = _loserMessages or list(FALLBACK_LOSER_MESSAGES)
    return _loserMessages.pop(random.randrange(len(_loserMessages)))

def prettyPrint(labels, votes):
    shown = [l.strip().replace(" ", "_") + ("(x%d)" % votes[l] if votes.get(l, 1) > 1 else "") for l in labels]
    print("Choices: " + " ".join(shown))

def dramaticRoll():
    print("rolling", end="", flush=True)
    for i in range(3):
        time.sleep(ROLL_PAUSE)
        print(".", end="", flush=True)

def eliminate(name, remaining):
    dramaticRoll()
    remaining.remove(name)
    print('\n"%s" %s' % (name, nextLoserMessage()))
    time.sleep(RESULT_PAUSE)

def weightedPick(items, weights):
    if sum(weights) <= 0:
        return random.choice(items)
    return random.choices(items, weights=weights)[0]

def weightedOrder(items, weights):
    """Best-first ordering: repeatedly draw by weight (used for the elimination show)."""
    pool, order = list(zip(items, weights)), []
    while pool:
        i = weightedPick(range(len(pool)), [w for _, w in pool])
        order.append(pool.pop(i)[0])
    return order

def rollRound(choices, boosts):
    """One round. Returns (winner or None for 'roll again', top 3 finalists)."""
    N = computeOdds(choices, boosts)
    if SHOW_ODDS:
        showOdds(choices, N, boosts)
    reroll = len(choices) >= 3 and random.random() < ROLL_AGAIN_CHANCE
    if reroll:
        winner = None
        ranking = weightedOrder(choices, [c.p for c in choices])
    else:
        winner = weightedPick(choices, [c.p for c in choices])
        others = [c for c in choices if c is not winner]
        ranking = [winner] + weightedOrder(others, [c.p for c in others])

    remaining = [c.name for c in choices]
    votes = {c.name: c.votes for c in choices}
    elim = [c.name for c in reversed(ranking)]          # worst first, best last
    prettyPrint(remaining, votes)
    if len(choices) >= 3:
        early, final3 = elim[:-3], elim[-3:]
    else:
        early, final3 = elim[:-1], []
    for name in early:
        eliminate(name, remaining)
        if len(remaining) % 5 == 0:
            print()
            prettyPrint(remaining, votes)
    if final3:
        remaining.append("roll again")
        print()
        prettyPrint(remaining, votes)
        if reroll:
            finalSeq = final3
        else:
            finalSeq = final3[:-1]
            finalSeq.insert(random.randrange(len(finalSeq) + 1), "roll again")
        for name in finalSeq:
            eliminate(name, remaining)
    return winner, ranking[:3]

def slopRoll(slopChoice, board, choices):
    pool = slopPool(board, slopChoice.lists)
    isCategory = slopChoice.name.startswith(CATEGORY_PREFIX)
    if isCategory:
        print("\n%s wins! Picking a show from it (%d shows)" % (slopChoice.name, len(pool)))
    else:
        print("\n%s wins! Digging through the slop bin (%d shows)" % (slopChoice.name, len(pool)))
    dramaticRoll()
    card = weightedPick([c for c, _ in pool], [w for _, w in pool])
    if isCategory:
        print('\nFrom %s: "%s"' % (card["list"], card["name"]))
    else:
        print('\nThe slop bin serves up "%s" (from %s)' % (card["name"], card["list"]))
    for c in choices:
        if c.card and c.card["id"] == card["id"]:
            return c
    pick = Choice(card["name"], "anime", card)
    loadStats(pick, board)
    return pick

def askCurrentEpisode(choice):
    """When MAL shows the winner as finished or just started, ask where the group actually is."""
    if choice.malEdge is None:
        return None
    total = num(choice.stats, "total_eps")
    state = "finished" if total and choice.malEdge >= total else "just started"
    raw = input("MyAnimeList shows %s as %s (%d/%s). What episode are you on? [Enter to skip] "
                % (choice.name, state, choice.malEdge, fmt(total))).strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        print("Not a number, skipping")
        return None

def askEpisodes(choice):
    listName = (choice.card or {}).get("list", "").lower()
    default = {k.lower(): v for k, v in EPISODES_BY_LIST.items()}.get(listName, DEFAULT_EPISODES)
    if not ASK_EPISODES or choice.kind == "unknown" or choice.fromMal:
        return default
    raw = input("Episodes of %s you're watching? [%d] " % (choice.name, default)).strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        print("Not a number, using %d" % default)
        return default


# --------------------------------- Main ---------------------------------

def getCmdLineArgs():
    parser = argparse.ArgumentParser(description='Roll for what to watch, using the Trello board.')
    parser.add_argument('choices', metavar='choices', nargs='*', default=[],
                        help='choices to choose from. Space delimited.')
    parser.add_argument('--dry-run', action='store_true', help="don't write anything to Trello")
    parser.add_argument('--refresh-eps', action='store_true', help='re-fetch episode length / count from AniList')
    parser.add_argument('-a', '--again', action='store_true', help='reuse the choices from the last run')
    return parser.parse_args()

def pickOne():
    global DRY_RUN
    args = getCmdLineArgs()
    global REFRESH_EPS
    DRY_RUN = args.dry_run
    REFRESH_EPS = args.refresh_eps

    board = loadBoard()
    names = (sorted({c["name"] for c in board.cards}, key=str.lower) + [SLOP_NAME, LSLOP_NAME]
             + [CATEGORY_PREFIX + n for n in board.categories])
    index = {n.lower(): n for n in names}
    ask, mode = makePrompter(names)
    print("Autocomplete: %d shows and %d categories from the board, %s." % (len(board.cards), len(board.categories), mode))

    entries = []
    if args.again:
        try:
            with open(LAST_CHOICES_FILE) as f:
                entries = json.load(f)
            print("Same choices as last time: " + ", ".join(entries))
        except (OSError, ValueError):
            print("No previous choices saved yet, enter them below.")
    if not entries:
        entries = [index.get(f.lower(), f) for f in FAIR_ODDS]
    for n in (interpret(a, index) for a in args.choices):
        if n:
            entries.append(n)
    if len([e for e in entries if not isTag(e)]) < 2:
        entries = getChoices(entries, ask, index)
    try:
        with open(LAST_CHOICES_FILE, "w") as f:
            json.dump(entries, f)
    except OSError:
        pass

    choices = buildChoices([e for e in entries if not isTag(e)], board)
    if ONLINE:
        print("Loading stats from Trello...")
    for c in choices:
        loadStats(c, board)
    print()

    boosts = {}
    while True:
        winner, finalists = rollRound(choices, boosts)
        if winner:
            break
        print("Winner: roll again")
        print("rerolling")
        print()
        print()
        time.sleep(REROLL_PAUSE)
        boosts = {f.name: FINALIST_REROLL_BOOST for f in finalists}

    watching = slopRoll(winner, board, choices) if winner.kind == "slop" else winner

    if 'awful' in watching.name and random.randrange(100) == 0:
        print("Alternate Ending")
        print("Winner:", "Seinfeld")
    elif watching is winner:
        print("Winner:", winner.name)
    else:
        print("Winner: %s -> %s" % (winner.name, watching.name))

    currentEp = askCurrentEpisode(watching)
    episodes = askEpisodes(watching)
    if currentEp is not None:                 # on episode N means N - 1 already watched
        watching.stats["watched"] = max(currentEp - 1, 0)
    saveResults(choices, winner, watching, episodes)

def saveResults(choices, winner, watching, episodes):
    today = datetime.date.today().isoformat()
    for c in choices:
        if c is winner:
            c.stats["submitted_since_roll"] = 0
            c.stats["wins"] = num(c.stats, "wins", 0) + 1
            c.stats["last_rolled"] = today
            if c.kind == "slop":
                c.stats["watched"] = num(c.stats, "watched", 0) + episodes
        else:
            c.stats["submitted_since_roll"] = num(c.stats, "submitted_since_roll", 0) + c.votes
    if watching is not winner:     # picked by Slop / Lslop
        watching.stats["submitted_since_roll"] = 0
        watching.stats["wins"] = num(watching.stats, "wins", 0) + 1
        watching.stats["last_rolled"] = today
    if watching.fromMal:
        print("(%s's episode count comes from MyAnimeList, update it there)" % watching.name)
    else:
        watching.stats["watched"] = num(watching.stats, "watched", 0) + episodes

    toSave = choices + ([watching] if watching not in choices else [])
    saved = 0
    for c in toSave:
        try:
            saved += saveStats(c)
        except Exception as e:
            print("  couldn't save %s: %s" % (c.name, e))
    if saved:
        print("Updated stats on %d Trello card comment%s." % (saved, "" if saved == 1 else "s"))
    if watching.kind == "unknown":
        print('("%s" isn\'t on the board, so nothing was saved for it.)' % watching.name)

def main():
    try:
        pickOne()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled, nothing saved.")

if __name__ == '__main__':
    main()
