"""Shim — junior batch lives in player_cards.generators.junior_player."""

from player_cards.generators.junior_player import PLAYERS, generate_batch, main

__all__ = ["PLAYERS", "generate_batch", "main"]

if __name__ == "__main__":
    main()
