import time
import json
import re
import itertools as it
from slackclient import SlackClient
from tabulate import tabulate
from peewee import *
from datetime import datetime
from dateutil import tz
from collections import defaultdict

from models import *
from util import mean, show
from elo import rank_game
from patterns import *

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
    rankees = defaultdict(Rankee)  # TODO: Feels wrong

    def __init__(self, slack_client, channel_id, name, min_streak_len):
        self.name = name
        self.slack_client = slack_client
        self.min_streak_len = min_streak_len
        self.channel_id = channel_id

        self.init_rankees()
        self.run()

    def apply_match(self, match: Match, *, verbose=False):  # TODO: Global verbosity
        """
        Apply a match, updating all player's ELOs.
        Return a defaultdict mapping user handle to ELO delta.
        """
        # TODO: handle unequal team sizes?
        avg_winner = mean(map(lambda r: self.rankees[r.handle].rating, match.winners))
        avg_loser  = mean(map(lambda r: self.rankees[r.handle].rating, match.losers))
        total_deltas = defaultdict(float)

        for winner in match.winners:
            winner_elo_delta, loser_elo_delta = rank_game(self.rankees[winner.handle].rating, avg_loser)
            total_deltas[winner.handle] += winner_elo_delta
            self.rankees[winner.handle].rating += winner_elo_delta
            if verbose:
                self.talk_to(winner.handle, f'Your ELO is now {self.rankees[winner.handle].rating} ({show(winner_elo_delta)})')
        for loser in match.losers:
            winner_elo_delta, loser_elo_delta = rank_game(avg_winner, self.rankees[loser.handle].rating)
            total_deltas[loser.handle] += loser_elo_delta
            self.rankees[loser.handle].rating += loser_elo_delta
            if verbose:
                self.talk_to(loser.handle, f'Your ELO is now {self.rankees[loser.handle].rating} ({show(loser_elo_delta)})')

        return total_deltas

    def init_rankees(self):
        """Initializes self.rankees with the games stored in the database."""
        matches = Match.select(Match).order_by(Match.id)
        for match in matches:
            if not match.pending:
                self.apply_match(match)

    def talk(self, message):
        """Send a message to the Slack channel"""
        self.slack_client.api_call('chat.postMessage', channel=self.channel_id, text=message, username=self.name)

    def talk_to(self, handle_s, message):
        """Accepts a single handle or a list of handles."""
        message = message[0].lower() + message[1:]

        if isinstance(handle_s, list) or isinstance(handle_s, set):
            self.talk(' '.join(f'<@{handle}>' for handle in set(handle_s)) + ', ' + message)
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

    def get_pending(self, match_id):
        """Get a pending match or say an error and return None"""
        match = self.get_match(match_id)
        if not match:
            return None
        if not match.pending:
            self.talk(f'Match #{match_id} is not pending!')
            return None
        return match

    def game(self, user_handle, winner_handles, loser_handles, winners_score, losers_score):
        match = Match.create(
            winners_score=winners_score,
            losers_score=losers_score,
        )

        for winner_handle in winner_handles:
            Player.create(
                handle=winner_handle,
                match=match,
                won=True,
            )
        for loser_handle in loser_handles:
            Player.create(
                handle=loser_handle,
                match=match,
                won=False,
            )

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

        # TODO: Abstract and decouple the idea of cumulative deltas
        total_elo_deltas = defaultdict(lambda: 0)
        for match in matches:
            elo_deltas = self.confirm(user_handle, match.id)
            if elo_deltas:
                for user_handle, elo_delta in elo_deltas.items():
                    total_elo_deltas[user_handle] += elo_delta

        self.talk_to(user_handle, 'Confirmed {} matches: {}!'.format(
            len(matches),
            ", ".join(map(lambda m: '#' + str(m.id), matches)),
        ))
        for user_handle, elo_delta in total_elo_deltas.items():
            self.talk_to(user_handle, f'Your new ELO is {self.rankees[user_handle].rating} ({show(elo_delta)}).')

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
            return self.apply_match(match, verbose=verbose)

    def print_leaderboard(self):
        table = []

        # TODO: Eager so will get slow with many players.
        for user_handle, rankee in sorted(self.rankees.items(), key=lambda p: p[1].rating, reverse=True):
            print(user_handle, rankee)
            win_streak = self.get_win_streak(user_handle)
            streak_text = '(won {} in a row)'.format(win_streak) if win_streak >= self.min_streak_len else '-'
            name = self.slack_client.get_name(user_handle)
            table.append([name, rankee.rating, rankee.wins, rankee.losses, streak_text])

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

    # TODO: This method is misplaced
    # Also, it should probably just be an attribute of Rankee
    def get_win_streak(self, player_handle):
        win_streak = 0
        matches = (Match.select()
            .where(Match.pending == False)
            .join(Player)
            .where(Player.handle == player_handle,
                   Player.won == True)
            .order_by(Match.datetime.desc()))
        return len(list(matches))

if __name__ == '__main__':
    with open('config.json') as config_data:
        config = json.load(config_data)

    if config.get('debug', False):
        print('Warning: backdoor enabled!')
        BACKDOOR_ENABLED = True

    slack_client = SlackClient(config['slack_token'])
    db.connect()
    create_tables()
    EloBot(
        slack_client,
        slack_client.get_channel_id(config['channel']),
        config['bot_name'],
        config['min_streak_length'],
    )
