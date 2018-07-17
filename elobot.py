import time
import json
import re
import itertools as it
from datetime import datetime
from dateutil import tz
from collections import defaultdict

from slackclient import SlackClient
from tabulate import tabulate
from peewee import *

from models import *
from util import colloq_listify, colloq_rangify
from patterns import *
from cumulative import observe_match

from_zone = tz.gettz('UTC')
to_zone = tz.gettz('America/Los_Angeles')

class SlackClient(SlackClient):
    def get_name(self, user_handle):
        return self.api_call('users.info', user=user_handle)['user']['profile']['display_name_normalized']

    def get_channel_id(self, channel_name):
        channels = self.api_call('channels.list')

        for channel in channels['channels']:
            if channel['name'] == channel_name:
                return channel['id']

        raise ValueError(f'No channel "{channel_name}"')


class EloBot:
    def __init__(self, slack_client, channel_id, name, min_streak_len):
        self.name = name
        self.slack_client = slack_client
        self.min_streak_len = min_streak_len
        self.channel_id = channel_id

        # TODO: Should map from Player to int. Handles should be dealt with as little as possible
        # Map from handle to elo_cache
        self.elo_cache = defaultdict(lambda: 1500)  # Default ELO is 1500

        self.flush_elo_cache(verbose=False)

    def flush_elo_cache(self, *, verbose=True):
        """Update stored elo_cache. If verbose, tell everyone their ELO change since last flush."""
        for player in Player.select():
            old_elo = self.elo_cache[player.handle]
            self.elo_cache[player.handle] = player.elo
            if verbose:
                elo_delta = player.elo - old_elo
                if elo_delta != 0:
                    self.talk_to(player.handle, f'Your ELO is {player.elo} ({elo_delta:+})')

    def talk(self, message):
        """Send a message to the Slack channel"""
        self.slack_client.api_call('chat.postMessage', channel=self.channel_id, text=message, username=self.name)

    def talk_to(self, handle_s, message):
        """Accepts a single handle or a list of handles."""
        message = message[0].lower() + message[1:]

        if isinstance(handle_s, list) or isinstance(handle_s, set):
            self.talk(colloq_listify(f'<@{handle}>' for handle in set(handle_s)) + ': ' + message)
        else:
            self.talk(f'<@{handle_s}>, {message}')

    def run(self):
        self.slack_client.rtm_connect(auto_reconnect=True)
        while True:
            time.sleep(0.1)
            messages = self.slack_client.rtm_read()
            for message in messages:
                if 'user' in message and 'text' in message and message.get('type') == 'message' and message.get('channel') == self.channel_id:
                    self.handle_message(message)

    def handle_message(self, message):
        text = message['text']
        user_handle = message['user']

        if BACKDOOR_ENABLED and re.match(BACKDOOR_REGEX_G, text, re.IGNORECASE):
            new_user_handle, new_text = re.match(BACKDOOR_REGEX_G, text, re.IGNORECASE).groups()
            return self.handle_message({
                'user': new_user_handle,
                'text': new_text
            })

        if re.match(GAME_REGEX_G, text, re.IGNORECASE):
            team1_handles, team2_handles, scores = parse_game(text, user_handle)

            # Ensure that no player is in the game more than once
            # This is only a porcelain restriction; the code otherwise allows repeat players
            for handle in team1_handles + team2_handles:
                if (team1_handles + team2_handles).count(handle) > 1:
                    self.talk_to(handle, 'Hey! You can\'t be in this game more than once!')
                    return

            self.games(user_handle, team1_handles, team2_handles, scores)
        elif re.match(CONFIRM_REGEX_G, text, re.IGNORECASE):
            match_id, = re.match(CONFIRM_REGEX_G, text, re.IGNORECASE).groups()
            self.confirm(user_handle, match_id, verbose=True)
        elif re.match(CONFIRM_RANGE_REGEX_G, text, re.IGNORECASE):
            lower, upper = re.match(CONFIRM_RANGE_REGEX_G, text, re.IGNORECASE).groups()
            self.confirm_many(user_handle, lower, upper)
        elif re.match(CONFIRM_ALL_REGEX, text, re.IGNORECASE):
            self.confirm_all(user_handle)
        elif re.match(LEADERBOARD_REGEX, text, re.IGNORECASE):
            self.print_leaderboard()
        elif re.match(UNCONFIRMED_REGEX, text, re.IGNORECASE):
             self.print_unconfirmed()

    def get_match(self, match_id):
        """Get a match or say an error and return None"""
        try:
            return Match.select(Match).where(Match.id == match_id).get()
        except DoesNotExist:
            self.talk(f'No match #{match_id}!')

    def games(self, user_handle, team1_handles, team2_handles, scores):
        match = None  # We leak this variable from the loop
        for score in scores:
            team1_score, team2_score = score
            if team1_score >= team2_score:
                winner_handles = team1_handles
                loser_handles = team2_handles
            else:
                winner_handles = team2_handles
                loser_handles = team1_handles

            match = Match.create(winners_score=max(score), losers_score=min(score))
            for winner_handle in winner_handles:
                Participation.create(player=Player.get_or_create(handle=winner_handle)[0], match=match, won=True)
            for loser_handle in loser_handles:
                Participation.create(player=Player.get_or_create(handle=loser_handle)[0], match=match, won=False)
            self.confirm(user_handle, match.id)

        if len(scores) == 1:
            msg = f'Please confirm match #{match.id}.'
        else:
            msg = f'Matches #{match.id - len(scores) + 1}-{match.id} need confirmation.'
        self.talk_to((set(team1_handles) | set(team2_handles)) - {user_handle}, msg)

    def confirm_all(self, user_handle):
        matches = (Match.select()
                        .join(Participation)
                        .where(Participation.player == Player.get(handle=user_handle),
                               Participation.pending == True)
                        .order_by(Match.datetime.asc()))  # Order is significant

        if not matches:
            self.talk_to(user_handle, 'No unconfirmed matches!')
            return

        for match in matches:
            elo_deltas = self.confirm(user_handle, match.id, verbose=False)

        if len(matches) == 1:
            self.talk_to(user_handle, f'Confirmed match #{matches[0].id}')
        else:
            match_ids = map(lambda m: m.id, matches)
            self.talk_to(user_handle, f'Confirmed {len(matches)} matches: {colloq_rangify(match_ids)}!')
        self.flush_elo_cache()

    def confirm_many(self, user_handle, lower, upper):
        actually_confirmed = []
        for match_id in range(int(lower), int(upper) + 1):
            if self.confirm(user_handle, match_id):
                actually_confirmed.append(match_id)

        if len(actually_confirmed) == 0:
            self.talk_to(user_handle, 'No given matches needed confirmation.')
        elif len(actually_confirmed) == 1:
            self.talk_to(user_handle, f'Confirmed match #{actually_confirmed[0]}')
        else:
            self.talk_to(user_handle, f'Confirmed matches {colloq_rangify(actually_confirmed)}.')

        self.flush_elo_cache()

    def confirm(self, user_handle, match_id, *, verbose=False):
        """Return whether a match was confirmed or not."""
        match = self.get_match(match_id)
        if not match: return False

        partics = (Participation
                    .select()
                    .where(Participation.player == Player.get(handle=user_handle),
                           Participation.match == match))

        if not partics:
            if verbose:
                self.talk_to(user_handle, f'Cannot confirm match #{match_id}! You\'re not in it!')
            return False

        if not any(map(lambda p: p.pending, partics)):
            if verbose:
                self.talk_to(user_handle, f'You have already confirmed match #{match_id}!')
            return False

        (Participation.update(pending = False)
            .where(Participation.player == Player.get(handle=user_handle),
                   Participation.match == Match.get(id=match_id))
            .execute())

        if verbose:
            self.talk_to(user_handle, f'Confirmed match #{match_id}!')

        if not match.pending:
            observe_match(match)
            if verbose:
                self.flush_elo_cache()
        return True

    def print_leaderboard(self):
        table = []

        for player in sorted(Player.select(), key=lambda p: -p.elo):
            win_streak = player.streak
            streak_text = f'Won {win_streak} in a row' if win_streak >= self.min_streak_len else '-'
            name = self.slack_client.get_name(player.handle)
            table.append([name, player.elo, player.wins, player.losses, streak_text])

        self.talk('```' + tabulate(table, headers=['Name', 'ELO', 'Wins', 'Losses', 'Streak']) + '```')

    def print_unconfirmed(self):
        table = []

        # TODO: There must be a cleaner way to do this line
        for match in it.islice(filter(lambda m: m.pending, Match.select().order_by(Match.datetime.desc())), 0, 25):
            match_datetime_utc = match.datetime.replace(tzinfo=from_zone)
            match_datetime_pst = match_datetime_utc.astimezone(to_zone)

            def render_participation(pa):
                prefix = '*' if pa.pending else ''
                return prefix + self.slack_client.get_name(pa.player.handle)
            def render_participations(pas):
                return ' '.join(map(render_participation, pas))

            table.append([
                match.id,
                render_participations(Participation
                                        .select()
                                        .where(Participation.match == match,
                                               Participation.won == True)),
                render_participations(Participation
                                        .select()
                                        .where(Participation.match == match,
                                               Participation.won == False)),
                '{} - {}'.format(match.winners_score, match.losers_score),
                match_datetime_pst.strftime('%m/%d/%y %I:%M %p')
            ])

        self.talk('```* Needs to confirm\n' + tabulate(table, headers=['Match', 'Winning team', 'Losing team', 'Score', 'Date']) + '```')

if __name__ == '__main__':
    with open('config.json') as config_data:
        config = json.load(config_data)

    if config.get('debug', False):
        print('Warning: backdoor enabled!')
        BACKDOOR_ENABLED = True

    slack_client = SlackClient(config['slack_token'])
    db.connect()
    create_tables()

    for match in Match.select().where(Match.pending == False):
        observe_match(match)

    bot = EloBot(
        slack_client,
        slack_client.get_channel_id(config['channel']),
        config['bot_name'],
        config['min_streak_length'],
    )

    while True:
        try:
            bot.run()
        except KeyboardInterrupt:
            break
        except:
            import traceback
            print(traceback.format_exc())
            bot.talk("I have encountered an error. Please end my misery :knife:")
