from peewee import *
from playhouse.sqlite_ext import SqliteExtDatabase

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
        return any(map(lambda p: p.pending, self.players))

    @property
    def losers(self):
        return set(filter(lambda p: not p.won, self.players))

    @property
    def winners(self):
        return set(filter(lambda p: p.won, self.players))


@needs_table
class Player(BaseModel):
    """Represents a player in a single match."""
    match   = ForeignKeyField(Match, related_name='players')
    won     = BooleanField()
    handle  = CharField()
    pending = BooleanField(default=True)
