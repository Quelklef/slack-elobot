def k_factor(elo):
    if elo > 2400:
        return 16
    elif elo < 2100:
        return 32
    return 24

def rank_game(winner_elo, loser_elo):
    """
    Rank a game between two players.
    Return the elo delta.
    """
    # From https://metinmediamath.wordpress.com/2013/11/27/how-to-calculate-the-elo-elo-including-example/
    winner_transformed_elo = 10 ** (winner_elo / 400.0)
    loser_transformed_elo  = 10 ** (loser_elo  / 400.0)

    winner_expected_score = winner_transformed_elo / (winner_transformed_elo + loser_transformed_elo)
    loser_expected_score  = loser_transformed_elo  / (winner_transformed_elo + loser_transformed_elo)

    winner_elo_delta = k_factor(winner_elo) * (1 - winner_expected_score)
    loser_elo_delta  = k_factor(loser_elo)  * (0 - loser_expected_score)

    return int(winner_elo_delta), int(loser_elo_delta)
