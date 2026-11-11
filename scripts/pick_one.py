#! /usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = ["prompt_toolkit"]
# ///
"""
Anime picker backed by a Trello board.

  picker.py                        type choices (autocompletes from the board), blank line to roll
  picker.py "Frieren" "One Piece"  seed choices from the command line
  picker.py --dry-run              roll normally but don't write anything to Trello
  picker.py --refresh-eps          re-fetch episode length / count from AniList (normally cached)

Needs TRELLO_KEY and TRELLO_TOKEN in the environment.
Autocomplete: with `pip install prompt_toolkit` suggestions pop up as you type;
without it, press Tab to complete (readline).

Stats live in a comment on each card starting with "PY:". Slop / Lslop stats live in
"PY:Slop" / "PY:Lslop" comments on the Slop Count card. You can hand-edit the numbers
in those comments (e.g. fix ep_len or total_eps) and the script will use your edits.
"""

import time, random, argparse, os, sys, json, re, datetime
import urllib.request, urllib.parse, urllib.error

# ================================ CONFIG ================================
BOARD_ID = os.environ.get("TRELLO_BOARD", "688ffb0448f639e7f0dd2ea3")   # Anime Watch List

# Weight of each normal choice:
#   weight   = votes * (BASE_WEIGHT + momentum + progress) * reroll_boost
#   momentum = MOMENTUM_WEIGHT * (1 + d + d^2 + ... + d^(s-1))     s = times submitted since it last won
#              -> pity that builds with every miss and levels off at MOMENTUM_WEIGHT / (1 - d)
#   progress = PROGRESS_WEIGHT * (watched / total_eps) * (REFERENCE_EP_LEN / ep_len)
#              -> closer to done = bigger, shorter episodes = bigger, 0 if total_eps is unknown
# A brand-new card has s = 0 and watched = 0, so it just gets BASE_WEIGHT.
BASE_WEIGHT      = 1.0
MOMENTUM_WEIGHT  = 0.5    # pity added by the first miss
MOMENTUM_DECAY   = 0.8    # d, between 0 and 1. Max pity = 0.5 / (1 - 0.8) = 2.5
PROGRESS_WEIGHT  = 1.5    # bonus for a finished-or-nearly-finished REFERENCE_EP_LEN-minute show
REFERENCE_EP_LEN = 24.0   # minutes
DEFAULT_EP_LEN   = 24.0   # used when the episode length is unknown
MIN_EP_LEN       = 12.0   # floor: short episodes can at most double the progress bonus

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
DATA_CARD   = "Slop Count"            # Slop / Lslop stats are stored on this card

# Episodes credited to the winner (you're asked; this is the default if you just hit Enter)
EPISODES_BY_LIST = {"One Episode": 1, "Three Episodes": 3, "Logan's Harem": 1}
DEFAULT_EPISODES = 1
ASK_EPISODES     = True

LOOKUP_ANILIST = True     # fill in ep_len / total_eps from AniList the first time a card is seen (then cached)
SHOW_ODDS      = True
SENTINEL       = "PY:"
ROLL_PAUSE, RESULT_PAUSE, REROLL_PAUSE = 0.6, 2, 3
PROFILE_DIR = os.path.join(os.path.expanduser("~"), "utilities", "profiles")
FALLBACK_LOSER_MESSAGES = ["is out.", "has been eliminated.", "didn't make it."]
# ========================================================================

API = "https://api.trello.com/1/"
KEY, TOKEN = os.environ.get("TRELLO_KEY"), os.environ.get("TRELLO_TOKEN")
ONLINE = bool(KEY and TOKEN)
DRY_RUN = False
REFRESH_EPS = False
ME = None
ANIME_FIELDS = ["watched", "total_eps", "ep_len", "submitted_since_roll", "wins", "last_rolled"]
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

def loadBoard():
    global ONLINE, ME
    board = Board()
    if not ONLINE:
        print("TRELLO_KEY / TRELLO_TOKEN not set: running offline (no autocomplete, nothing saved).")
        return board
    try:
        ME = trello("GET", "members/me", fields="id")["id"]
        lists = {l["id"]: l["name"] for l in trello("GET", "boards/%s/lists" % BOARD_ID, fields="name")}
        cards = trello("GET", "boards/%s/cards" % BOARD_ID, fields="name,idList")
    except Exception as e:
        print("Couldn't reach Trello (%s): running offline (no autocomplete, nothing saved)." % e)
        ONLINE = False
        return board
    for c in cards:
        card = {"id": c["id"], "name": c["name"].strip(), "list": lists.get(c["idList"], "")}
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

