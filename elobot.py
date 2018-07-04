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
from util import mean, show
from patterns import *
from rankee import get_elo, get_wins, get_losses, observe_match, rankees_init

from_zone = tz.gettz('UTC')
to_zone = tz.gettz('America/Los_Angeles')

class SlackClient(SlackClient):
    def __init__(self, *args, **kwargs):
        self.last_ping = 0
        super().__init__(*args, **kwargs)

    def is_bot(self, user_handle):
        return self.api_call('users.info', user=user_handle)['user']['is_bot']

    def get_name(self, user_handle):
        return self.api_call('users.info', user=user_handle)['user']['profile']['display_name_normalized']

    def get_channel_id(self, channel_name):
        channels = self.api_call('channels.list')

        for channel in channels['channels']:
            if channel['name'] == channel_name:
                return channel['id']

        print('Unable to find channel: ' + channel_name)
        quit()

    def ensure_connected(self):
        sleeptime = 0.1
        while not self.server.connected:
            print('Was disconnected, attemping to reconnect...')
            try:
                self.rtm_connect()
            except:  # TODO: Except what
                pass
            time.sleep(sleeptime)
            sleeptime = min(30, sleeptime * 2)  # Exponential back off with a max wait of 30s

    def heartbeat(self):
        """Send a heartbeat if necessary"""
        now = int(time.time())
        if now > self.last_ping + 3:
            self.server.ping()
            self.last_ping = now


