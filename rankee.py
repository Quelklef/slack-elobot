from collections import defaultdict

from peewee import *

from models import *
from elo import rank_teams

class Rankee:
    """Rankee is an *in memory only* object that is built up by replaying the match history."""
    def __init__(self):
        self.wins = 0
        self.losses = 0
        self.rating = 1500
        self.streak = 0

# Map user handles to rankees
rankees = defaultdict(Rankee)

# id of the last observed match
last_match_observed = 0

def observe_match(match):
    # Create these variables because I'm not sure if match.winners and match.losers are ordered by default
    winners = list(match.winners)
    losers  = list(match.losers)
    winning_deltas, losing_deltas = rank_teams(
        list(map(lambda w: rankees[w.handle].rating, winners)),
        list(map(lambda l: rankees[l.handle].rating, losers)),
    )

    for winner, winner_delta in zip(winners, winning_deltas):
        rankee = rankees[winner.handle]
        rankee.wins += 1
        rankee.rating += winner_delta
        rankee.streak += 1
    for loser, loser_delta in zip(losers, losing_deltas):
        rankee = rankees[loser.handle]
        rankee.losses += 1
        rankee.rating += loser_delta
        rankee.streak = 0

def rankees_init():
    for match in Match.select().where(Match.pending == False):
        observe_match(match)

def get_elo(user_handle):
    return rankees[user_handle].rating

def get_wins(user_handle):
    return rankees[user_handle].wins

def get_losses(user_handle):
    return rankees[user_handle].losses

def get_streak(user_handle):
    return rankees[user_handle].streak