def anilistLookup(title):
    """(ep_len, total_eps, matched title); (None, None, None) if no match; None on network error."""
    query = "query($s:String){Media(search:$s,type:ANIME){episodes duration title{english romaji}}}"
    body = json.dumps({"query": query, "variables": {"s": title}}).encode()
    req = urllib.request.Request("https://graphql.anilist.co", data=body,
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            media = json.load(resp)["data"]["Media"]
    except urllib.error.HTTPError as e:
        return (None, None, None) if e.code == 404 else None
    except Exception:
        return None
    if not media:
        return (None, None, None)
    return media.get("duration"), media.get("episodes"), media["title"].get("english") or media["title"].get("romaji")


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
        # ep_len / total_eps are cached in the card's PY: comment. AniList is only asked when a card
        # has never been looked up (or the last lookup hit a network error), or with --refresh-eps.
        # "?" means "looked up, not found / still airing" and is cached too.
        fields = ("ep_len", "total_eps")
        cached = all(k in st and st[k] != "retry" for k in fields)
        if LOOKUP_ANILIST and (REFRESH_EPS or not cached):
            info = anilistLookup(choice.name)
            if info is None:
                for k in fields:
                    if num(st, k) is None:
                        st[k] = "retry"
                print('  AniList unreachable for "%s", will try again next run' % choice.name)
            else:
                for k, v in zip(fields, info[:2]):
                    if REFRESH_EPS or num(st, k) is None:
                        st[k] = v
                if info[2]:
                    print('  AniList: "%s" -> "%s", %s eps x %s min' % (choice.name, info[2], fmt(info[1]), fmt(info[0])))
                else:
                    print('  AniList: no match for "%s" (edit ep_len / total_eps in its PY: comment)' % choice.name)
        for k in fields:
            st.setdefault(k, None)
    computeWeight(choice)

def computeWeight(choice):
    st = choice.stats
    s = max(num(st, "submitted_since_roll", 0), 0)
    d = MOMENTUM_DECAY
    choice.momentum = MOMENTUM_WEIGHT * (s if d >= 1 else (1 - d ** s) / (1 - d))
    choice.progress = 0.0
    total, watched = num(st, "total_eps"), num(st, "watched", 0)
    if choice.kind == "anime" and total and total > 0:
        epLen = max(num(st, "ep_len") or DEFAULT_EP_LEN, MIN_EP_LEN)
        choice.progress = PROGRESS_WEIGHT * min(watched / total, 1.0) * REFERENCE_EP_LEN / epLen
    choice.weight = max(BASE_WEIGHT + choice.momentum + choice.progress, 1e-6)

def slopPool(board, lists):
    weights = {k.lower(): w for k, w in lists.items()}
    return [(c, weights[c["list"].lower()]) for c in board.cards if c["list"].lower() in weights]

def buildChoices(entries, board):
    choices, byName = [], {}
    for name in entries:
        if name not in byName:
            if name in (SLOP_NAME, LSLOP_NAME):
                ch = Choice(name, "slop", board.dataCard, tag=name)
            elif name.lower() in board.byName:
                ch = Choice(name, "anime", board.byName[name.lower()])
            else:
                ch = Choice(name, "unknown")
            byName[name] = ch
            choices.append(ch)
        byName[name].votes += 1
    kept = []
    for ch in choices:
        if ch.kind == "slop" and not slopPool(board, LSLOP_LISTS if ch.name == LSLOP_NAME else SLOP_LISTS):
            print("%s dropped: its lists are empty or missing." % ch.name)
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

def makePrompter(names):
    """Returns (ask function, description of the autocomplete mode in use)."""
    if not sys.stdin.isatty():
        return input, "off (input isn't a terminal)"
    try:
        from prompt_toolkit import prompt as ptPrompt
        from prompt_toolkit.completion import WordCompleter
        completer = WordCompleter(names, ignore_case=True, sentence=True, match_middle=True)
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
    print("Enter your choices (Tab/autocomplete from the board, blank line to roll):")
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
            if len(entries) >= 2:
                return entries
            print("Try again")
            print(entries)
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
    lists = LSLOP_LISTS if slopChoice.name == LSLOP_NAME else SLOP_LISTS
    pool = slopPool(board, lists)
    print("\n%s wins! Digging through the slop bin (%d shows)" % (slopChoice.name, len(pool)))
    dramaticRoll()
    card = weightedPick([c for c, _ in pool], [w for _, w in pool])
    print('\nThe slop bin serves up "%s" (from %s)' % (card["name"], card["list"]))
    for c in choices:
        if c.card and c.card["id"] == card["id"]:
            return c
    pick = Choice(card["name"], "anime", card)
    loadStats(pick, board)
    return pick

def askEpisodes(choice):
    listName = (choice.card or {}).get("list", "").lower()
    default = {k.lower(): v for k, v in EPISODES_BY_LIST.items()}.get(listName, DEFAULT_EPISODES)
    if not ASK_EPISODES or choice.kind == "unknown":
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
    return parser.parse_args()

def pickOne():
    global DRY_RUN
    args = getCmdLineArgs()
    global REFRESH_EPS
    DRY_RUN = args.dry_run
    REFRESH_EPS = args.refresh_eps

    board = loadBoard()
    names = sorted({c["name"] for c in board.cards}, key=str.lower) + [SLOP_NAME, LSLOP_NAME]
    index = {n.lower(): n for n in names}
    ask, mode = makePrompter(names)
    print("Autocomplete: %d shows from the board, %s." % (len(names) - 2, mode))

    entries = [index.get(f.lower(), f) for f in FAIR_ODDS]
    for n in (interpret(a, index) for a in args.choices):
        if n:
            entries.append(n)
    if len(entries) < 2:
        entries = getChoices(entries, ask, index)

    choices = buildChoices(entries, board)
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

    episodes = askEpisodes(watching)
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
    watching.stats["watched"] = num(watching.stats, "watched", 0) + (episodes if watching.kind != "slop" else 0)

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