class EloBot:
    def __init__(self, slack_client, channel_id, name, min_streak_len):
        self.name = name
        self.slack_client = slack_client
        self.min_streak_len = min_streak_len
        self.channel_id = channel_id

        # Map from handle to elo_cache
        self.elo_cache = defaultdict(int)

        self.flush_elo_cache(verbose=False)
        self.run()

    def flush_elo_cache(self, *, verbose=True):
        """Update stored elo_cache. If verbose, tell everyone their ELO change since last flush."""
        # TODO: Inefficient, just as the other one
        handles = set(map(lambda p: p.handle, Player.select()))
        for handle in handles:
            old_elo = self.elo_cache[handle]
            new_elo = get_elo(handle)
            self.elo_cache[handle] = new_elo
            if verbose:
                self.talk_to(handle, f'Your ELO is {new_elo} ({show(new_elo - old_elo)})')

    def talk(self, message):
        """Send a message to the Slack channel"""
        self.slack_client.api_call('chat.postMessage', channel=self.channel_id, text=message, username=self.name)

    def talk_to(self, handle_s, message):
        """Accepts a single handle or a list of handles."""
        message = message[0].lower() + message[1:]

        if isinstance(handle_s, list) or isinstance(handle_s, set):
            self.talk(', '.join(f'<@{handle}>' for handle in set(handle_s)) + ': ' + message)
        else:
            self.talk(f'<@{handle_s}>, {message}')

    def run(self):
        while True:
            time.sleep(0.1)
            self.slack_client.heartbeat()
            self.slack_client.ensure_connected()

            messages = self.slack_client.rtm_read()
            for message in messages:
                if 'user' in message and message.get('type', False) == 'message' and message.get('channel', False) == self.channel_id and message.get('text', False):
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
            winner_handles, loser_handles, winner_score, loser_score = parse_game(text, user_handle)

            # Ensure that no player is in the game more than once
            # This is only a porcelain restriction; the code otherwise allows repeat players
            for handle in winner_handles + loser_handles:
                if (winner_handles + loser_handles).count(handle) > 1:
                    self.talk_to(handle, 'Hey! You can\'t be in this game more than once!')
                    return

            self.game(user_handle, winner_handles, loser_handles, winner_score, loser_score)
        elif re.match(CONFIRM_REGEX_G, text, re.IGNORECASE):
            match_id, = re.match(CONFIRM_REGEX_G, text, re.IGNORECASE).groups()
            self.confirm(user_handle, match_id, verbose=True)
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
        except Exception:  #TODO
            self.talk(f'No match #{match_id}!')

    def game(self, user_handle, winner_handles, loser_handles, winners_score, losers_score):
        match = Match.create(winners_score=winners_score, losers_score=losers_score)
        for winner_handle in winner_handles:
            Player.create(handle=winner_handle, match=match, won=True)
        for loser_handle in loser_handles:
            Player.create(handle=loser_handle, match=match, won=False)

        self.confirm(user_handle, match.id)
        self.talk_to(
            (set(winner_handles) | set(loser_handles)) - {user_handle},
            f'Type "Confirm {match.id}" to confirm the above match, or ignore it if it\'s incorrect.',
        )

    def confirm_all(self, user_handle):
        matches = (Match.select()
                        .join(Player)
                        .where(Player.handle == user_handle,
                               Player.pending == True)
                        .order_by(Match.datetime.asc()))  # Order is significant

        if not matches:
            self.talk_to(user_handle, 'No unconfirmed matches!')
            return

        for match in matches:
            elo_deltas = self.confirm(user_handle, match.id, verbose=False)

        self.talk_to(user_handle, 'Confirmed {} matches: {}!'.format(
            len(matches),
            ", ".join(map(lambda m: '#' + str(m.id), matches)),
        ))
        self.flush_elo_cache()

    def confirm(self, user_handle, match_id, *, verbose=False):
        """
        If the match is not applied, return None.
        If the match is applied, return a defaultdict mapping user handles to elo deltas.
        """
        match = self.get_match(match_id)
        if not match: return

        players = Player.select().where(Player.handle == user_handle, Player.match == match_id)

        if not players:
            if verbose:
                self.talk_to(user_handle, f'Cannot confirm match #{match_id}! You\'re not in it!')
            return

        if not any(map(lambda p: p.pending, players)):
            if verbose:
                self.talk_to(user_handle, f'You have already confirmed match #{match_id}!')
            return

        (Player.update(pending = False)
            .where(Player.handle == user_handle, Player.match == match_id)
            .execute())

        if verbose:
            self.talk_to(user_handle, f'Confirmed match #{match_id}!')

        if not match.pending:
            observe_match(match)
            if verbose:
                self.flush_elo_cache()

    def print_leaderboard(self):
        table = []

        # TODO: Inefficient
        for user_handle in set(map(lambda p: p.handle, Player.select())):
            win_streak = self.get_win_streak(user_handle)
            streak_text = '(won {} in a row)'.format(win_streak) if win_streak >= self.min_streak_len else '-'
            name = self.slack_client.get_name(user_handle)
            table.append([name, get_elo(user_handle), get_wins(user_handle), get_losses(user_handle), streak_text])

        self.talk('```' + tabulate(table, headers=['Name', 'ELO', 'Wins', 'Losses', 'Streak']) + '```')

    def print_unconfirmed(self):
        # TODO: It might be nicer that people that need to confirm are just suffixed by '*' or something
        table = []

        # TODO: There must be a cleaner way to do this line
        for match in it.islice(filter(lambda m: m.pending, Match.select().order_by(Match.datetime.desc())), 0, 25):
            match_datetime_utc = match.datetime.replace(tzinfo=from_zone)
            match_datetime_pst = match_datetime_utc.astimezone(to_zone)
            table.append([
                match.id,
                ' '.join(map(lambda p: self.slack_client.get_name(p.handle), filter(lambda p: p.pending, match.players))),
                ' '.join(map(lambda p: self.slack_client.get_name(p.handle), match.winners)),
                ' '.join(map(lambda p: self.slack_client.get_name(p.handle), match.losers)),
                '{} - {}'.format(match.winners_score, match.losers_score),
                match_datetime_pst.strftime('%m/%d/%y %I:%M %p')
            ])

        self.talk('```' + tabulate(table, headers=['Match', 'Needs to Confirm', 'Winning team', 'Losing team', 'Score', 'Date']) + '```')

if __name__ == '__main__':
    with open('config.json') as config_data:
        config = json.load(config_data)

    if config.get('debug', False):
        print('Warning: backdoor enabled!')
        BACKDOOR_ENABLED = True

    slack_client = SlackClient(config['slack_token'])
    db.connect()
    create_tables()
    rankees_init()
    EloBot(
        slack_client,
        slack_client.get_channel_id(config['channel']),
        config['bot_name'],
        config['min_streak_length'],
    )
