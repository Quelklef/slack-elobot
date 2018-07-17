from peewee import *
from playhouse.sqlite_ext import SqliteExtDatabase

from cumulative import cumulatives

db = SqliteExtDatabase('elo.db', pragmas=(('foreign_keys', True),))

needs_table_li = []
def needs_table(x):
    needs_table_li.append(x)
    return x
def create_tables():
    for nt in needs_table_li:
        nt.create_table()


class BaseModel(Model):
    class Meta:
        database = db


@needs_table
class Match(BaseModel):
    winners_score = IntegerField()
    losers_score  = IntegerField()
    datetime      = DateTimeField(constraints=[SQL('DEFAULT CURRENT_TIMESTAMP')])

    @property
    def pending(self):
        """Is at least one participant pending?"""
        return any(map(lambda pa: pa.pending, self.participations))

    @property
    def losers(self):
        return (Player
                .select()
                .join(Participation)
                .where(Participation.won == False,
                       Participation.match == self))

    @property
    def winners(self):
        return (Player
                .select()
                .join(Participation)
                .where(Participation.won == True,
                       Participation.match == self))


@needs_table
class Player(BaseModel):
    """Represents a single person who has played multiple games"""
    handle = CharField()

    @property
    def elo(self):
        return cumulatives[self.handle].elo

    @property
    def wins(self):
        return cumulatives[self.handle].wins

    @property
    def losses(self):
        return cumulatives[self.handle].losses

    @property
    def streak(self):
        return cumulatives[self.handle].streak


@needs_table
class Participation(BaseModel):
    """Represents one player participating in one match"""
    player  = ForeignKeyField(Player, related_name='participations')
    match   = ForeignKeyField(Match, related_name='participations')
    won     = BooleanField()
    pending = BooleanField(default=True)
