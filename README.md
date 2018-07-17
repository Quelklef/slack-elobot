# ELO Bot

A basic ELO bot for Slack. Can be used to keep track of the best table tennis or smash player in the office. Issues and pull requests welcome!

## Installation

This project uses [pipenv](https://docs.pipenv.org/)

```
git clone https://github.com/samm81/slack-elobot
cd slack-elobot
cp sampleconfig.json config.json
pipenv install
```

Then edit the token value in config.json to match the one acquired from https://api.slack.com/web#authentication, and:

```
pipenv run python3 elobot.py
```

## How to use

### Declare a Game

When a game finished, you can tell the bot along the lines of:

> @sam and @norm played me and @max 14 - 2

> I deuled @sam 22-0, 13-4, and 15-6

> @sam, @marsha, @dave, and me sparred @hamlet, @romeo, and @juliet 4-20

It will then ask all users to confirm the match.

### Confirm a Match

To confirm a match you are in, type

> confirm {match_id}

Alternatively, you can confirm a range of matches with:

> confirm #4-10

or all matches with:

> confirm all

### See Leaderboard

Type

> print leaderboard

to see all players in descending rank.

### See Pending Matches

Type

> print unconfirmed

to see pending matches.
