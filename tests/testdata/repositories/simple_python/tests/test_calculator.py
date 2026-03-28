"""Tests for calculator module."""

from src.calculator import add, subtract, Calculator


def test_add():
    assert add(1, 2) == 3


def test_subtract():
    assert subtract(5, 3) == 2


def test_calculator_history():
    calc = Calculator()
    calc.calculate("add", 1, 2)
    assert calc.last_result() == 3
