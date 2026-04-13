#!/usr/bin/env python3
"""Entrypoint do projeto bb2gh."""

from dotenv import load_dotenv

load_dotenv()

from bb2gh.app import main


if __name__ == "__main__":
    main()
