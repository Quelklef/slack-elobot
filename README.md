# ELO Bot

A basic ELO bot for Slack. Can be used to keep track of the best table tennis or smash player in the office. Issues and pull requests welcome!

## Installation

(With virtual environments)

```
git clone https://github.com/<>/slack-elobot
cd slack-elobot
mkdir pyvenv
python3 -m venv pyvenv
source pyvenv/bin/activate
pip install pipenv
pipenv install
mv sampleconfig.json config.json
```

Then edit the token value in config.json to match the one acquired from https://api.slack.com/web#authentication

```
source pyvenv/bin/activate
python3 elobot.py
```

## How to use

### Declare a Game

When a game finished, you can tell the bot along the lines of:

> I beat @sam 22-0

> @sam and @norm crushed me and @max 14 - 2

> @sam, @marsha, @dave, and me beat @hamlet, @romeo, and @juliet 4-20

It will then ask all users to confirm the match.

### Confirm a Match

To confirm a match you are in, type

> confirm {match_id}.

Alternatively, you can confirm all pending matches with:

> confirm all

### See Leaderboard

Type

> print leaderboard

to see the top 10 players.

### Seet Pending Matches

Type

> print unconfirmed

to see pending matches.
