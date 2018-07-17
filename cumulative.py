from collections import defaultdict

from peewee import *

from models import *
from elo import rank_teams

class PlayerCumulative:
    """
    The DB only records who won what games and by how much, but not players's elos, etc.
    This class complements the Player table. It is an in-memory-only object which builds
    up the elos, win count, loss count, and streak from the match history.
    """
    def __init__(self):
        self.wins = 0
        self.losses = 0
        self.elo = 1500
        self.streak = 0

# Map user handles to rankees
cumulatives = defaultdict(PlayerCumulative)

def observe_match(match):
    # Create these variables because I'm not sure if match.winners and match.losers are ordered by default
    winning_deltas, losing_deltas = rank_teams(
        list(map(lambda w: w.elo, match.winners)),
        list(map(lambda l: l.elo, match.losers)),
    )

    for winner, winner_delta in zip(match.winners, winning_deltas):
        cumulative = cumulatives[winner.handle]
        cumulative.wins += 1
        cumulative.elo += winner_delta
        cumulative.streak += 1
    for loser, loser_delta in zip(match.losers, losing_deltas):
        cumulative = cumulatives[loser.handle]
        cumulative.losses += 1
        cumulative.elo += loser_delta
        cumulative.streak = 0
