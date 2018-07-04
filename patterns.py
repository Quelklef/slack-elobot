import re

# Regexes are suffixed with -REGEX or -REGEX_G.
# -REGEX regexes don't contain capture groups, and
# -REGEX_G regexes do.

# re.compile is not used because it will not make much of a performance
# difference with this few regexes, and because keeping all regexes as
# strings allows for easy composition via string manipulation.

HANDLE_REGEX   = '<@[A-z0-9]*>'
HANDLE_REGEX_G = '<@([A-z0-9]*)>'

# We allow for an optional backdoor that allows any user to run any command
# Good for debugging
# Default to false; we later pull a value for it from the config.
BACKDOOR_ENABLED = False
BACKDOOR_REGEX_G    = f'As {HANDLE_REGEX_G}:? (.*)'

PLAYED_TERMS = '''crushed
rekt
beat
whooped
destroyed
smashed
demolished
decapitated
smothered
creamed
loss to
tied
played'''.split('\n')
PLAYED_REGEX = f'(?:{"|".join(PLAYED_TERMS)})'

PLAYER_REGEX   = f'(?:I|me|{HANDLE_REGEX})'
PLAYER_REGEX_G = f'(I|me|{HANDLE_REGEX})'
ME_REGEX       = f'(?:I|me)'
TEAM_REGEX_G   = f'({PLAYER_REGEX}(?:,? (?:and )?{PLAYER_REGEX})*)'  # Captures the entire team
GAME_REGEX_G   = f'{TEAM_REGEX_G} {PLAYED_REGEX} {TEAM_REGEX_G} (\d+) ?- ?(\d+)'

def parse_team(team_text, me_handle):
    m = re.match(TEAM_REGEX_G, team_text, re.IGNORECASE)
    if not m:
        raise ValueError("Given text must match TEAM_REGEX_G")
    team_text, = m.groups()
    team = re.findall(PLAYER_REGEX_G, team_text, re.IGNORECASE)

    result = []
    for player in team:
        if re.match(ME_REGEX, player, re.IGNORECASE):
            result.append(me_handle)
        else:
            result.append(re.match(HANDLE_REGEX_G, player, re.IGNORECASE).groups()[0])
    return result

def parse_game(game_text, me_handle):
    m = re.match(GAME_REGEX_G, game_text, re.IGNORECASE)
    if not m:
        raise ValueError("Given text must match GAME_REGEX_G")
    team1_text, team2_text, team1_score, team2_score = m.groups()
    return (
        parse_team(team1_text, me_handle),
        parse_team(team2_text, me_handle),
        int(team1_score),
        int(team2_score),
    )

CONFIRM_REGEX_G   = 'Confirm (\d+)'
CONFIRM_ALL_REGEX = 'Confirm all'
LEADERBOARD_REGEX = 'Print leaderboard'
UNCONFIRMED_REGEX = 'Print unconfirmed'