"""
CLI entry point for openterminal.

Usage:
    openterminal --input-dir data/ --models model_a model_b --judge-model model_c
"""

from __future__ import annotations

from openterminal.pipeline.batch_processor import main


def cli() -> None:
    """Entry point registered in pyproject.toml [project.scripts]."""
    main()


if __name__ == "__main__":
    cli()
