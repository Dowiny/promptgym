import pytest

from promptgym import cli


def test_version_flag(capsys):
    assert cli.main(["--version"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("promptgym 4.")


def test_levels_validation():
    args = cli.build_parser().parse_args(["--levels", "1", "16"])
    assert cli._validate_levels(args.levels) == [1, 16]
    with pytest.raises(SystemExit):
        cli._validate_levels([17])
    with pytest.raises(SystemExit):
        cli._validate_levels([0])


def test_parser_defaults():
    args = cli.build_parser().parse_args([])
    assert not args.compare and not args.strict and not args.judge
    assert args.levels is None
