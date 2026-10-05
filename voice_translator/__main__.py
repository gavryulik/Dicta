import argparse

from voice_translator.config import PRODUCT_TAGLINE


def main() -> int:
    parser = argparse.ArgumentParser(description=PRODUCT_TAGLINE)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--terminal",
        action="store_true",
        help="run one Enter-controlled recording in the terminal",
    )
    arguments = parser.parse_args()

    if arguments.terminal:
        from voice_translator.app import main as terminal_main

        return terminal_main()

    from voice_translator.menu_bar import main as menu_bar_main

    return menu_bar_main()


if __name__ == "__main__":
    raise SystemExit(main())
